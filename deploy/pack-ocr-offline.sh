#!/usr/bin/env bash
# Build and export an air-gapped OCR image (CUDA 12.6 / cu126).
#
# Fixes baked into redaction-ocr:latest:
#   1) PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK + local weights (no HF/ModelScope)
#   2) libgomp1 in the image (libgomp.so.1)
#   3) CMD ["python", "ocr_server.py"] so init_ocr() actually runs
#
# Usage:
#   bash deploy/pack-ocr-offline.sh
#   bash deploy/pack-ocr-offline.sh /path/to/output-dir
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
STAGING="$BACKEND/models/paddleocr-offline"
OUT_DIR="${1:-$ROOT/dist}"
IMAGE_TAG="${OCR_IMAGE_TAG:-redaction-ocr:latest}"
TAR_NAME="${OCR_TAR_NAME:-redaction-ocr-cu126.tar.gz}"
BASE_IMAGE="${DOCKER_BASE_IMAGE:-python:3.11-slim}"

PDX_SRC="${PADDLE_PDX_MODELS:-$HOME/.paddlex/official_models}"
VL_SRC="${PADDLE_VL_MODEL:-$BACKEND/models/paddleocr-vl/PaddleOCR-VL-1.6}"

# Models required by ocr_server.py (PP-StructureV3 + PaddleOCR-VL-1.6 + word engine)
NEEDED_MODELS=(
  PP-DocLayoutV3
  PP-DocLayout_plus-L
  PP-DocBlockLayout
  PP-OCRv6_medium_det
  PP-OCRv6_medium_rec
)

echo "==> Staging offline PaddleX models -> $STAGING"
mkdir -p "$STAGING"
missing=0
for name in "${NEEDED_MODELS[@]}"; do
  src="$PDX_SRC/$name"
  if [[ ! -d "$src" ]]; then
    echo "MISSING model: $src"
    missing=1
    continue
  fi
  echo "  copy $name"
  rm -rf "$STAGING/$name"
  cp -a "$src" "$STAGING/$name"
done

if [[ ! -d "$VL_SRC" ]]; then
  echo "MISSING PaddleOCR-VL model: $VL_SRC"
  missing=1
else
  echo "  copy PaddleOCR-VL-1.6 from $VL_SRC"
  rm -rf "$STAGING/PaddleOCR-VL-1.6"
  mkdir -p "$STAGING/PaddleOCR-VL-1.6"
  cp -a "$VL_SRC"/. "$STAGING/PaddleOCR-VL-1.6/"
fi

if [[ "$missing" -ne 0 ]]; then
  echo
  echo "ERROR: missing model weights. On an online machine, warm them once:"
  echo "  export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True"
  echo "  python -c \"from paddleocr import PPStructureV3, PaddleOCRVL; PPStructureV3(use_table_recognition=False,use_seal_recognition=False,use_formula_recognition=False,use_chart_recognition=False); PaddleOCRVL(pipeline_version='v1.6')\""
  echo "Then re-run this script."
  exit 1
fi

echo "==> Model staging summary"
du -sh "$STAGING"/* | sort -h
echo

mkdir -p "$OUT_DIR"
echo "==> Building $IMAGE_TAG (Dockerfile.ocr, cu126, Tsinghua pip)"
docker build \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  -f "$BACKEND/Dockerfile.ocr" \
  -t "$IMAGE_TAG" \
  "$BACKEND"

echo "==> Verifying CUDA build tag inside image (expect 12.6)"
docker run --rm --entrypoint python "$IMAGE_TAG" -c '
import paddle, paddleocr
print("paddle   =", paddle.__version__)
print("paddleocr=", getattr(paddleocr, "__version__", "?"))
print("cuda     =", paddle.version.cuda())
assert str(paddle.version.cuda()).startswith("12.6"), paddle.version.cuda()
print("OK: cu126 confirmed")
'

echo "==> Verifying libgomp + offline env baked in"
docker run --rm --entrypoint sh "$IMAGE_TAG" -c '
  set -e
  python -c "import ctypes.util; p=ctypes.util.find_library(\"gomp\"); print(\"libgomp\", p); assert p"
  python -c "import os; assert os.environ.get(\"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK\")==\"True\"; print(\"env OK\")"
  test -d /opt/paddlex/official_models/PP-OCRv6_medium_det
  test -d /opt/paddlex/official_models/PaddleOCR-VL-1.6
  echo "libgomp + models OK"
'

OUT_TAR="$OUT_DIR/$TAR_NAME"
echo "==> Exporting $OUT_TAR"
docker save "$IMAGE_TAG" | gzip > "$OUT_TAR"
ls -lh "$OUT_TAR"

echo
echo "Done. On the bastion:"
echo "  gunzip -c $TAR_NAME | docker load"
echo "  # compose command must be: [\"python\", \"ocr_server.py\"]"
echo "  docker compose up -d ocr   # or model-bundle-ocr-1"
echo "  docker logs -f model-bundle-ocr-1"
echo "  # expect: versions ... cuda=12.6  and  Service ready"
