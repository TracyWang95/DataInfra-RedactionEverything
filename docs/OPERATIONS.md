# Operations Guide

This document covers production operations for DataInfra-RedactionEverything.

---

## Log Format

The backend uses **structured JSON logging** in production and **human-readable text** in debug mode.

| Mode | `LOG_JSON` | `DEBUG` | Output |
|---|---|---|---|
| Production | `true` (default) | `false` | JSON lines — one JSON object per log entry |
| Development | `false` | `true` | Colored text with timestamps |

JSON log fields: `timestamp`, `level`, `message`, `module`, `request_id` (when available).

**Example JSON log line:**

```json
{"timestamp": "2026-04-07T12:00:00Z", "level": "INFO", "message": "Request processed", "module": "app.api.routes", "request_id": "abc123"}
```

Pipe JSON logs to your preferred aggregator (ELK, Datadog, Loki, CloudWatch, etc.).

---

## Monitoring Endpoints

All endpoints are served by the FastAPI backend on port 8000.

| Endpoint | Purpose | Auth Required |
|---|---|---|
| `GET /health` | Basic liveness check — returns `{"status": "ok"}` | No |
| `GET /health/services` | Dependency health — reports status of OCR, NER, and Vision microservices | No |
| `GET /metrics` | Prometheus-compatible metrics (if enabled) | No |

### Recommended Usage

- **Load balancer health check**: Point to `/health` with a 10s interval and 5s timeout.
- **Dashboard / alerting**: Poll `/health/services` to detect downstream microservice failures (OCR offline, NER model not loaded, etc.).

---

## Database Backup

The backend uses **SQLite** (`jobs.sqlite3` in `DATA_DIR`) for job tracking.

### Automatic Hourly Backup

SQLite is a single file, making backup straightforward. Recommended cron job on the Docker host:

```bash
# Backup SQLite database every hour (uses SQLite Online Backup API for consistency)
0 * * * * docker exec <backend-container> sqlite3 /app/data/jobs.sqlite3 ".backup '/app/data/backups/jobs_$(date +\%Y\%m\%d_\%H\%M).sqlite3'"
```

Alternatively, copy the volume directly (stop writes or use `.backup` to avoid corruption):

```bash
0 * * * * cp /var/lib/docker/volumes/datainfra-redactioneverything_backend-data/_data/jobs.sqlite3 \
             /backups/jobs_$(date +%Y%m%d_%H%M).sqlite3
```

### Retention

Keep at least 48 hourly backups and 7 daily backups. Example cleanup:

```bash
# Delete hourly backups older than 48 hours
find /backups -name 'jobs_*.sqlite3' -mmin +2880 -delete
```

---

## Recommended Alerting Thresholds

| Metric / Check | Condition | Severity | Action |
|---|---|---|---|
| `/health` response | Non-200 or timeout > 5s | **Critical** | Restart backend container |
| `/health/services` — OCR | Status `offline` for > 5 min | **Warning** | Check OCR container logs, GPU memory |
| `/health/services` — NER | Status `offline` for > 5 min | **Warning** | Check NER container, model file |
| `/health/services` — Vision | Status `offline` for > 5 min | **Warning** | Check Vision container, GPU memory |
| Container memory | > 90% of limit (4 GB backend) | **Warning** | Investigate memory leak, increase limit |
| Container restart count | > 3 in 10 min | **Critical** | Check logs for crash loop |
| Disk usage (`DATA_DIR` volume) | > 80% capacity | **Warning** | Clean old uploads/outputs, expand volume |
| SQLite backup age | Last backup > 2 hours old | **Warning** | Check cron job, disk space |
| Response latency (p95) | > 30s for non-OCR endpoints | **Warning** | Check backend CPU, concurrency settings |
| OCR inference latency (p95) | > 360s (matches `OCR_TIMEOUT`) | **Warning** | Check GPU utilization, model warm-up |

### Example Prometheus Alert Rules

```yaml
groups:
  - name: redaction-platform
    rules:
      - alert: BackendDown
        expr: up{job="redaction-backend"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Backend is unreachable"

      - alert: HighMemoryUsage
        expr: container_memory_usage_bytes{name=~".*backend.*"} / container_spec_memory_limit_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Backend memory usage above 90%"
```
