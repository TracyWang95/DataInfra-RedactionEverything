# 国内基础镜像（DaoCloud）+ 清华 PyPI / Debian
ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app

# Runtime dependencies for the lightweight API image.
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list \
    && apt-get update && apt-get install -y --no-install-recommends \
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
