"""
腾讯云 DNSPod 认证器插件
"""

import logging
import time
from typing import Any, Callable, Optional

import zope.interface
from certbot import errors, interfaces
from certbot.plugins import dns_common

from .tencent_client import TencentCloudDNSClient

logger = logging.getLogger(__name__)


@zope.interface.implementer(interfaces.IAuthenticator)
@zope.interface.provider(interfaces.IPluginFactory)
class Authenticator(dns_common.DNSAuthenticator):
    """腾讯云 DNSPod 认证器"""

    description = "通过腾讯云 DNSPod API 获取证书，使用 DNS-01 验证"
    ttl = 600  # DNS 记录 TTL

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.credentials: Optional[dns_common.CredentialsConfiguration] = None

    @classmethod
    def add_parser_arguments(cls, add: Callable[..., None], default_propagation_seconds: int = 30) -> None:
        """添加命令行参数"""
        super().add_parser_arguments(add, default_propagation_seconds)
        add("credentials", help="腾讯云 API 凭证文件路径")

    def more_info(self) -> str:
        """返回插件的更多信息"""
        return (
            "此插件通过腾讯云 DNSPod API 配置 DNS 记录来完成 DNS-01 验证。"
            "需要在凭证文件中配置腾讯云 SecretId 和 SecretKey。"
        )

    def _setup_credentials(self) -> None:
        """设置 API 凭证"""
        self.credentials = self._configure_credentials(
            "credentials",
            "腾讯云 API 凭证文件路径",
            {
                "secret_id": "腾讯云 SecretId",
                "secret_key": "腾讯云 SecretKey",
            }
        )

    def _perform(self, domain: str, validation_name: str, validation: str) -> None:
        """
        添加 DNS TXT 记录进行验证

        :param domain: 要验证的域名
        :param validation_name: 验证记录名称
        :param validation: 验证值
        """
        self._get_tencent_client().add_txt_record(validation_name, validation)

    def _cleanup(self, domain: str, validation_name: str, validation: str) -> None:
        """
        清理 DNS TXT 记录

        :param domain: 要验证的域名
        :param validation_name: 验证记录名称
        :param validation: 验证值
        """
        self._get_tencent_client().del_txt_record(validation_name, validation)

    def _get_tencent_client(self) -> "_TencentCloudDNSHelper":
        """获取腾讯云 DNS 客户端"""
        if not self.credentials:
            raise errors.Error("凭证未配置")

        secret_id = self.credentials.conf("secret_id")
        secret_key = self.credentials.conf("secret_key")

        return _TencentCloudDNSHelper(secret_id, secret_key, self.ttl)


def _get_rr_from_record_name(record_name: str, domain: str) -> str:
    """
    从记录名称获取主机记录（DNSPod 的 SubDomain）

    :param record_name: 完整的记录名称
    :param domain: 根域名
    :return: 主机记录
    """
    if record_name.endswith("." + domain):
        rr = record_name[: -len(domain) - 1]
    else:
        rr = record_name

    return rr


class _TencentCloudDNSHelper:
    """腾讯云 DNS 辅助类"""

    def __init__(self, secret_id: str, secret_key: str, ttl: int):
        """
        初始化 DNS 辅助类

        :param secret_id: 腾讯云 SecretId
        :param secret_key: 腾讯云 SecretKey
        :param ttl: DNS 记录 TTL
        """
        self.client = TencentCloudDNSClient(secret_id, secret_key)
        self.ttl = ttl
        self._record_ids = {}  # 存储添加的记录 ID，用于清理

    def add_txt_record(self, record_name: str, record_content: str) -> None:
        """
        添加 TXT 记录

        :param record_name: 记录名称
        :param record_content: 记录内容
        """
        domain = self._get_domain_from_record_name(record_name)
        rr = _get_rr_from_record_name(record_name, domain)

        logger.debug(f"添加 TXT 记录: {record_name} -> {record_content}")

        try:
            # 检查是否已存在相同的记录
            existing_records = self.client.get_domain_records(domain, rr, "TXT")
            for record in existing_records:
                if record["value"] == record_content:
                    logger.info(f"TXT 记录已存在: {record_name}")
                    self._record_ids[record_name] = record["record_id"]
                    return

            # 添加新记录
            record_id = self.client.add_domain_record(domain, rr, "TXT", record_content, self.ttl)
            self._record_ids[record_name] = record_id

            # 等待 DNS 传播
            time.sleep(10)

        except Exception as e:
            logger.error(f"添加 TXT 记录失败: {e}")
            raise errors.PluginError(f"添加 TXT 记录失败: {e}")

    def del_txt_record(self, record_name: str, record_content: str) -> None:
        """
        删除 TXT 记录

        :param record_name: 记录名称
        :param record_content: 记录内容
        """
        logger.debug(f"删除 TXT 记录: {record_name}")

        try:
            # 优先使用存储的记录 ID 删除
            if record_name in self._record_ids:
                record_id = self._record_ids[record_name]
                domain = self._get_domain_from_record_name(record_name)
                self.client.delete_domain_record(domain, record_id)
                del self._record_ids[record_name]
                return

            # 如果没有存储的记录 ID，尝试查找并删除
            domain = self._get_domain_from_record_name(record_name)
            rr = _get_rr_from_record_name(record_name, domain)

            existing_records = self.client.get_domain_records(domain, rr, "TXT")
            for record in existing_records:
                if record["value"] == record_content:
                    self.client.delete_domain_record(domain, record["record_id"])
                    break
            else:
                logger.warning(f"未找到要删除的 TXT 记录: {record_name}")

        except Exception as e:
            logger.error(f"删除 TXT 记录失败: {e}")
            # 清理时的错误不应该导致程序失败
            logger.warning(f"清理 TXT 记录时出错，但不影响证书获取: {e}")

    @staticmethod
    def _get_domain_from_record_name(record_name: str) -> str:
        """
        从记录名称获取域名

        :param record_name: 完整的记录名称
        :return: 根域名
        """
        # 移除 _acme-challenge. 前缀
        if record_name.startswith("_acme-challenge."):
            domain = record_name[16:]  # 移除 "_acme-challenge." 前缀
        else:
            domain = record_name

        return TencentCloudDNSClient.get_root_domain(domain)
