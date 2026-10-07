# Certbot DNS 腾讯云插件

这是一个用于 Certbot 的腾讯云 DNSPod 插件，支持通过腾讯云 DNSPod API 进行 DNS-01 验证来获取 SSL 证书。支持泛域名。

## 功能特性

- 支持通过腾讯云 DNSPod API 自动管理 DNS 记录
- 支持泛域名
- 支持 Certbot 3 和 5 版本
- 兼容 Python 3.9–3.14（Python 3.9 使用 Certbot 3，Python 3.14 使用 Certbot 5）
- 支持 DNS-01 验证方式
- 自动清理本次创建的临时 DNS 记录，保留已有记录
- 完善的错误处理和日志记录

## 安装

### 从 PyPI 安装

```bash
pip3 install certbot-dns-tencent
```

也可以使用 uv 安装（插件与 Certbot 在同一环境中）：

```bash
uv tool install --with certbot-dns-tencent "certbot>=5,<6"
```

Python 3.9 请安装 Certbot 3；已有 Certbot 环境应使用该环境的 Python 安装插件。

## 配置文件

```ini
dns_tencent_secret_id = ??
dns_tencent_secret_key = ??
```

使用临时凭证时，可额外配置 `dns_tencent_token`。

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

默认 TXT TTL 为 600 秒，可通过 `--dns-tencent-ttl` 调整；DNS 传播等待由 `--dns-tencent-propagation-seconds` 控制。

## 腾讯云权限配置

确保您的腾讯云 API 密钥（SecretId / SecretKey）具有 DNSPod 的管理权限：

`QcloudDNSPodFullAccess`，或自定义策略包含以下操作：

- `dnspod:DescribeDomainList`
- `dnspod:CreateRecord`
- `dnspod:DeleteRecord`
- `dnspod:DescribeRecordList`

## 自动部署

此程序只是 certbot 的 DNS 验证插件，如果需要自动运行申请部署，可以使用 [AutoCert](https://github.com/tiyee/AutoCert)。
