#!/usr/bin/env bash
# 单文件匿名化完整 curl 示例（图片 / PDF / Word / 纯文本）
#
# 用法:
#   export FILE=/path/to/sample.jpg
#   bash docs/single-file-api-curl-example.sh
#
# 依赖: curl, jq（用于解析 JSON）
set -euo pipefail

FILE="${FILE:-./sample.jpg}"
AUTH_HEADER=()

# ── 0. 可选：鉴权（AUTH_ENABLED=true 时必须） ─────────────────────────────
# 首次部署可先 POST http://8.134.38.29:8081/api/v1/auth/setup 设置密码，或 POST http://8.134.38.29:8081/api/v1/auth/register 注册。
# TOKEN=$(curl -sS -X POST http://8.134.38.29:8081/api/v1/auth/login \
#   -H "Content-Type: application/json" \
#   -d '{"username":"admin","password":"your_password"}' | jq -r .access_token)
# AUTH_HEADER=(-H "Authorization: Bearer $TOKEN")

echo "== 0) 健康检查 =="
curl -sS http://8.134.38.29:8081/health | jq .

echo "== 1) 上传文件 =="
UPLOAD_JSON=$(curl -sS "${AUTH_HEADER[@]}" -X POST http://8.134.38.29:8081/api/v1/files/upload \
  -F "file=@${FILE}" \
  -F "upload_source=playground")
echo "$UPLOAD_JSON" | jq .
FILE_ID=$(echo "$UPLOAD_JSON" | jq -r .file_id)

echo "== 2) OCR / 文本解析 =="
PARSE_JSON=$(curl -sS "${AUTH_HEADER[@]}" "http://8.134.38.29:8081/api/v1/files/${FILE_ID}/parse")
echo "$PARSE_JSON" | jq '{file_id, file_type, page_count, is_scanned, content_preview: (.content | .[0:120])}'

echo "== 3) 文本 NER（混合识别，推荐） =="
NER_JSON=$(curl -sS "${AUTH_HEADER[@]}" -X POST "http://8.134.38.29:8081/api/v1/files/${FILE_ID}/ner/hybrid" \
  -H "Content-Type: application/json" \
  -d '{"entity_type_ids": null}')
echo "$NER_JSON" | jq '{file_id, entity_count, entity_summary, sample_entities: (.entities[:3])}'

echo "== 4) 视觉识别（人脸/印章/签字等，图片或扫描 PDF） =="
VISION_JSON=$(curl -sS "${AUTH_HEADER[@]}" -X POST \
  "http://8.134.38.29:8081/api/v1/redaction/${FILE_ID}/vision?page=1&include_result_image=false" \
  -H "Content-Type: application/json" \
  -d '{}')
echo "$VISION_JSON" | jq '{file_id, page, box_count: (.bounding_boxes | length), sample_boxes: (.bounding_boxes[:2])}'

echo "== 5) 可选：预览遮罩效果 =="
PREVIEW_JSON=$(curl -sS "${AUTH_HEADER[@]}" -X POST \
  "http://8.134.38.29:8081/api/v1/redaction/${FILE_ID}/preview-image?page=1" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --argjson boxes "$(echo "$VISION_JSON" | jq '[.bounding_boxes[] | select(.selected)]')" \
    '{bounding_boxes: $boxes, config: {replacement_mode: "smart", image_redaction_method: "mosaic", image_redaction_strength: 75}}')")
echo "$PREVIEW_JSON" | jq '{file_id, page, image_base64_len: (.image_base64 | length)}'

echo "== 6) 执行匿名化 =="
EXEC_BODY=$(jq -n \
  --arg fid "$FILE_ID" \
  --argjson entities "$(echo "$NER_JSON" | jq '[.entities[] | select(.selected != false)]')" \
  --argjson boxes "$(echo "$VISION_JSON" | jq '[.bounding_boxes[] | select(.selected != false)]')" \
  '{
    file_id: $fid,
    entities: $entities,
    bounding_boxes: $boxes,
    config: {
      replacement_mode: "smart",
      entity_types: ["PERSON", "PHONE", "ID_CARD", "ORG"],
      image_redaction_method: "mosaic",
      image_redaction_strength: 75,
      image_fill_color: "#000000"
    }
  }')
EXEC_JSON=$(curl -sS "${AUTH_HEADER[@]}" -X POST http://8.134.38.29:8081/api/v1/redaction/execute \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: demo-$(date +%s)" \
  -d "$EXEC_BODY")
echo "$EXEC_JSON" | jq .

echo "== 7) 下载脱敏结果 =="
curl -sS "${AUTH_HEADER[@]}" -L \
  "http://8.134.38.29:8081/api/v1/files/${FILE_ID}/download?redacted=true" \
  -o "./redacted-${FILE_ID}$(echo "$UPLOAD_JSON" | jq -r '.filename' | sed 's/.*\././')"
echo "Saved: ./redacted-${FILE_ID}*"

echo "== 8) 脱敏报告 & 前后对比 =="
curl -sS "${AUTH_HEADER[@]}" "http://8.134.38.29:8081/api/v1/redaction/${FILE_ID}/report" | jq .
curl -sS "${AUTH_HEADER[@]}" "http://8.134.38.29:8081/api/v1/redaction/${FILE_ID}/compare" | jq '{file_id, changes_count: (.changes | length)}'

echo "Done. file_id=$FILE_ID"
