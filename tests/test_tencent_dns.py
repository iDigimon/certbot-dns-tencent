"""
certbot-dns-tencent 单元测试

使用 unittest + unittest.mock，mock 掉腾讯云 DNSPod SDK 客户端，
无需真实凭证即可运行。
"""

import unittest
from unittest import mock

from certbot import errors
from certbot.plugins import dns_common

from certbot_dns_tencent import tencent_client
from certbot_dns_tencent.dns_tencent import (
    Authenticator,
    _TencentCloudDNSHelper,
    _get_rr_from_record_name,
)
from certbot_dns_tencent.tencent_client import (
    DEFAULT_RECORD_LINE,
    TencentCloudDNSClient,
)


def make_record_item(record_id, value, name, type_="TXT", ttl=600, line="默认"):
    """构造一个模拟的 DNSPod RecordListItem"""
    item = mock.Mock()
    item.RecordId = record_id
    item.Value = value
    item.Name = name
    item.Type = type_
    item.TTL = ttl
    item.Line = line
    return item


class TencentCloudDNSClientTest(unittest.TestCase):
    """客户端层测试：TencentCloudDNSClient"""

    def _patched_client(self):
        """返回一个内部 SDK 客户端被 mock 的 TencentCloudDNSClient"""
        with mock.patch.object(tencent_client.dnspod_client, "DnspodClient") as m:
            client = TencentCloudDNSClient("sid", "skey")
        return client, m

    def test_create_client_uses_credentials_and_endpoint(self):
        """_create_client 应使用传入的凭证与 dnspod endpoint 创建客户端"""
        with mock.patch.object(tencent_client.dnspod_client, "DnspodClient") as mock_ctor:
            TencentCloudDNSClient("my-id", "my-key")

        # DnspodClient(cred, "", profile) 被调用一次
        self.assertEqual(mock_ctor.call_count, 1)
        args, _ = mock_ctor.call_args
        cred = args[0]
        # region 传空字符串
        self.assertEqual(args[1], "")
        # 凭证内容正确
        self.assertEqual(cred.secret_id, "my-id")
        self.assertEqual(cred.secret_key, "my-key")

    def test_get_domain_records_parses_list(self):
        """get_domain_records 应正确解析 RecordList 为 dict 列表"""
        client, _ = self._patched_client()
        response = mock.Mock()
        response.RecordList = [
            make_record_item(101, "val1", "www"),
            make_record_item(102, "val2", "_acme-challenge", ttl=300),
        ]
        client.client.DescribeRecordList = mock.Mock(return_value=response)

        result = client.get_domain_records("example.com", "www", "TXT")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {
            "record_id": 101,
            "sub_domain": "www",
            "type": "TXT",
            "value": "val1",
            "ttl": 600,
            "line": "默认",
        })
        self.assertEqual(result[1]["record_id"], 102)
        self.assertEqual(result[1]["ttl"], 300)

        # 校验请求参数：类型、主机记录、ErrorOnEmpty
        req = client.client.DescribeRecordList.call_args.args[0]
        self.assertEqual(req.Domain, "example.com")
        self.assertEqual(req.SubDomain, "www")
        self.assertEqual(req.RecordType, "TXT")
        self.assertEqual(req.ErrorOnEmpty, "no")

    def test_get_domain_records_empty(self):
        """RecordList 为 None 时应返回空列表"""
        client, _ = self._patched_client()
        response = mock.Mock()
        response.RecordList = None
        client.client.DescribeRecordList = mock.Mock(return_value=response)

        self.assertEqual(client.get_domain_records("example.com", "www"), [])

    def test_get_domain_records_propagates_error(self):
        """SDK 抛异常时应向上抛出"""
        client, _ = self._patched_client()
        client.client.DescribeRecordList = mock.Mock(side_effect=RuntimeError("boom"))

        with self.assertRaises(RuntimeError):
            client.get_domain_records("example.com", "www")

    def test_add_domain_record_returns_id(self):
        """add_domain_record 应返回 RecordId"""
        client, _ = self._patched_client()
        response = mock.Mock()
        response.RecordId = 999
        client.client.CreateRecord = mock.Mock(return_value=response)

        record_id = client.add_domain_record("example.com", "www", "TXT", "val", 600)

        self.assertEqual(record_id, 999)
        req = client.client.CreateRecord.call_args.args[0]
        self.assertEqual(req.Domain, "example.com")
        self.assertEqual(req.SubDomain, "www")
        self.assertEqual(req.RecordType, "TXT")
        self.assertEqual(req.Value, "val")
        self.assertEqual(req.TTL, 600)
        # 默认线路
        self.assertEqual(req.RecordLine, DEFAULT_RECORD_LINE)

    def test_add_domain_record_no_id_raises(self):
        """CreateRecord 未返回 RecordId 时应抛异常"""
        client, _ = self._patched_client()
        response = mock.Mock()
        response.RecordId = None
        client.client.CreateRecord = mock.Mock(return_value=response)

        with self.assertRaises(Exception):
            client.add_domain_record("example.com", "www", "TXT", "val")

    def test_delete_domain_record_success(self):
        """delete_domain_record 成功应返回 True 并传 Domain/RecordId"""
        client, _ = self._patched_client()
        client.client.DeleteRecord = mock.Mock()

        self.assertTrue(client.delete_domain_record("example.com", 999))
        req = client.client.DeleteRecord.call_args.args[0]
        self.assertEqual(req.Domain, "example.com")
        self.assertEqual(req.RecordId, 999)

    def test_get_root_domain(self):
        """根域名提取：取最后两段"""
        self.assertEqual(TencentCloudDNSClient.get_root_domain("a.b.example.com"), "example.com")
        self.assertEqual(TencentCloudDNSClient.get_root_domain("example.com"), "example.com")
        self.assertEqual(TencentCloudDNSClient.get_root_domain("localhost"), "localhost")


class HelperTest(unittest.TestCase):
    """辅助层测试：_TencentCloudDNSHelper"""

    def _helper(self):
        """返回一个内部 client 被 mock 的 helper"""
        with mock.patch.object(tencent_client.dnspod_client, "DnspodClient"):
            helper = _TencentCloudDNSHelper("sid", "skey", 600)
        helper.client = mock.Mock(spec=TencentCloudDNSClient)
        return helper

    def test_add_txt_record_new(self):
        """无现存记录时应调用 add_domain_record 并存 id"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(return_value=[])
        helper.client.add_domain_record = mock.Mock(return_value=555)

        with mock.patch("certbot_dns_tencent.dns_tencent.time.sleep"):
            helper.add_txt_record("_acme-challenge.www.example.com", "token-value")

        helper.client.add_domain_record.assert_called_once_with(
            "example.com", "_acme-challenge.www", "TXT", "token-value", 600
        )
        # 记录 id 已缓存
        self.assertEqual(
            helper._record_ids["_acme-challenge.www.example.com"], 555
        )

    def test_add_txt_record_already_exists(self):
        """已存在相同值的记录时应跳过（幂等，不重复添加）"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(
            return_value=[{"record_id": 77, "value": "token-value"}]
        )
        helper.client.add_domain_record = mock.Mock()

        with mock.patch("certbot_dns_tencent.dns_tencent.time.sleep"):
            helper.add_txt_record("_acme-challenge.example.com", "token-value")

        # 不应调用添加
        helper.client.add_domain_record.assert_not_called()
        # 复用已有记录的 id
        self.assertEqual(
            helper._record_ids["_acme-challenge.example.com"], 77
        )

    def test_add_txt_record_raises_plugin_error(self):
        """底层异常应转为 certbot PluginError"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(
            side_effect=RuntimeError("api down")
        )

        with self.assertRaises(errors.PluginError):
            helper.add_txt_record("_acme-challenge.example.com", "token-value")

    def test_del_txt_record_with_cached_id(self):
        """有已存 id 时应优先用 id 删除"""
        helper = self._helper()
        helper._record_ids["_acme-challenge.example.com"] = 42
        helper.client.delete_domain_record = mock.Mock()

        helper.del_txt_record("_acme-challenge.example.com", "token-value")

        helper.client.delete_domain_record.assert_called_once_with("example.com", 42)
        # 缓存被清理
        self.assertNotIn("_acme-challenge.example.com", helper._record_ids)

    def test_del_txt_record_fallback_query(self):
        """无已存 id 时应回退查询并删除匹配项"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(
            return_value=[
                {"record_id": 1, "value": "other"},
                {"record_id": 2, "value": "token-value"},
            ]
        )
        helper.client.delete_domain_record = mock.Mock()

        helper.del_txt_record("_acme-challenge.example.com", "token-value")

        # 只删除 value 匹配的那条
        helper.client.delete_domain_record.assert_called_once_with("example.com", 2)

    def test_del_txt_record_not_found_no_raise(self):
        """查无记录时不应抛异常（清理失败不影响出证）"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(return_value=[])
        helper.client.delete_domain_record = mock.Mock()

        # 不应抛出
        helper.del_txt_record("_acme-challenge.example.com", "token-value")
        helper.client.delete_domain_record.assert_not_called()

    def test_del_txt_record_swallows_error(self):
        """清理时底层抛异常应被吞掉（不影响证书获取）"""
        helper = self._helper()
        helper.client.get_domain_records = mock.Mock(
            side_effect=RuntimeError("api down")
        )

        # 不应抛出
        helper.del_txt_record("_acme-challenge.example.com", "token-value")

    def test_get_domain_from_record_name(self):
        """应正确去掉 _acme-challenge. 前缀并取根域"""
        self.assertEqual(
            _TencentCloudDNSHelper._get_domain_from_record_name(
                "_acme-challenge.www.example.com"
            ),
            "example.com",
        )
        self.assertEqual(
            _TencentCloudDNSHelper._get_domain_from_record_name("example.com"),
            "example.com",
        )


class AuthenticatorTest(unittest.TestCase):
    """认证器层测试：Authenticator"""

    def test_more_info(self):
        """more_info 返回非空字符串"""
        self.assertIsInstance(Authenticator.more_info(None), str)
        self.assertTrue(len(Authenticator.more_info(None)) > 0)

    def test_add_parser_arguments(self):
        """add_parser_arguments 应注册 credentials 参数"""
        add = mock.Mock()
        Authenticator.add_parser_arguments(add)
        # 至少调用了注册 credentials
        calls = [c.args[0] for c in add.call_args_list if c.args]
        self.assertIn("credentials", calls)

    def test_get_tencent_client_without_credentials(self):
        """凭证未配置时 _get_tencent_client 应抛 errors.Error"""
        authenticator = Authenticator.__new__(Authenticator)
        authenticator.credentials = None
        authenticator.ttl = 600
        with self.assertRaises(errors.Error):
            authenticator._get_tencent_client()

    def test_get_tencent_client_with_credentials(self):
        """配置了凭证时应返回 helper（client 被 mock）"""
        authenticator = Authenticator.__new__(Authenticator)
        creds = mock.Mock()
        creds.conf = lambda key: {"secret_id": "sid", "secret_key": "skey"}.get(key)
        authenticator.credentials = creds
        authenticator.ttl = 600

        with mock.patch.object(tencent_client.dnspod_client, "DnspodClient"):
            helper = authenticator._get_tencent_client()
        self.assertIsInstance(helper, _TencentCloudDNSHelper)

    def test_perform_delegates_to_helper(self):
        """_perform 应委托给 helper.add_txt_record"""
        authenticator = Authenticator.__new__(Authenticator)
        authenticator.ttl = 600
        authenticator.credentials = mock.Mock()

        with mock.patch.object(Authenticator, "_get_tencent_client") as m:
            helper = m.return_value
            authenticator._perform(
                "example.com", "_acme-challenge.example.com", "token-value"
            )
        helper.add_txt_record.assert_called_once_with(
            "_acme-challenge.example.com", "token-value"
        )

    def test_cleanup_delegates_to_helper(self):
        """_cleanup 应委托给 helper.del_txt_record"""
        authenticator = Authenticator.__new__(Authenticator)
        authenticator.ttl = 600
        authenticator.credentials = mock.Mock()

        with mock.patch.object(Authenticator, "_get_tencent_client") as m:
            helper = m.return_value
            authenticator._cleanup(
                "example.com", "_acme-challenge.example.com", "token-value"
            )
        helper.del_txt_record.assert_called_once_with(
            "_acme-challenge.example.com", "token-value"
        )


class UtilTest(unittest.TestCase):
    """工具函数测试"""

    def test_get_rr_from_record_name(self):
        """主机记录提取"""
        self.assertEqual(
            _get_rr_from_record_name("_acme-challenge.www.example.com", "example.com"),
            "_acme-challenge.www",
        )
        self.assertEqual(
            _get_rr_from_record_name("www.example.com", "example.com"),
            "www",
        )
        # 不以 .domain 结尾时原样返回
        self.assertEqual(
            _get_rr_from_record_name("example.com", "example.com"),
            "example.com",
        )


if __name__ == "__main__":
    unittest.main()
