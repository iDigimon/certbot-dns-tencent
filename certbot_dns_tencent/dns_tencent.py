"""DNS-01 authenticator shared by Certbot 3, 4 and 5."""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from certbot import errors
from certbot.plugins import dns_common

from certbot_dns_tencent.compat import DNSAuthenticator
from certbot_dns_tencent.tencent_client import TencentCloudDNSClient

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    name = name.strip().rstrip(".").lower()
    if not name or any(not label or "*" in label for label in name.split(".")):
        raise errors.PluginError("Expected a non-wildcard DNS name")
    try:
        return name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise errors.PluginError("Invalid DNS name") from exc


class Authenticator(DNSAuthenticator):
    """Use Certbot's base lifecycle, credentials and cross-platform file checks."""

    description = "通过腾讯云 DNSPod API 完成 DNS-01 验证，支持泛域名"
    ttl = 600

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.credentials: Optional[dns_common.CredentialsConfiguration] = None
        self._helper: Optional[_TencentCloudDNSHelper] = None

    @classmethod
    def add_parser_arguments(
        cls, add: Callable[..., None], default_propagation_seconds: int = 30
    ) -> None:
        super().add_parser_arguments(add, default_propagation_seconds)
        add("credentials", help="腾讯云 API 凭证 INI 文件路径")
        add("ttl", type=int, default=600, help="TXT 记录 TTL 秒数（默认 600）")

    def more_info(self) -> str:
        return "通过腾讯云 DNSPod API 创建独立的 TXT 验证记录，仅清理本次创建的记录。"

    def _setup_credentials(self) -> None:
        ttl = self.conf("ttl")
        propagation = self.conf("propagation-seconds")
        if ttl is None or ttl < 1:
            raise errors.PluginError("--dns-tencent-ttl must be at least 1")
        if propagation is None or propagation < 0:
            raise errors.PluginError("--dns-tencent-propagation-seconds must be non-negative")
        if self._helper is not None:
            return
        self.credentials = self._configure_credentials(
            "credentials",
            "腾讯云 API 凭证文件路径",
            {
                "secret_id": "腾讯云 SecretId",
                "secret_key": "腾讯云 SecretKey",
            },
        )
        self.ttl = ttl
        self._helper = _TencentCloudDNSHelper(
            self.credentials.conf("secret_id"),
            self.credentials.conf("secret_key"),
            self.ttl,
            token=self.credentials.conf("token"),
        )

    def _get_tencent_client(self) -> "_TencentCloudDNSHelper":
        if self._helper is None:
            raise errors.PluginError("Tencent DNSPod credentials have not been configured")
        return self._helper

    def _perform(self, domain: str, validation_name: str, validation: str) -> None:
        self._get_tencent_client().add_txt_record(validation_name, validation)

    def _cleanup(self, domain: str, validation_name: str, validation: str) -> None:
        if self._helper is not None:
            self._helper.del_txt_record(validation_name, validation)


def _get_rr_from_record_name(record_name: str, domain: str) -> str:
    record_name, domain = _normalize_name(record_name), _normalize_name(domain)
    if record_name == domain:
        return "@"
    if record_name.endswith("." + domain):
        return record_name[: -len(domain) - 1]
    raise errors.PluginError(f"DNS name {record_name} is outside zone {domain}")


@dataclass
class _RecordLease:
    domain: str
    record_id: str
    created: bool
    users: int = 1


class _TencentCloudDNSHelper:
    """Track record ownership by both DNS name and TXT value."""

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        ttl: int,
        *,
        token: Optional[str] = None,
    ) -> None:
        self.client = TencentCloudDNSClient(secret_id, secret_key, token=token)
        self.ttl = ttl
        self._zones: Optional[list[str]] = None
        self._leases: dict[tuple[str, str], _RecordLease] = {}

    def _get_domain_from_record_name(self, record_name: str) -> str:
        record_name = _normalize_name(record_name)
        if self._zones is None:
            # Cache only complete discovery; never guess a zone after an API error.
            zones = [_normalize_name(zone) for zone in self.client.list_zones()]
            self._zones = zones
        matches = [
            zone for zone in self._zones if record_name == zone or record_name.endswith("." + zone)
        ]
        if not matches:
            raise errors.PluginError(f"No managed Tencent DNSPod zone found for {record_name}")
        return max(matches, key=lambda zone: len(zone.split(".")))

    def add_txt_record(self, record_name: str, record_content: str) -> None:
        record_name = _normalize_name(record_name)
        key = (record_name, record_content)
        if key in self._leases:
            self._leases[key].users += 1
            return
        domain = self._get_domain_from_record_name(record_name)
        rr = _get_rr_from_record_name(record_name, domain)
        records = self.client.get_domain_records(domain, rr, "TXT")
        existing = next((item for item in records if item["value"] == record_content), None)
        record_id = (
            existing["record_id"]
            if existing
            else self.client.add_domain_record(domain, rr, "TXT", record_content, self.ttl)
        )
        self._leases[key] = _RecordLease(domain, record_id, created=existing is None)
        logger.info("TXT challenge ready at %s", record_name)
        # Certbot performs one propagation wait after all challenges are ready.

    def del_txt_record(self, record_name: str, record_content: str) -> None:
        key = (_normalize_name(record_name), record_content)
        lease = self._leases.get(key)
        if lease is None:
            return
        if lease.users == 1 and lease.created:
            try:
                self.client.delete_domain_record(lease.domain, lease.record_id)
            except errors.PluginError as exc:
                logger.warning("Unable to clean TXT record at %s: %s", key[0], exc)
                # Save ownership so a subsequent cleanup can retry the deletion.
                return
            logger.info("Cleaned TXT challenge at %s", key[0])
        lease.users -= 1
        if lease.users == 0:
            del self._leases[key]
