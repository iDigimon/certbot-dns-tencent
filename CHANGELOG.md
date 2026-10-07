# 更新日志

## 2.0.0

- 支持 Python 3.9–3.14 与 Certbot 3/5，集中维护兼容层，移除旧 zope 装饰器。
- 使用 uv、Hatchling、pytest 和 tox-uv，CI/CD 运行十组兼容环境并验证安装后的 wheel。
- 通过 DNSPod 完整分页查询选择最长匹配的托管域名，支持多级后缀、独立子域 zone 和 IDN。
- 复用客户端，按名称与 TXT 值管理挑战状态，只清理本次创建的记录，保留已有 TXT。
- 支持双 TXT 值、共享值引用、删除失败重试，以及已删除记录的幂等清理。
- 删除逐条固定等待，统一使用 Certbot 的传播等待；增加可配置 TTL 和临时凭证 token。
- SDK 请求设置超时，异常信息仅报告错误码，避免输出凭证和 TXT 验证值。
- 保留 `dns-tencent` 入口、原凭证字段和命令行参数；新增 `DescribeDomainList` 权限要求。

Python 3.9 使用 Certbot 3；Python 3.14 使用 Certbot 5。详细开发约束与测试方法见 AGENTS.md。
