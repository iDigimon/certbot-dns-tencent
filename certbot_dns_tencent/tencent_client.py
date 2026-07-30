"""
腾讯云 DNSPod API 客户端
"""

import logging
from typing import Any, Dict, List

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.dnspod.v20210323 import dnspod_client, models

logger = logging.getLogger(__name__)

# DNSPod 默认解析线路名称
DEFAULT_RECORD_LINE = "默认"


class TencentCloudDNSClient:
    """腾讯云 DNSPod 客户端"""

    def __init__(self, secret_id: str, secret_key: str):
        """
        初始化腾讯云 DNSPod 客户端

        :param secret_id: 腾讯云 SecretId
        :param secret_key: 腾讯云 SecretKey
        """
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.client = self._create_client()

    def _create_client(self) -> dnspod_client.DnspodClient:
        """创建 DNSPod 客户端"""
        cred = credential.Credential(self.secret_id, self.secret_key)
        http_profile = HttpProfile(endpoint="dnspod.tencentcloudapi.com")
        client_profile = ClientProfile(httpProfile=http_profile)
        # DNSPod 是非区域性服务，region 传空字符串即可
        return dnspod_client.DnspodClient(cred, "", client_profile)

    def get_domain_records(
        self, domain_name: str, sub_domain: str, record_type: str = "TXT"
    ) -> List[Dict[str, Any]]:
        """
        获取域名记录

        :param domain_name: 主域名
        :param sub_domain: 主机记录
        :param record_type: 记录类型
        :return: 记录列表
        """
        try:
            # 腾讯云 SDK 的请求对象构造函数无参，需先实例化再逐个赋值
            request = models.DescribeRecordListRequest()
            request.Domain = domain_name
            request.SubDomain = sub_domain
            request.RecordType = record_type
            # 查无记录时不报错，便于做幂等的“先查后加”判断
            request.ErrorOnEmpty = "no"
            response = self.client.DescribeRecordList(request)

            if response.RecordList:
                return [
                    {
                        "record_id": record.RecordId,
                        "sub_domain": record.Name,
                        "type": record.Type,
                        "value": record.Value,
                        "ttl": record.TTL,
                        "line": record.Line,
                    }
                    for record in response.RecordList
                ]
            return []
        except Exception as e:
            logger.error(f"获取域名记录失败: {e}")
            raise

    def add_domain_record(
        self,
        domain_name: str,
        sub_domain: str,
        record_type: str,
        value: str,
        ttl: int = 600,
    ) -> int:
        """
        添加域名记录

        :param domain_name: 主域名
        :param sub_domain: 主机记录
        :param record_type: 记录类型
        :param value: 记录值
        :param ttl: TTL 值
        :return: 记录 ID
        """
        try:
            request = models.CreateRecordRequest()
            request.Domain = domain_name
            request.SubDomain = sub_domain
            request.RecordType = record_type
            request.RecordLine = DEFAULT_RECORD_LINE
            request.Value = value
            request.TTL = ttl
            response = self.client.CreateRecord(request)

            if response.RecordId is not None:
                logger.info(f"成功添加 DNS 记录: {sub_domain}.{domain_name} -> {value}")
                return response.RecordId
            else:
                raise Exception("添加记录失败，未返回记录 ID")
        except Exception as e:
            logger.error(f"添加域名记录失败: {e}")
            raise

    def delete_domain_record(self, domain_name: str, record_id: int) -> bool:
        """
        删除域名记录

        :param domain_name: 主域名
        :param record_id: 记录 ID
        :return: 是否成功
        """
        try:
            request = models.DeleteRecordRequest()
            request.Domain = domain_name
            request.RecordId = record_id
            self.client.DeleteRecord(request)

            logger.info(f"成功删除 DNS 记录: {record_id}")
            return True
        except Exception as e:
            logger.error(f"删除域名记录失败: {e}")
            raise

    @staticmethod
    def get_root_domain(domain: str) -> str:
        """
        获取根域名

        :param domain: 完整域名
        :return: 根域名
        """
        # 简单的根域名提取逻辑，取最后两段
        parts = domain.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return domain
