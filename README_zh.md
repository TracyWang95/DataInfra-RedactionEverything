<div align="center">

# DataInfra &middot; RedactionEverything

**本地优先的非结构化数据匿名化工作台**

不止个人信息，也不止固定规则。RedactionEverything 面向合同、扫描件、图片、PDF、Word 和纯文本，使用语义模型、OCR、视觉检测和可配置清单，把需要保护的内容识别出来，再交给人工复核和导出流程。

[![License](https://img.shields.io/badge/license-Personal%20Use-blue.svg)](./LICENSE)
[![CI](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml/badge.svg)](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything?style=social)](https://github.com/TracyWang95/DataInfra-RedactionEverything)

**语言：** [English](./README.md) | 中文

> 本项目采用自定义 [Personal Use License](./LICENSE)：个人用途可免费使用；付费工作、咨询交付、公司、机构、政府、团队或其他组织的生产使用、集成、SaaS、托管服务和再分发需取得单独商业授权。
>
> 商业授权、支持服务、采购条款或定制交付请联系：**wwang11@alumni.nd.edu**。

<p>
  <a href="#项目简介">项目简介</a> &middot;
  <a href="#项目定位">项目定位</a> &middot;
  <a href="#核心能力">核心能力</a> &middot;
  <a href="#快速开始">快速开始</a> &middot;
  <a href="#系统架构">系统架构</a> &middot;
  <a href="#模型服务">模型服务</a> &middot;
  <a href="#模型与致谢">模型与致谢</a> &middot;
  <a href="#技术栈">技术栈</a> &middot;
  <a href="#安全与部署">安全与部署</a> &middot;
  <a href="#许可证">许可证</a>
</p>

</div>

---

## 项目简介

**RedactionEverything** 是一个面向本地部署的文档数据匿名化系统。它把非结构化文件拆成文本线和图像线处理，识别姓名、机构、证件号、账号、地址、金额、日期、印章、人脸、签字等敏感内容，再提供可视化复核、批量任务管理和结果导出。

项目的设计目标不是做一个只能识别少数 PII 的固定工具，而是提供一套可以被行业清单驱动的工作台：

- 通用清单覆盖个人、组织、通信、证件、账号、金额、时间、地址等基础敏感实体。
- 行业清单面向法律、金融、医疗场景，按行业语义补充专用识别项。
- 文本识别默认交给 HaS Text 语义模型；正则只作为自定义兜底项保留。
- 图像识别由 OCR + HaS、HaS Image YOLO 和 VLM checklist 组成，分别处理文字、可视区域和签字等语义视觉特征。
- 所有业务文件、配置、识别结果和导出物都保留在本地运行环境中。

---

## 项目定位

RedactionEverything 的定位不是一个只做文本 PII 的轻量过滤器，而是一套完整的匿名化工作台。类似 [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) 这样的项目，是高吞吐文本 token 级 PII 检测的优秀基线；本项目关注的是另一个更贴近业务落地的层面：中文和中英混合业务文档、扫描 PDF、Word 合同、图片、视觉隐私区域、人工复核、批量交付和本地化部署。

这里的差异不是口号，而是范围不同：

- **语言和 schema 深度：** 中文合同、法律材料、金融资料、医疗文件和中英混合内容，往往需要行业清单和可配置 NER，而不是少量固定标签。
- **真实文档形态：** 生产文件通常不是干净文本，而是包含 PDF 版式、OCR 噪声、表格、印章、签字、截图、照片和扫描页。
- **视觉覆盖：** OCR+HaS 处理图中文字，HaS Image YOLO 处理可视区域，VLM rubric 检测补上手写签字等语义视觉目标。
- **业务流程：** 识别只是第一步，系统还需要复核、修正、选择、批量任务、状态管理、结果历史和打包导出。
- **隐私边界：** 默认架构坚持本地或内网推理，避免把原始敏感文件交给外部托管 API。

---

## 核心能力

| 能力 | 说明 |
|---|---|
| 单次处理 | 支持 TXT、DOCX、PDF、扫描 PDF、PNG、JPG 等文件，上传后直接识别、复核和导出 |
| 批量处理 | 配置清单、上传队列、批量识别、逐份审阅、统一导出，适合成组合同和资料包 |
| 任务中心 | 查看任务状态、进度、继续审阅、查看详情和删除；运行中任务需先取消后删除 |
| 处理结果 | 查看已处理文件、批量树状结果、单文件结果、分页选择和打包下载 |
| 文本语义识别 | HaS Text 按清单中的 NER 标签识别实体，不依赖内置穷举映射 |
| OCR + HaS | 图像和扫描件由 MinerU（或 PaddleOCR-VL）抽取文字块，再用 HaS Text 做语义识别并回写坐标 |
| HaS Image YOLO | 检测人脸、指纹、证件、银行卡、印章、二维码、屏幕等视觉区域 |
| VLM checklist | 作为图像管道补充能力，默认聚焦签字等需要视觉语义判断的区域 |
| 配置清单 | 内置通用、法律、金融、医疗清单，也支持自定义文本、图像和兜底项 |
| 本地部署 | 前端、后端、模型服务都可以在本机或内网 GPU 环境中运行 |

---

## 快速开始

### 环境要求

| 依赖 | 推荐版本 |
|---|---|
| Node.js | 24 LTS |
| Python | 3.11 |
| GPU | NVIDIA GPU，建议 16 GB 显存用于完整图像管道 |
| CUDA | 与本地 PyTorch / llama.cpp / MinerU 构建匹配 |
| Conda（Linux 推荐） | 例如 `DataInfraNew`，OCR 与后端共用；HaS Text / VLM 可用独立进程 |

模型权重、真实样本、上传文件、运行数据库和导出结果不随仓库提交。请按自己的本地路径配置。

### Linux 本地启动（Conda，推荐 MinerU 分支）

本分支默认使用 **MinerU** 作为 OCR 微服务（不再依赖 PaddleOCR-VL）。典型端口如下（若本机 8082 被 MinIO 等占用，OCR 使用 **9082**；若 8000 已被其他 vLLM 占用，后端 API 使用 **8090**）：

| 服务 | 端口 | 说明 |
|---|---:|---|
| 后端 API | 8090 | FastAPI |
| 前端 | 3000 | Vite dev |
| HaS Text NER | **8088** | `HaS_Text_0209`（llama-server），**不要**误连 8000 上的通用大模型 |
| HaS Image | 8081 | YOLO11 |
| MinerU OCR | **9082** | 独立进程 `scripts/ocr_server.py` |
| GLM VLM | 8091 | llama-server + 本地 GGUF |
| 其他 vLLM（可选） | 8000 | 与本项目 HaS NER **分离** |

**1. 准备环境与配置**

```bash
conda activate DataInfraNew
cd backend
pip install -r requirements.txt
pip install -r requirements-ocr.lock    # MinerU OCR 微服务
pip install -r requirements-vision.lock # HaS Image 微服务

cp ../.env.example .env  # 再按下方示例修改端口与 URL
```

`backend/.env` 示例（勿把仅用于子进程的环境变量写入会导致 pydantic 报错的字段）：

```env
OCR_BASE_URL=http://127.0.0.1:9082
HAS_LLAMACPP_BASE_URL=http://127.0.0.1:8088/v1
HAS_TEXT_MODEL_NAME=HaS_Text_0209
HAS_IMAGE_BASE_URL=http://127.0.0.1:8081
VLM_BASE_URL=http://127.0.0.1:8091/v1
OCR_STRUCTURE_ENABLED=false
AUTH_ENABLED=false
```

**2. 模型资源（首次）**

```bash
cd backend
# HaS Image 权重（hf-mirror）
HF_MIRROR_BASE=https://hf-mirror.com ./scripts/download_has_image_weights.sh
# MinerU pipeline（ModelScope，可选离线）
python scripts/download_mineru_models_modelscope.py
# GLM VLM GGUF（llama-server 无 HTTPS，需先 wget 到本地）
./scripts/download_vlm_gguf.sh
```

国内下载默认走 [hf-mirror.com](https://hf-mirror.com)；各启动脚本会加载 `scripts/hf_mirror_env.sh`。

**3. 一键后台启动本地栈**

```bash
cd frontend && npm ci   # 首次
cd ../backend
chmod +x scripts/*.sh
./scripts/restart_all_local.sh
```

脚本会在后台（`nohup`）依次启动：HaS Text @8088、MinerU @9082、HaS Image @8081、GLM VLM @8091、后端 @8090、前端 @3000。日志与 PID 在 `backend/logs/`。

- 可选 vLLM @8000（与 HaS NER 无关，占大量显存）：`START_OPTIONAL_VLLM=1 ./scripts/restart_all_local.sh`
- 仅后台起前端：`./scripts/start_frontend_background.sh`

打开 http://localhost:3000 ，在健康面板确认 OCR、HaS Text、HaS Image、VLM 为在线后再识别。

**分进程启动（调试用）**

```bash
./scripts/run_has_text_llama_server.sh   # 8088，必开
./scripts/run_ocr_server_conda.sh        # 9082 MinerU
./scripts/run_vlm_llama_server.sh        # 8091，需本地 GGUF
./scripts/start_backend_and_vision_background.sh
```

停止（含前端与 8088 HaS Text）：`./scripts/stop_all_local.sh`

**识别无结果时请先检查：** `/health/services` 中 OCR 为 online；**HaS Text 必须指向 8088 的 HaS_Text**，若 `HAS_LLAMACPP_BASE_URL` 指向 8000 上的 Qwen，OCR 有字但 NER 实体数为 0，页面上也会空白。

### 本地一键启动（Windows + WSL，原版 Paddle 链路）

仍可使用仓库根目录的 Windows 混合启动（WSL 内 PaddleOCR-VL + vLLM）：

```bash
npm run dev
```

该入口会启动 WSL 中的 vLLM 与 PaddleOCR 包装、Windows 上的 llama.cpp VLM、HaS Image、后端与前端。MinerU 分支在 Linux 上更推荐上一节的 Conda 方式。

关闭服务：`npm run stop`

### 手动启动后端（通用）

```bash
cd backend
python -m venv .venv   # 或 conda activate <env>
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8090
```

```bash
curl http://127.0.0.1:8090/health
curl http://127.0.0.1:8090/health/services
```

### Docker

仓库保留 Dockerfile 和 compose 配置（`Dockerfile.ocr` 已适配 MinerU 依赖）。生产环境部署前请确认 `.env`、模型挂载、GPU runtime、认证和反向代理配置；`OCR_BASE_URL` 需指向 compose 内的 `ocr` 服务（默认 8082，与 Linux 本机 9082 开发端口可不同）。

---

## 系统架构

```text
                   +------------------------+
                   |  TXT / DOCX / PDF / IMG |
                   +-----------+------------+
                               |
                   +-----------v------------+
                   |  FastAPI 编排与任务队列 |
                   +-----------+------------+
                               |
        +----------------------+----------------------+
        |                      |                      |
+-------v--------+     +-------v--------+     +-------v--------+
| 文本语义管道   |     | OCR + HaS 管道 |     | 视觉区域管道   |
| HaS Text NER   |     | MinerU OCR boxes |     | YOLO / VLM     |
+-------+--------+     +-------+--------+     +-------+--------+
        |                      |                      |
        +----------------------+----------------------+
                               |
                   +-----------v------------+
                   |  坐标归一、去重、合并  |
                   +-----------+------------+
                               |
                   +-----------v------------+
                   |  人工复核、脱敏、导出  |
                   +------------------------+
```

---

## 模型服务

### MinerU 分支（Linux Conda，当前默认）

| 服务 | 端口 | 说明 |
|---|---:|---|
| 后端 API | 8090 | 上传、任务、配置、识别、导出 |
| 前端 | 3000 | 浏览器工作台 |
| HaS Text | **8088** | llama-server + `HaS_Text_0209_0.6B_Q4_K_M.gguf`，文本 NER |
| HaS Image | 8081 | YOLO11 视觉区域检测 |
| MinerU OCR | **9082** | `scripts/ocr_server.py`，文档 OCR 与文字框 |
| GLM VLM | **8091** | llama-server + GLM-4.6V-Flash GGUF，签字等 checklist |

### 原版 Paddle 链路（Windows `npm run dev`）

| 服务 | 端口 | 说明 |
|---|---:|---|
| 后端 API | 8000 | FastAPI |
| HaS Text | 8080 | vLLM / llama.cpp |
| HaS Image | 8081 | YOLO11 |
| PaddleOCR-VL | 8082 | OCR 微服务 |
| VLM | 8090 | 视觉语义 |

### 环境变量（MinerU / Linux 示例）

```env
OCR_BASE_URL=http://127.0.0.1:9082
OCR_PORT=9082
HAS_LLAMACPP_BASE_URL=http://127.0.0.1:8088/v1
HAS_TEXT_MODEL_NAME=HaS_Text_0209
HAS_IMAGE_BASE_URL=http://127.0.0.1:8081
VLM_BASE_URL=http://127.0.0.1:8091/v1
VLM_MODEL_NAME=GLM-4.6V-Flash-Q4_K_M
OCR_STRUCTURE_ENABLED=false
```

可选：与本机其他 vLLM 共存时，用 `VLLM_GPU_MEMORY_UTILIZATION=0.70` 启动 HaS Text 以外的模型服务（见 `scripts/run_has_text_vllm.sh`），为 MinerU 与 GLM VLM 留出显存。

显存紧张时，优先降低 vLLM 显存占用、调小 VLM 上下文，或关闭签字（VLM）仅保留 OCR+HaS 与 HaS Image；不要让关键模型静默回退到 CPU，否则页面会长时间无结果或服务显示降级。

---

## 模型与致谢

RedactionEverything 是编排层和产品层，不声明拥有第三方模型权重。本仓库不重新分发这些权重；部署前请从官方仓库下载模型，阅读对应 model card，并遵守各模型、权重和运行时项目的许可证与使用条款。

| 组件 | 上游模型或项目 | 用途 |
|---|---|---|
| MinerU | [opendatalab/MinerU](https://github.com/opendatalab/MinerU)（pipeline 权重经 ModelScope / HF） | 文档 OCR、版面与文字框（本分支默认，`backend/scripts/ocr_server.py`） |
| PaddleOCR-VL（可选） | [PaddlePaddle/PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | 原版 Windows/WSL 链路仍可使用 |
| HaS Text | [xuanwulab/HaS_4.0_0.6B](https://huggingface.co/xuanwulab/HaS_4.0_0.6B)，推荐 GGUF [HaS_Text_0209_0.6B_Q4_K_M](https://huggingface.co/xuanwulab/HaS_4.0_0.6B_GGUF) | 文本和 OCR 文本块的语义 NER |
| HaS Image | [xuanwulab/HaS_Image_0209_FP32](https://huggingface.co/xuanwulab/HaS_Image_0209_FP32) | 基于 YOLO11 的视觉隐私区域分割 |
| GLM VLM | [zai-org/GLM-4.6V-Flash](https://huggingface.co/zai-org/GLM-4.6V-Flash)，本地 llama.cpp 部署可使用兼容 GGUF 量化版本，例如 [unsloth/GLM-4.6V-Flash-GGUF](https://huggingface.co/unsloth/GLM-4.6V-Flash-GGUF) | 通过 rubric/checklist 做视觉语义识别，当前默认聚焦签字 |
| YOLO 运行时 | [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) | HaS Image 实例分割运行框架 |
| llama.cpp 运行时 | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | GGUF 权重的本地 OpenAI 兼容 VLM 服务 |
| vLLM 运行时 | [vLLM](https://github.com/vllm-project/vllm) | 可选；与 HaS Text（8088）分离，勿把通用大模型当作 NER 后端 |

感谢 OpenDataLab（MinerU）、PaddlePaddle、腾讯玄武实验室、Z.ai、Unsloth、Ultralytics、llama.cpp、vLLM 以及开源模型社区。正是这些模型和运行时项目，让本地优先的文档匿名化能够在消费级 GPU 上落地。

---

## 局限性与显存提示

RedactionEverything 默认坚持本地或内网闭环推理，原因是匿名化系统处理的正是原始敏感文件；把文件交给联网 API 虽然可以使用更大的视觉语言模型，但也会削弱匿名化基础设施本身的隐私边界。因此项目的默认方向是单卡笔记本可部署，并尽量通过量化、上下文控制、并发控制和管道编排把完整链路压到本地 GPU 内运行。

图像管道中的 VLM 不是为了替代 HaS Image YOLO11，而是作为补充能力存在。当前 YOLO11 视觉检测覆盖人脸、指纹、证件、银行卡、印章、二维码、屏幕等常见可视区域，但没有单独训练签字目标检测模型；签字、手写签署痕迹这类目标更依赖视觉语义判断，所以默认使用 GLM-4.6V-Flash Q4 量化模型，通过 rubric/checklist 方式识别签名区域。

这也带来明确的资源取舍：完整本地链路可同时包含 MinerU OCR、HaS Text、HaS Image YOLO 和 GLM VLM 四路模型（另加可选的大型 vLLM）。即使做了预热、GPU 探测和 VLM 串行调度，16GB 显存以下仍可能因 KV cache 或并发而变慢。建议完整图像管道使用 16GB 及以上 NVIDIA GPU；与同卡大模型共存时，将 vLLM 的 `--gpu-memory-utilization` 调到约 **0.70**，并为 HaS Text 使用独立 8088 端口。若不需要签字识别，可在清单中关闭 VLM，只保留 OCR+HaS 与 HaS Image。

更大尺寸的本地 VLM 通常会带来更好的视觉语义理解，但部署门槛也更高。项目默认配置优先保证个人工作站、单卡笔记本和内网机器能够运行，而不是追求最大模型规模。

---

## 配置清单

系统内置四类清单：

| 清单 | 用途 |
|---|---|
| 通用 | 个人、组织、证件、账号、联系方式、地址、金额、日期时间等基础敏感实体 |
| 法律 | 当事人、代理人、法院、案号、合同编号、案件事实和法律文书相关字段 |
| 金融 | 账户、卡号、交易、金额、机构、客户和金融业务资料 |
| 医疗 | 患者、医疗机构、检查、诊断、用药、病历和就诊信息 |

文本管道和图像管道的清单互相独立。新建清单时，每个模块都支持全选和清空，方便按场景快速裁剪。

---

## 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | React 19、TypeScript、Vite、Tailwind CSS、Radix UI、Zustand |
| 后端 | FastAPI、Pydantic、SQLite、本地文件存储 |
| 文本识别 | HaS Text，vLLM 或 llama.cpp OpenAI 兼容服务 |
| OCR | MinerU pipeline（默认）；可选 PaddleOCR-VL / PP-Structure |
| 视觉检测 | HaS Image YOLO11、VLM checklist |
| 导出 | 文本、图片、PDF、Word 处理与批量打包 |

---

## 代码结构

```text
backend/
  app/          FastAPI 应用、任务队列、识别编排、脱敏和导出
  config/       内置识别清单和行业预设
  scripts/
    ocr_server.py                 MinerU OCR 微服务
    run_ocr_server_conda.sh       启动 OCR（conda DataInfraNew）
    run_has_text_llama_server.sh  HaS Text NER @8088
    run_vlm_llama_server.sh       GLM VLM @8091
    run_has_text_vllm.sh          可选 vLLM（勿替代 HaS NER）
    restart_all_local.sh / stop_all_local.sh
    download_* / hf_mirror_env.sh 模型下载与国内镜像

frontend/
  src/          React 工作台、任务中心、处理结果、单次处理、批量处理和配置清单
  public/       前端静态资源
```

---

## 安全与部署

- 仓库只包含应用代码和默认配置，不包含本地 `.env`、模型权重、样本数据、上传文件、运行数据库、日志或导出结果。
- 项目默认面向本地或内网部署；如需公网访问，请配置认证、访问控制、反向代理、TLS、日志留存和密钥轮换策略。
- 默认识别由模型能力和配置清单驱动；正则仅作为用户自定义兜底能力保留。
- 建议将模型、样本、任务数据和导出目录放在私有运行环境中管理，并用访问权限和备份策略单独保护。

---

## 贡献

欢迎提交 issue 和 PR。建议 PR 聚焦一个问题或一个功能，避免混入本地样本、实验脚本、模型权重和临时输出。

提交前至少确认：

```bash
cd backend
python -m ruff check app/

cd ../frontend
npm run build
```

---

## 许可证

本项目采用自定义 [Personal Use License](./LICENSE)：

- 个人用途可免费使用，包括个人项目、学习、研究、私人实验和演示。
- 付费工作、咨询交付、公司、机构、政府、团队或其他组织的生产使用、产品集成、SaaS、托管服务、OEM、再分发和采购场景需要单独商业授权。
- 模型权重、第三方依赖和数据集遵循其各自许可证。

商业授权联系：**wwang11@alumni.nd.edu**。

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)
