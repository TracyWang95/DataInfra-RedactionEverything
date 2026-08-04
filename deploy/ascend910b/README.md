# Ascend 910B 部署指南（DataInfra-RedactionEverything）

本文记录本仓库在 **华为昇腾 910B（aarch64）** 上的适配结论与可复现部署步骤，便于下次在干净机器或重建环境时一键拉起。

官方 VL 参考：[PaddleOCR-VL · Huawei Ascend NPU](https://www.paddleocr.ai/main/version3.x/pipeline_usage/PaddleOCR-VL-Huawei-Ascend-NPU.html)

---

## 1. 架构总览

侧车全部使用 **`--network host`**，backend/frontend 通过 `host.docker.internal` 访问。

| 服务 | 容器名 | 默认 NPU | 端口 | 镜像 / 启动脚本 |
|------|--------|----------|------|-----------------|
| HaS Text NER | `redaction-has-npu` | **0** | **8080** | `openeuler/vllm-ascend:…` / `has_npu.sh` |
| LocateAnything | `redaction-la-npu` | **1** | **8090** | `redaction-locateanything-ascend` / `la_npu.sh` |
| OCR Structure + VL client | `redaction-ocr-npu` | **2** | **8082** | `redaction-ocr-npu` / `ocr_npu.sh` |
| HaS-Image YOLO | `redaction-yolo-npu` | **3** | **8081** | `redaction-has-image-ascend` / `yolo_npu.sh` |
| PaddleOCR-VL genai | `redaction-vl-genai-npu` | **4** | **8118** | 官方 `paddleocr-genai-vllm-server:latest-huawei-npu` / `vl_genai_npu.sh` |
| Backend / Frontend | compose | — | 8000 / 3000 | `docker-compose.yml` + `docker-compose.ascend.yml` |

```
浏览器 → frontend:3000 → backend:8000
                              ├─ OCR     → :8082  (Structure@NPU2, VL client → :8118)
                              ├─ VL genai→ :8118  (官方 vLLM@NPU4)
                              ├─ HaS NER → :8080  (vllm-ascend@NPU0)
                              ├─ LA      → :8090  (torch_npu@NPU1)
                              └─ YOLO    → :8081  (ultralytics+torch_npu@NPU3)
```

**关键结论（务必记住）：**

- **PaddleOCR-VL 不支持在 paddle-custom-npu 容器里本地 `device=npu` 直推**（会踩 `view_dtype` / CPU layout 类问题）。
- 正确路径是：**官方 genai-vllm-server（NPU）+ OCR 侧车以 `OCR_VL_BACKEND=vllm-server` 当客户端**。
- OCR Structure 镜像只用 **驱动挂载**，不要把宿主机 CANN 8.3 overlay 进 paddle-npu（CANN 8.0）镜像，否则 ACL 报错。
- YOLO / 部分侧车：**不要用 `bash -l`**（ATB `set_env` 里的 torch ABI 探测会卡住）。

---

## 2. 环境前提

### 2.1 硬件 / 驱动

- 昇腾 910B（建议 ≥5 张卡；本仓库默认占用 0–4）
- 宿主机驱动示例：`npu-smi` → driver **25.2.x**
- 校验：

```bash
npu-smi info
ls /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc
```

### 2.2 软件

- OS：openEuler / Ubuntu aarch64 均可（侧车镜像自带运行时）
- Docker 25+，建议配置国内 registry mirror（见 `scripts/cn_mirrors.env` / `scripts/configure_docker_mirror.sh`）
- 磁盘：**根分区不要只剩几 GB**。官方 genai 镜像约 **18GB+**，vllm-ascend / OCR 镜像各十余 GB。  
  若 `/` 很小、`/data` 很大，强烈建议把 Docker `data-root` 指到数据盘（见 §7）。

### 2.3 仓库与镜像源

```bash
cd /path/to/DataInfra-RedactionEverything
set -a; source scripts/cn_mirrors.env; set +a
```

常用基础镜像：

| 用途 | 镜像 |
|------|------|
| HaS / LA / YOLO 基座 | `openeuler/vllm-ascend:0.11.0rc0-torch_npu2.5.1-cann8.1.rc1-python3.10-oe2403sp4` |
| OCR Structure | `ccr-2vdh3abv-pub.cnc.bj.baidubce.com/device/paddle-npu:cann800-ubuntu20-npu-910b-base-aarch64-gcc84` |
| VL genai（官方） | `ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-genai-vllm-server:latest-huawei-npu` |

---

## 3. 模型准备

```bash
python3 -m pip install -q modelscope 'huggingface_hub>=0.25'
python3 backend/scripts/download_models.py
# 或按需：
# python3 backend/scripts/download_models.py --only has
# python3 backend/scripts/download_models.py --only locateanything
```

| 模型 | 路径 | 备注 |
|------|------|------|
| HaS Text | `backend/models/has/HaS_Text_0209_0.6B/` | 需有 `config.json` |
| LocateAnything | `backend/models/locateanything/LocateAnything-3B-HF/` | 必须含 `processing_locateanything.py`、`image_processing_locateanything.py`（缺则 HF 补齐，见 §8） |
| HaS-Image YOLO | `backend/models/has_image/sensitive_seg_best.pt` | HF：`xuanwulab/HaS_Image_0209_FP32` |
| PaddleOCR / Structure / VL | 首次启动时由 PaddleX 拉到 cache | 默认 cache：`/data/ljc/caches/ocr`（可用 `OCR_CACHE_ROOT` 改） |

补齐 LA processor（若缺失）：

```bash
export HF_ENDPOINT=https://hf-mirror.com
python3 - <<'PY'
from huggingface_hub import hf_hub_download
from pathlib import Path
local = Path("backend/models/locateanything/LocateAnything-3B-HF")
for f in ("processing_locateanything.py", "image_processing_locateanything.py"):
    print(hf_hub_download("nvidia/LocateAnything-3B", f, local_dir=str(local)))
PY
```

---

## 4. 一键启动

脚本目录：`deploy/ascend910b/`

```bash
chmod +x deploy/ascend910b/*.sh
bash deploy/ascend910b/start_all.sh
```

`start_all.sh` 顺序：

1. 检查/下载模型  
2. `vl_genai_npu.sh`（官方 VL，等模型下载+ACL graph，首次可能数分钟）  
3. `ocr_npu.sh`（Structure@NPU2 + VL client → `:8118`）  
4. `has_npu.sh`  
5. `la_npu.sh`  
6. `yolo_npu.sh`（若脚本存在）  
7. `docker compose -f docker-compose.yml -f docker-compose.ascend.yml up -d backend frontend`

也可分步启动（调试时推荐）：

```bash
bash deploy/ascend910b/vl_genai_npu.sh   # 先等 :8118 /v1/models 就绪
bash deploy/ascend910b/ocr_npu.sh
bash deploy/ascend910b/has_npu.sh
bash deploy/ascend910b/la_npu.sh
bash deploy/ascend910b/yolo_npu.sh
docker compose -f docker-compose.yml -f docker-compose.ascend.yml up -d backend frontend
```

### 常用环境变量

| 变量 | 默认 | 含义 |
|------|------|------|
| `HAS_NPU_ID` / `LA_NPU_ID` / `OCR_NPU_ID` / `YOLO_NPU_ID` / `VL_NPU_ID` | 0/1/2/3/4 | 物理卡号 |
| `OCR_VL_BACKEND` | `vllm-server` | VL 走远程 genai |
| `OCR_VLLM_URL` | `http://127.0.0.1:8118/v1` | genai OpenAI 兼容地址 |
| `OCR_VL_API_MODEL_NAME` | `PaddleOCR-VL-1.6-0.9B` | 与 genai `--model_name` 一致 |
| `OCR_CACHE_ROOT` | `/data/ljc/caches/ocr` | PaddleX/HF 缓存 |
| `VLLM_ASCEND_IMAGE` | 见 `lib_npu.sh` | LA/YOLO/HaS 基座 |
| `FORCE_YOLO_REBUILD` | `0` | `1` 强制重建 YOLO 镜像 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 国内 HF |

Compose overlay（`docker-compose.ascend.yml`）会把 backend 指到：

- `OCR_BASE_URL=http://host.docker.internal:8082`
- `HAS_TEXT_VLLM_BASE_URL=http://host.docker.internal:8080/v1`
- `VISUAL_FEATURES_BASE_URL=http://host.docker.internal:8090`
- `HAS_IMAGE_URL=http://host.docker.internal:8081`
- `OCR_VL_ENABLED=true`

并 **禁用** NVIDIA 侧车 profile（`ocr` / `ner` / `visual-features`）。

---

## 5. 各组件要点

### 5.1 PaddleOCR-VL（官方 genai）— `vl_genai_npu.sh`

```bash
paddleocr genai_server \
  --model_name PaddleOCR-VL-1.6-0.9B \
  --host 0.0.0.0 --port 8118 --backend vllm
```

- 仅挂 **driver / npu-smi / dcmi**（镜像自带 CANN + vLLM Ascend）。
- 首次会下载 `PaddleOCR-VL-1.6` 权重到容器内 `~/.paddlex/official_models/`。
- 就绪探针：`curl -s http://127.0.0.1:8118/v1/models`

### 5.2 OCR Structure + VL client — `ocr_npu.sh`

- 镜像：`backend/Dockerfile.ocr.npu`（paddlepaddle 3.2.0 + paddle-custom-npu 3.2.0）
- **只挂 driver**，不挂宿主机 `ascend-toolkit` / `nnal`
- `OCR_VL_ENABLED=1` + `OCR_VL_BACKEND=vllm-server` → 调 `:8118`
- 运行时挂载最新 `backend/scripts/ocr_server.py`，方便热修
- Health：`curl -s http://127.0.0.1:8082/health`  
  期望：`device=npu:0`，`model` 含 `PaddleOCR-VL-… + PP-StructureV3`

### 5.3 HaS NER — `has_npu.sh`

- 直接跑 `vllm.entrypoints.openai.api_server`
- 挂载 `has_patches/sitecustomize.py` 兼容 tokenizer
- `--gpu-memory-utilization 0.35 --enforce-eager`

### 5.4 LocateAnything — `la_npu.sh`

- 镜像：`backend/Dockerfile.locateanything.ascend`（**transformers==4.57.1**，基座 5.x 会炸）
- aarch64 **无 decord 轮子** → 使用 `backend/scripts/decord_stub`（仅图片服务）
- 端口 8090：注意宿主机是否有其它进程占 IPv4；部分 BMC/Redfish 只占 IPv6 link-local，一般可并存

### 5.5 YOLO HaS-Image — `yolo_npu.sh`

- 镜像：`backend/Dockerfile.has_image.ascend`
- 需要 `mesa-libGL`（ultralytics → cv2）
- `HAS_IMAGE_DEVICE=npu:0`（容器内可见卡映射为 0）
- **禁止 `bash -l` 启动**

---

## 6. 验收清单

```bash
# 进程与卡
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
npu-smi info

# 侧车 health
curl -s http://127.0.0.1:8080/v1/models | head
curl -s http://127.0.0.1:8090/health
curl -s http://127.0.0.1:8082/health
curl -s http://127.0.0.1:8081/health
curl -s http://127.0.0.1:8118/v1/models

# 聚合（应 all_online: true）
curl -s http://127.0.0.1:8000/health/services | python3 -m json.tool

# OCR 冒烟（JSON base64）
python3 - <<'PY'
import base64, json, urllib.request
img=open("docs/manual/single.png","rb").read()
body=json.dumps({"image": base64.b64encode(img).decode()}).encode()
for ep in ("/ocr","/structure"):
  req=urllib.request.Request(f"http://127.0.0.1:8082{ep}", data=body,
    headers={"Content-Type":"application/json"})
  with urllib.request.urlopen(req, timeout=180) as r:
    d=json.loads(r.read()); print(ep, "boxes", len(d.get("boxes") or []), "elapsed", d.get("elapsed"))
PY
```

服务端细分日志关键字：

- VL：`PaddleOCR-VL parser produced … in Xs`
- Structure：`[OCR-prof] structure=…s char=…s`

---

## 7. Docker 磁盘（910 机器常见坑）

根分区 ~70G 装不下多份 16–27G 镜像时：

1. 停 Docker → 把 `/var/lib/docker` rsync 到 `/data/docker`
2. `/etc/docker/daemon.json` 增加 `"data-root": "/data/docker"`
3. 若已有容器 bind 了旧绝对路径 volume，可再设兼容链接：  
   `ln -sfn /data/docker /var/lib/docker`
4. 确认：`docker info | grep 'Docker Root Dir'` → `/data/docker`
5. 确认无误后删除旧备份目录以释放 `/`

拉 genai 前先：`df -h / /data` 与 `docker system df`。

---

## 8. 已知问题与对策

| 现象 | 原因 | 对策 |
|------|------|------|
| VL `view_dtype` / CPU Undefined layout | 在 paddle-npu 里本地跑 VL | 改用官方 genai + `vllm-server` |
| OCR ACL 500001 / CANN 不匹配 | 宿主机 CANN 8.3 overlay 进 CANN 8.0 镜像 | OCR/YOLO **只挂 driver** |
| YOLO / 侧车启动卡住无日志 | `bash -l` 触发 ATB ABI `import torch` | 用非 login `python …` CMD |
| YOLO `libGL.so.1` | 缺 OpenGL 库 | 镜像内装 `mesa-libGL` |
| LA 缺 `processing_locateanything.py` | 模型包不完整 | HF 补文件（§3） |
| LA `requires decord` | aarch64 无轮子 | `decord_stub` + `PYTHONPATH` |
| `no space left on device` | Docker 在小根分区 | §7 迁 data-root |
| 健康页 OCR 名称 | 以 sidecar `/health.model` 为准 | VL+Structure 同时就绪时显示二者 |

**不要做的事：**

- 不要再启 `redaction-ocr-vl-cpu` 作为主路径（仅历史兜底，`ocr_cpu.sh` 保留但不推荐）。
- 不要用通用 `vllm-ascend` 硬套 PaddleOCR-VL 权重（tokenizer / ROPE 易炸）；用官方 genai 镜像。
- 不要在 OCR NPU 镜像里 `pip uninstall opencv*`（易破坏依赖）。

---

## 9. 日常运维

```bash
# 重启单个侧车
bash deploy/ascend910b/ocr_npu.sh
bash deploy/ascend910b/vl_genai_npu.sh

# 看日志
docker logs -f redaction-vl-genai-npu
docker logs -f redaction-ocr-npu
docker logs -f redaction-la-npu

# 停全部侧车（compose 另算）
docker rm -f redaction-vl-genai-npu redaction-ocr-npu \
  redaction-has-npu redaction-la-npu redaction-yolo-npu
```

共享挂载逻辑见 `lib_npu.sh`：`npu_docker_devices` / `npu_docker_volumes` / `npu_docker_common_flags`。

---

## 10. 相关文件索引

```
deploy/ascend910b/
  README.md                 # 本文
  lib_npu.sh                # NPU device/volume 公共函数
  start_all.sh              # 一键启动
  vl_genai_npu.sh           # 官方 VL genai
  ocr_npu.sh / ocr_cpu.sh   # OCR（NPU 主路径 / CPU 兜底）
  has_npu.sh + has_patches/ # HaS NER
  la_npu.sh                 # LocateAnything
  yolo_npu.sh               # HaS-Image YOLO
docker-compose.ascend.yml   # backend 指到 host 侧车
backend/Dockerfile.ocr.npu
backend/Dockerfile.locateanything.ascend
backend/Dockerfile.has_image.ascend
backend/scripts/decord_stub/
backend/scripts/ocr_server.py
scripts/cn_mirrors.env
```

性能对照报告（历史）：`P800_MODEL_PERF_REPORT.md`、`P800_BATCH_PERF_REPORT.md`。
