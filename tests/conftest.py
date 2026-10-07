"""Use real plugin configuration and mock only the external SDK boundary."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from certbot_dns_tencent.dns_tencent import Authenticator, _TencentCloudDNSHelper
from certbot_dns_tencent.tencent_client import TencentCloudDNSClient


@pytest.fixture
def client(monkeypatch):
    sdk = Mock()
    monkeypatch.setattr(
        "certbot_dns_tencent.tencent_client.dnspod_client.DnspodClient", Mock(return_value=sdk)
    )
    result = TencentCloudDNSClient("id", "secret", token="session")
    result.page_size = 2
    return result


@pytest.fixture
def helper(monkeypatch):
    cloud = Mock(spec=TencentCloudDNSClient)
    cloud.list_zones.return_value = ["example.com", "example.co.uk", "sub.example.co.uk"]
    cloud.get_domain_records.return_value = []
    cloud.add_domain_record.side_effect = ["101", "102", "103"]
    monkeypatch.setattr(
        "certbot_dns_tencent.dns_tencent.TencentCloudDNSClient", Mock(return_value=cloud)
    )
    return _TencentCloudDNSHelper("id", "secret", 600)


@pytest.fixture
def authenticator(helper):
    config = SimpleNamespace(
        dns_tencent_credentials=None,
        dns_tencent_ttl=600,
        dns_tencent_propagation_seconds=0,
        noninteractive_mode=True,
    )
    result = Authenticator(config, "dns-tencent")
    result._helper = helper
    return result
