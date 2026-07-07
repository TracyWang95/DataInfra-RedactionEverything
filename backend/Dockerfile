FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime dependencies for the lightweight API image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

# Keep model-serving stacks out of the default backend image. GPU/OCR/vision
# dependencies are installed by their profile-gated service images instead.
# Note: requirements-ci.txt (floating versions) is used intentionally.
# requirements.lock is NOT suitable here: it pins the full local dev stack
# (paddlepaddle-gpu, paddleocr) that this slim image must exclude, while
# missing runtime deps this image needs (SQLAlchemy, PyMySQL, psycopg,
# numpy, opencv-python-headless, openpyxl).
COPY requirements-ci.txt .
RUN pip install -r requirements-ci.txt

COPY . .

RUN mkdir -p /app/data /app/uploads /app/outputs

RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
