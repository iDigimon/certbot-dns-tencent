# Certbot DNS 腾讯云插件

这是一个用于 Certbot 的腾讯云 DNSPod 插件，支持通过腾讯云 DNSPod API 进行 DNS-01 验证来获取 SSL 证书。支持泛域名。

## 功能特性

- 支持通过腾讯云 DNSPod API 自动管理 DNS 记录
- 支持泛域名
- 支持 certbot 3 版本（更低版本未测试）
- 兼容 Python 3.8+ 版本
- 支持 DNS-01 验证方式
- 自动清理临时 DNS 记录
- 完善的错误处理和日志记录

## 安装

### 从 PyPI 安装

```bash
pip3 install certbot-dns-tencent
```

## 配置文件

```ini
dns_tencent_secret_id = ??
dns_tencent_secret_key = ??
```

修改配置文件权限（假如文件是 `~/tencent.ini`）：

```bash
chmod 600 ~/tencent.ini
```

## 运行

```bash
certbot certonly \
  --authenticator dns-tencent \
  --dns-tencent-credentials ~/tencent.ini \
  --dns-tencent-propagation-seconds 30 \
  -d "*.example.com" \
  -d "example.com"
```

## 腾讯云权限配置

确保您的腾讯云 API 密钥（SecretId / SecretKey）具有 DNSPod 的管理权限：

`QcloudDNSPodFullAccess`，或自定义策略包含以下操作：

- `dnspod:CreateRecord`
- `dnspod:DeleteRecord`
- `dnspod:DescribeRecordList`

## 单元测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## 自动部署

此程序只是 certbot 的 DNS 验证插件，如果需要自动运行申请部署，可以使用 [AutoCert](https://github.com/tiyee/AutoCert)。
