"""Tencent Cloud DNSPod API v20210323 adapter using the official SDK."""

from typing import Any, Optional

from certbot import errors
from tencentcloud.common.credential import Credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.dnspod.v20210323 import dnspod_client, models

DEFAULT_RECORD_LINE = "默认"
_NO_RECORD = "ResourceNotFound.NoDataOfRecord"


class TencentCloudDNSClient:
    """Manage individual records without replacing existing TXT RRsets."""

    page_size = 100

    def __init__(self, secret_id: str, secret_key: str, *, token: Optional[str] = None) -> None:
        http = HttpProfile(endpoint="dnspod.tencentcloudapi.com", reqTimeout=30)
        # retryer=None uses the SDK's NoopRetryer. Never retry ambiguous writes.
        self.client = dnspod_client.DnspodClient(
            Credential(secret_id, secret_key, token), "", ClientProfile(httpProfile=http)
        )

    def _call(self, operation: str, request: Any) -> Any:
        try:
            response = getattr(self.client, operation)(request)
        except TencentCloudSDKException as exc:
            # Do not include provider messages, credentials or TXT values.
            raise errors.PluginError(
                f"Tencent DNSPod {operation} failed ({exc.get_code()})"
            ) from exc
        except OSError as exc:
            raise errors.PluginError(f"Tencent DNSPod {operation} failed (network error)") from exc
        if response is None:
            raise errors.PluginError(f"Tencent DNSPod {operation} returned an empty response")
        return response

    @staticmethod
    def _page_complete(offset: int, count: int, total: Optional[int], kind: str) -> bool:
        if total is None or total < offset or (count == 0 and offset < total):
            raise errors.PluginError(f"Tencent DNSPod returned an incomplete {kind} list")
        return offset >= total

    def list_zones(self) -> list[str]:
        """Read every page of zones before selecting the longest matching one."""
        zones = []
        offset = 0
        while True:
            request = models.DescribeDomainListRequest()
            request.Type = "ALL"
            request.Offset = offset
            request.Limit = self.page_size
            body = self._call("DescribeDomainList", request)
            items = body.DomainList or []
            zones.extend(item.Name for item in items)
            offset += len(items)
            total = body.DomainCountInfo.DomainTotal if body.DomainCountInfo else None
            if self._page_complete(offset, len(items), total, "zone"):
                return zones

    def get_domain_records(
        self, domain_name: str, sub_domain: str, record_type: str = "TXT"
    ) -> list[dict[str, Any]]:
        """List exact, enabled records on the default line, including all pages."""
        records = []
        offset = 0
        while True:
            request = models.DescribeRecordListRequest()
            request.Domain = domain_name
            request.SubDomain = sub_domain
            request.RecordType = record_type
            request.Offset = offset
            request.Limit = self.page_size
            request.ErrorOnEmpty = "no"
            try:
                body = self._call("DescribeRecordList", request)
            except errors.PluginError as exc:
                if getattr(exc.__cause__, "code", None) == _NO_RECORD and offset == 0:
                    return []
                raise
            items = body.RecordList or []
            records.extend(
                {
                    "record_id": str(item.RecordId),
                    "sub_domain": item.Name,
                    "type": item.Type,
                    "value": item.Value,
                    "ttl": item.TTL,
                    "line": item.Line,
                }
                for item in items
                if item.Type == record_type
                and item.Name.lower() == sub_domain.lower()
                and item.Status == "ENABLE"
                and item.LineId == "0"
            )
            offset += len(items)
            total = body.RecordCountInfo.TotalCount if body.RecordCountInfo else None
            if self._page_complete(offset, len(items), total, "record"):
                return records

    def add_domain_record(
        self, domain_name: str, sub_domain: str, record_type: str, value: str, ttl: int = 600
    ) -> str:
        request = models.CreateRecordRequest()
        request.Domain = domain_name
        request.SubDomain = sub_domain
        request.RecordType = record_type
        request.RecordLine = DEFAULT_RECORD_LINE
        request.RecordLineId = "0"
        request.Value = value
        request.TTL = ttl
        body = self._call("CreateRecord", request)
        if not body.RecordId:
            raise errors.PluginError("Tencent DNSPod did not return a new record ID")
        return str(body.RecordId)

    def delete_domain_record(self, domain_name: str, record_id: str) -> bool:
        request = models.DeleteRecordRequest()
        request.Domain = domain_name
        request.RecordId = int(record_id)
        try:
            self._call("DeleteRecord", request)
        except errors.PluginError as exc:
            if getattr(exc.__cause__, "code", None) != _NO_RECORD:
                raise
        return True
