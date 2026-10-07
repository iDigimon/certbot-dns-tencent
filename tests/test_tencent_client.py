"""Mock the SDK transport while retaining real DNSPod request/response DTOs."""

import json
from unittest.mock import Mock

import pytest
from certbot import errors
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.dnspod.v20210323 import models

from certbot_dns_tencent.tencent_client import TencentCloudDNSClient


def dto(cls, data):
    result = cls()
    result.from_json_string(json.dumps(data))
    return result


def zones(names, total):
    return dto(
        models.DescribeDomainListResponse,
        {"DomainCountInfo": {"DomainTotal": total}, "DomainList": [{"Name": n} for n in names]},
    )


def records(items, total):
    return dto(
        models.DescribeRecordListResponse,
        {"RecordCountInfo": {"TotalCount": total}, "RecordList": items},
    )


def record(id_, name="host", value="token", type_="TXT", status="ENABLE", line="0"):
    return {
        "RecordId": id_,
        "Name": name,
        "Value": value,
        "Type": type_,
        "Status": status,
        "LineId": line,
        "TTL": 600,
        "Line": "默认",
    }


def request_map(request):
    return {k: v for k, v in json.loads(request.to_json_string()).items() if v is not None}


def test_sdk_credentials_endpoint_timeout_and_no_retries(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("certbot_dns_tencent.tencent_client.dnspod_client.DnspodClient", factory)
    TencentCloudDNSClient("id", "secret", token="session")
    credentials, region, profile = factory.call_args.args
    assert credentials.secret_id == "id"
    assert credentials.secret_key == "secret"
    assert credentials.token == "session"
    assert region == ""
    assert profile.httpProfile.endpoint == "dnspod.tencentcloudapi.com"
    assert profile.httpProfile.reqTimeout == 30
    assert profile.retryer is None
    assert profile.disable_region_breaker is True


def test_all_zone_pages(client):
    call = client.client.DescribeDomainList
    call.side_effect = [zones(["example.com", "example.co.uk"], 3), zones(["sub.example.co.uk"], 3)]
    assert client.list_zones() == ["example.com", "example.co.uk", "sub.example.co.uk"]
    assert [request_map(item.args[0]) for item in call.call_args_list] == [
        {"Type": "ALL", "Offset": 0, "Limit": 2},
        {"Type": "ALL", "Offset": 2, "Limit": 2},
    ]


def test_all_record_pages_and_exact_host_filter(client):
    call = client.client.DescribeRecordList
    call.side_effect = [
        records([record(1), record(2, name="other-host")], 3),
        records([record(3, value="second-value")], 3),
    ]
    found = client.get_domain_records("example.com", "host")
    assert [(item["record_id"], item["value"]) for item in found] == [
        ("1", "token"),
        ("3", "second-value"),
    ]
    assert request_map(call.call_args.args[0]) == {
        "Domain": "example.com",
        "SubDomain": "host",
        "RecordType": "TXT",
        "Offset": 2,
        "Limit": 2,
        "ErrorOnEmpty": "no",
    }


def test_only_enabled_txt_on_default_line_reused(client):
    client.client.DescribeRecordList.return_value = records(
        [record(1, status="DISABLE"), record(2, type_="CNAME"), record(3, line="10")], 3
    )
    assert client.get_domain_records("example.com", "host") == []


def test_exact_host_is_case_insensitive(client):
    client.client.DescribeRecordList.return_value = records([record(1, name="HOST")], 1)
    assert len(client.get_domain_records("example.com", "host")) == 1


def test_empty_lists(client):
    client.client.DescribeDomainList.return_value = zones([], 0)
    client.client.DescribeRecordList.return_value = records([], 0)
    assert client.list_zones() == []
    assert client.get_domain_records("example.com", "@") == []


@pytest.mark.parametrize("kind", ["zones", "records"])
@pytest.mark.parametrize("total", [10, None, -1])
def test_incomplete_pagination_fails(client, kind, total):
    if kind == "zones":
        client.client.DescribeDomainList.return_value = zones([], total)
        operation = client.list_zones
    else:
        client.client.DescribeRecordList.return_value = records([], total)

        def operation():
            return client.get_domain_records("example.com", "host")

    with pytest.raises(errors.PluginError, match="incomplete"):
        operation()


@pytest.mark.parametrize("kind", ["zones", "records"])
def test_missing_count_metadata_fails(client, kind):
    if kind == "zones":
        client.client.DescribeDomainList.return_value = dto(models.DescribeDomainListResponse, {})
        operation = client.list_zones
    else:
        client.client.DescribeRecordList.return_value = dto(models.DescribeRecordListResponse, {})

        def operation():
            return client.get_domain_records("example.com", "host")

    with pytest.raises(errors.PluginError, match="incomplete"):
        operation()


def test_create_delete_real_sdk_request_schema(client):
    client.client.CreateRecord.return_value = dto(models.CreateRecordResponse, {"RecordId": 123})
    assert client.add_domain_record("example.com", "@", "TXT", "token", 600) == "123"
    assert request_map(client.client.CreateRecord.call_args.args[0]) == {
        "Domain": "example.com",
        "SubDomain": "@",
        "RecordType": "TXT",
        "Value": "token",
        "TTL": 600,
        "RecordLine": "默认",
        "RecordLineId": "0",
    }
    assert client.delete_domain_record("example.com", "123") is True
    assert request_map(client.client.DeleteRecord.call_args.args[0]) == {
        "Domain": "example.com",
        "RecordId": 123,
    }


def test_create_requires_record_id(client):
    client.client.CreateRecord.return_value = dto(models.CreateRecordResponse, {})
    with pytest.raises(errors.PluginError, match="record ID"):
        client.add_domain_record("example.com", "host", "TXT", "token")


@pytest.mark.parametrize(
    "operation", ["DescribeDomainList", "DescribeRecordList", "CreateRecord", "DeleteRecord"]
)
def test_permission_errors_are_redacted(client, operation):
    getattr(client.client, operation).side_effect = TencentCloudSDKException(
        "UnauthorizedOperation", "sensitive request details"
    )
    with pytest.raises(errors.PluginError, match="UnauthorizedOperation") as exc:
        if operation == "DescribeDomainList":
            client.list_zones()
        elif operation == "DescribeRecordList":
            client.get_domain_records("example.com", "host")
        elif operation == "CreateRecord":
            client.add_domain_record("example.com", "host", "TXT", "token")
        else:
            client.delete_domain_record("example.com", "123")
    assert "sensitive" not in str(exc.value)


def test_already_deleted_record_is_success(client):
    client.client.DeleteRecord.side_effect = TencentCloudSDKException(
        "ResourceNotFound.NoDataOfRecord", "gone"
    )
    assert client.delete_domain_record("example.com", "123") is True


def test_empty_record_api_code(client):
    client.client.DescribeRecordList.side_effect = TencentCloudSDKException(
        "ResourceNotFound.NoDataOfRecord", "gone"
    )
    assert client.get_domain_records("example.com", "host") == []


def test_empty_error_on_later_page_is_not_a_complete_result(client):
    client.client.DescribeRecordList.side_effect = [
        records([record(1), record(2)], 3),
        TencentCloudSDKException("ResourceNotFound.NoDataOfRecord", "gone"),
    ]
    with pytest.raises(errors.PluginError):
        client.get_domain_records("example.com", "host")


def test_empty_response(client):
    client.client.DescribeDomainList.return_value = None
    with pytest.raises(errors.PluginError, match="empty response"):
        client.list_zones()


def test_network_failure_is_redacted(client):
    client.client.DescribeDomainList.side_effect = OSError("sensitive network details")
    with pytest.raises(errors.PluginError, match="network error") as exc:
        client.list_zones()
    assert "sensitive" not in str(exc.value)
