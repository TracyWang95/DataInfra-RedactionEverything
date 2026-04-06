# Security Policy / 安全策略

## Supported Versions / 支持版本

| Version | Status |
|---|---|
| `main` branch | :white_check_mark: Supported / 支持中 |

## Reporting a Vulnerability / 报告漏洞

If you discover a security vulnerability, please follow responsible disclosure:

如果你发现安全漏洞，请遵循负责任的披露流程：

1. **Do not** open a public Issue. / **不要**在公开 Issue 中描述漏洞细节。
2. Use [GitHub Security Advisories](https://github.com/TracyWang95/DataInfra-RedactionEverything/security/advisories/new) to report privately. / 使用 GitHub Security Advisories 私下报告。
3. Or contact the maintainer directly via [GitHub profile](https://github.com/TracyWang95). / 或通过 GitHub 主页联系维护者。

We will acknowledge receipt within **48 hours** and aim to provide a fix within **7 days**.

我们会在 **48 小时**内确认收到，并在 **7 天**内提供修复方案。

## Security Design / 安全设计原则

| Principle / 原则 | Implementation / 实现 |
|---|---|
| **无云端依赖** | 所有 AI 推理（OCR、NER、Vision）本地运行，零外部 API 调用 |
| **数据隔离** | 上传文件仅存储在本地文件系统 `backend/uploads/` |
| **网络边界** | 服务设计为内网部署，请勿暴露到公网 |
| **模型来源** | 模型权重仅从官方渠道下载（[Hugging Face](https://huggingface.co/xuanwulab)、[PaddlePaddle](https://www.paddlepaddle.org.cn/)） |

## Deployment Best Practices / 部署建议

- 部署在 **VPN 或防火墙**后，不要将 3000、8000、8080-8082 端口暴露到不信任的网络
- 生产环境启用 **`AUTH_ENABLED=true`** 开启 JWT 认证
- 定期清理 `backend/uploads/` 和 `backend/outputs/` 中的已处理文件
- 保持依赖更新：`pip install --upgrade` + `npm audit`
- 使用**加密存储**保护存放敏感文档的主机文件系统

## Data Handling / 数据处理

- 不收集、不传输任何遥测数据或使用分析
- 所有处理在内存和本地磁盘完成
- 任务队列数据库仅存储任务元数据，不包含文档内容
- 用户负责处理完成后的敏感文件管理和清除
