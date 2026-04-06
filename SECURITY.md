# Security Policy

## Supported Versions

| Version | Status |
|---|---|
| `main` branch | :white_check_mark: Supported |

## Reporting a Vulnerability

If you discover a security vulnerability in **DataInfra-RedactionEverything**, please follow responsible disclosure:

1. **Do not** open a public GitHub Issue with vulnerability details.
2. Instead, use [GitHub Security Advisories](https://github.com/TracyWang95/DataInfra-RedactionEverything/security/advisories/new) to report privately.
3. Alternatively, contact the maintainer directly via the email listed on the [GitHub profile](https://github.com/TracyWang95).

We will acknowledge receipt within **48 hours** and aim to provide a fix or mitigation plan within **7 days**.

## Security Design Principles

DataInfra-RedactionEverything is built with a **security-first, on-premise architecture**:

| Principle | Implementation |
|---|---|
| **No cloud dependencies** | All AI inference (OCR, NER, Vision) runs locally. Zero external API calls. |
| **Data isolation** | Uploaded files are stored in `backend/uploads/` on your local filesystem only. |
| **Network boundary** | Services are designed for internal network deployment. Do not expose to the public internet without additional hardening. |
| **Model provenance** | Model weights should only be downloaded from official sources ([Hugging Face Hub](https://huggingface.co/xuanwulab), [PaddlePaddle](https://www.paddlepaddle.org.cn/)). |

## Best Practices for Deployment

- Deploy behind a **VPN or firewall** — do not expose ports 3000, 8000, 8080-8082 to untrusted networks.
- Enable **`AUTH_ENABLED=true`** in production to require JWT authentication.
- Regularly **clean up** processed files from `backend/uploads/` and `backend/outputs/` after export.
- Keep dependencies updated — run `pip install --upgrade` and `npm audit` periodically.
- Use **encrypted storage** for the host filesystem where sensitive documents reside.

## Data Handling

- No telemetry, analytics, or usage data is collected or transmitted.
- All processing happens in-memory and on local disk.
- The job queue database (`data/jobs.sqlite3`) stores task metadata only, not document contents.
- Users are responsible for managing and purging sensitive files after processing.
