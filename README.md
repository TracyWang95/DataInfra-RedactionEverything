<div align="center">

# DataInfra &middot; RedactionEverything

**非结构化数据匿名化基础设施 &mdash; 开源**

不止个人信息 — **Redaction _Everything_**。<br/>
自定义识别规则，匿名化任何你定义的敏感内容：PII、商业秘密、合同条款、医疗数据、军工编号……<br/>
Word、PDF、扫描件、图片全覆盖，双 AI 流水线驱动，100% 本地部署。

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![CI](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml/badge.svg)](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything?style=social)](https://github.com/TracyWang95/DataInfra-RedactionEverything)

中文 &nbsp;|&nbsp; **[English](./README_en.md)**

> **开源协议：[Apache License 2.0](./LICENSE)** &mdash; 免费用于学术、研究和非商业场景。<br/>
> **商业使用（SaaS / OEM / 企业部署 50 人以上）需要获得商业授权。** 详见 **[商业授权说明](./COMMERCIAL_LICENSE.md)**。

<p>
  <a href="#项目简介">项目简介</a> &middot;
  <a href="#核心能力">核心能力</a> &middot;
  <a href="#快速开始">快速开始</a> &middot;
  <a href="#系统架构">系统架构</a> &middot;
  <a href="#技术栈">技术栈</a> &middot;
  <a href="#部署指南">部署指南</a> &middot;
  <a href="#贡献">贡献</a> &middot;
  <a href="#许可证">许可证</a>
</p>

<!-- screenshot: hero -->

</div>

---

## 项目简介

名字叫 **Redaction _Everything_**，因为我们要匿名化的不止是个人信息。

每个行业都有自己的敏感数据 — 法律合同中的当事人和案号、医疗病历中的诊断和用药、金融文档中的账户和交易流水、军工档案中的型号和编号。传统工具只认 PII，遇到行业特有的敏感字段就无能为力。

**RedactionEverything** 的核心理念是**完全可自定义**：你定义什么是敏感的，系统就识别和匿名化什么。内置 60+ 实体类型开箱即用，同时支持自定义正则规则、AI 语义规则和标签模板，适配任何行业、任何合规要求。

技术上，系统采用**双流水线架构** — OCR + NER 处理文本实体，YOLO11 实例分割检测 21 类视觉目标（人脸、印章、证件、二维码等） — 结果融合后交互式审阅，全部推理在本地完成：**数据不会离开你的网络**。

**参考标准：** GDPR &middot; 《个人信息保护法》 &middot; GB/T 37964-2019 &middot; 《面向数据流通的匿名化处理实施指南》 &middot; 《面向数据流通的匿名化效果评估方法》

---

## 核心能力

| &nbsp; | 能力 | 说明 |
|:---:|---|---|
| :wrench: | **深度可自定义** | 自定义实体类型、正则规则、AI 语义规则、标签模板 — 不止 PII，**任何敏感内容都能定义和识别** |
| :brain: | **AI 语义识别** | 基于大模型（Qwen3-0.6B via llama.cpp）的语义级 NER，理解上下文，不是简单正则匹配 |
| :eyes: | **视觉特征检测** | YOLO11 实例分割 — 人脸、指纹、印章、签名、身份证、银行卡、二维码、车牌等 **21 类**视觉目标 |
| :page_facing_up: | **多格式全覆盖** | Word (.docx)、PDF、扫描件 PDF、JPG、PNG |
| :zap: | **批量处理** | 五步向导：配置 → 上传 → 队列识别 → 审阅确认 → 打包导出 |
| :shield: | **100% 本地部署** | 全部推理本地运行，零云端依赖，数据不出内网 |
| :dart: | **多行业合规** | 法律、医疗、金融、政务 — GDPR、个保法、GB/T 37964-2019 |
| :globe_with_meridians: | **中英文双语** | 一键切换中英文界面 |
| :gear: | **REST API** | 85+ 端点，SSE 实时进度，Swagger / ReDoc 文档 |

---

## 截图

<!-- screenshot: 工作台单文件流程 -->

<!-- screenshot: 批量审阅三栏布局 -->

<!-- screenshot: 双流水线检测结果叠加 -->

---

## 快速开始

### Docker Compose（推荐）

> **前置要求：** [Docker Engine](https://docs.docker.com/engine/install/) 24+ 及 Docker Compose V2。<br/>
> GPU 服务另需 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)。

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# （可选）按需修改环境变量
cp .env.example .env

# 仅 CPU（不启动 GPU 服务）
docker compose up -d

# 启用 GPU 服务（OCR、NER、Vision）
docker compose --profile gpu up -d
```

打开 **http://localhost:3000** 即可使用。

> **提示：** 首次构建需要拉取基础镜像和安装依赖，请耐心等待。GPU 服务模型文件需提前放置在 `backend/models/` 目录下。

### 手动部署

<details>
<summary><strong>环境要求</strong></summary>

| 依赖 | 版本 |
|---|---|
| Python | 3.10+ |
| Node.js | 18+ |
| GPU | NVIDIA 8 GB+ 显存（推荐 RTX 4060 及以上） |
| llama.cpp | 最新版本（NER 服务） |

</details>

#### 1. 克隆仓库 & 准备模型

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# 下载模型权重
# - HaS Text NER:  huggingface.co/xuanwulab/HaS_Text_0209_0.6B_Q4
# - HaS Image:     sensitive_seg_best.pt (YOLO11)
# - PaddleOCR-VL:  首次运行自动下载（约 2 GB）
```

#### 2. 启动 AI 服务

```bash
# HaS NER（端口 8080）
llama-server -hf xuanwulab/HaS_Text_0209_0.6B_Q4 \
  --port 8080 -ngl 99 --host 0.0.0.0 -c 8192 -np 1

# HaS Image — YOLO11（端口 8081）
cd backend && python has_image_server.py

# PaddleOCR-VL（端口 8082）
cd backend && python ocr_server.py
```

#### 3. 启动后端

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 4. 启动前端

```bash
cd frontend
npm install && npm run dev
```

验证服务状态：

```bash
curl http://127.0.0.1:8000/health/services
```

---

## 系统架构

```
                          +------------------+
                          |    用户上传      |
                          | DOCX / PDF / IMG |
                          +--------+---------+
                                   |
                          +--------v---------+
                          |   文件解析 &     |
                          |   页面图像化     |
                          +--------+---------+
                                   |
                    +--------------+--------------+
                    |                              |
          +---------v----------+       +----------v---------+
          | 流水线 1：文本     |       | 流水线 2：视觉     |
          +---------+----------+       +----------+---------+
                    |                              |
          +---------v----------+       +----------v---------+
          |  PaddleOCR-VL-1.5  |       |   YOLO11（21类    |
          |  文字检测           |       |   实例分割）       |
          +---------+----------+       +----------+---------+
                    |                              |
          +---------v----------+                   |
          |   HaS NER (Q4)    |                   |
          |   实体识别         |                   |
          +---------+----------+                   |
                    |                              |
                    +--------------+--------------+
                                   |
                          +--------v---------+
                          |   IoU 去重 &     |
                          |   结果融合       |
                          +--------+---------+
                                   |
                          +--------v---------+
                          |   交互式编辑 &   |
                          |   匿名化处理     |
                          +------------------+
```

**五个服务协同工作：**

| 服务 | 端口 | 职责 |
|---|---|---|
| **前端** | 3000 | React UI — 上传、标注、审阅、导出 |
| **后端 API** | 8000 | FastAPI — 编排、任务队列、文件 I/O |
| **HaS NER** | 8080 | llama.cpp — 命名实体识别 |
| **HaS Image** | 8081 | YOLO11 — 21 类视觉 PII 分割 |
| **PaddleOCR** | 8082 | PaddleOCR-VL-1.5 — 文字检测与版面分析 |

---

## 技术栈

| 层级 | 技术 | 版本 |
|---|---|---|
| **前端** | React | 19 |
| | TypeScript | 5.7 |
| | Vite | 6.1 |
| | Tailwind CSS | 3.4 |
| | Radix UI (ShadCN) | latest |
| | Zustand | 5.0 |
| | Playwright | 1.58 |
| **后端** | FastAPI | 0.115+ |
| | Python | 3.10+ |
| | SQLite | （任务队列） |
| **AI / ML** | PaddleOCR-VL-1.5 | 2.7+ |
| | HaS Text（Qwen3-0.6B Q4） | via llama.cpp |
| | YOLO11（Ultralytics） | 8.3+ |

---

## 部署指南

### Docker Compose 部署详情

项目提供了完整的 `docker-compose.yml`，包含 5 个服务：

| 服务 | 镜像/构建 | 默认端口 | Profile |
|---|---|---|---|
| **backend** | `./backend/Dockerfile` | 8000 | _(始终启动)_ |
| **frontend** | `./frontend/Dockerfile` | 3000 → 80 | _(始终启动)_ |
| **ocr** | `./backend/Dockerfile.ocr` | 8082 | `gpu` |
| **ner** | `ghcr.io/ggerganov/llama.cpp:server` | 8080 | `gpu` |
| **vision** | `./backend/Dockerfile.vision` | 8081 | `gpu` |

**数据持久化（Docker Volumes）：**

| Volume | 容器路径 | 用途 |
|---|---|---|
| `backend-data` | `/app/data` | SQLite 数据库、配置、JWT 密钥 |
| `backend-uploads` | `/app/uploads` | 用户上传的文件 |
| `backend-outputs` | `/app/outputs` | 匿名化处理结果 |

**网络：** 所有服务在 `redaction-net` 桥接网络中通信，容器间通过服务名互访（如 `http://ocr:8082`）。

**日志：** 自动轮转，单文件最大 20 MB，保留最近 5 份（backend）/ 3 份（GPU 服务）。

### 环境变量

所有可配置项均已记录在 **`.env.example`** 中，复制为 `.env` 后按需修改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEBUG` | `false` | 启用调试日志 |
| `AUTH_ENABLED` | `false` | 启用 JWT 认证（首次访问 /setup 设置密码） |
| `JWT_SECRET_KEY` | _(自动生成)_ | JWT 签名密钥，留空则自动持久化 |
| `BACKEND_PORT` | `8000` | 后端对外暴露端口 |
| `FRONTEND_PORT` | `3000` | 前端对外暴露端口 |
| `OCR_BASE_URL` | `http://ocr:8082` | PaddleOCR 服务地址 |
| `HAS_LLAMACPP_BASE_URL` | `http://ner:8080/v1` | HaS NER 服务地址 |
| `HAS_IMAGE_BASE_URL` | `http://vision:8081` | HaS Image 服务地址 |
| `MAX_FILE_SIZE` | `52428800` (50 MB) | 最大上传文件大小（字节） |
| `OCR_TIMEOUT` | `360` | PaddleOCR VL 推理超时（秒） |
| `HAS_TIMEOUT` | `120` | HaS Text NER 超时（秒） |
| `FILE_ENCRYPTION_ENABLED` | `false` | AES-256-GCM 加密落盘 |
| `DEFAULT_REPLACEMENT_MODE` | `smart` | 匿名化模式：smart / mask / custom |

### GPU 加速（手动部署）

```bash
pip install paddlepaddle-gpu          # CUDA 12.6
pip install -r backend/requirements.txt

# 验证
python -c "import paddle; print(paddle.is_compiled_with_cuda(), paddle.get_device())"
# 预期输出: True gpu:0
```

---

## 视觉 PII 类别（HaS Image）

YOLO11 检测 **21 类**视觉敏感信息：

| ID | 标识符 | 类别 |
|:---:|---|---|
| 0 | `face` | 人脸 |
| 1 | `fingerprint` | 指纹 |
| 2 | `palmprint` | 掌纹 |
| 3 | `id_card` | 身份证 |
| 4 | `hk_macau_permit` | 港澳通行证 |
| 5 | `passport` | 护照 |
| 6 | `employee_badge` | 工牌 |
| 7 | `license_plate` | 车牌 |
| 8 | `bank_card` | 银行卡 |
| 9 | `physical_key` | 实体钥匙 |
| 10 | `receipt` | 收据 |
| 11 | `shipping_label` | 快递面单 |
| 12 | `official_seal` | 公章 |
| 13 | `whiteboard` | 白板 |
| 14 | `sticky_note` | 便签 |
| 15 | `mobile_screen` | 手机屏幕 |
| 16 | `monitor_screen` | 显示器屏幕 |
| 17 | `medical_wristband` | 医疗腕带 |
| 18 | `qr_code` | 二维码 |
| 19 | `barcode` | 条形码 |
| 20 | `paper` | 纸质文档 |

---

## 合规标准

| 标准 | 适用范围 |
|---|---|
| **GDPR**（欧盟） | 通用数据保护条例 |
| **《个人信息保护法》**（中国） | 个人信息保护法 |
| **GB/T 37964-2019** | 信息安全技术 — 个人信息去标识化指南 |
| **《面向数据流通的匿名化处理实施指南》** | 匿名化处理实施 |
| **《面向数据流通的匿名化效果评估方法》** | 匿名化效果评估 |

实体分类体系基于 GB/T 37964-2019，将 PII 划分为**直接标识符**（姓名、证件号、手机号）、**准标识符**（单位、地址、日期）和**视觉元素**（印章、人脸、证件照）。

---

## 贡献

欢迎贡献！请先阅读 **[CONTRIBUTING.md](./CONTRIBUTING.md)**。

```bash
# 端到端测试
cd frontend && npm run test:e2e

# 单元测试
cd frontend && npm run test
```

PR 检查清单：
- [ ] 所有推理在本地运行 — 不调用云端 API
- [ ] 冒烟测试通过
- [ ] 文档已更新（如适用）

---

## 许可证

本项目基于 **[Apache License 2.0](./LICENSE)** 开源。

商业部署、OEM 或托管服务需要单独的商业许可证。详见 **[COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md)**。

---

## 常见问题排查

| 问题 | 解决方案 |
|------|----------|
| CUDA / GPU 未识别 | 确认已安装 NVIDIA 驱动，运行 `nvidia-smi` 验证；使用 `docker compose --profile gpu up -d` 启动 GPU 服务 |
| 端口冲突 (3000/8000) | 修改 `.env` 中的端口映射，或停止占用端口的进程 |
| 模型文件下载慢 | NER/Vision 模型在首次启动时自动下载，可手动下载后放入 `models/` 目录并通过 volume 挂载 |
| 内存不足 (OOM) | 文本模式需 4GB+，GPU 视觉模式需 8GB+；可通过 `docker compose` 设置资源限制 |
| 上传文件失败 | 检查文件大小是否超过 50MB 限制（`MAX_FILE_SIZE`），确认 `uploads/` 目录权限正确 |
| OCR 识别为空 | 确认 OCR 服务健康（`curl http://localhost:8082/health`），检查图片是否清晰 |
| 认证问题 | 首次启用 `AUTH_ENABLED=true` 后访问 `/setup` 设置密码；忘记密码可删除 `data/` 下的密码文件重新设置 |

---

## 安全

请参阅 **[SECURITY.md](./SECURITY.md)** 了解安全策略和漏洞披露流程。核心原则：本平台专为**本地部署**设计 — 不向外部传输任何数据。

---

<div align="center">

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)

如果这个项目对你有帮助，请给一个 Star ⭐

</div>
