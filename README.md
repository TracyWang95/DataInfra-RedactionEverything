<div align="center">

# DataInfra &middot; RedactionEverything

**非结构化数据匿名化基础设施 &mdash; 开源**

自动检测并匿名化 Word、PDF、图片中的个人敏感信息，全流程本地部署，双 AI 流水线驱动。

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
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

每个组织每天都在处理大量敏感文档 — 合同、医疗单据、身份证件、扫描档案。这些文档在共享、发布或用于模型训练之前，必须移除其中的个人可标识信息（PII）。

**RedactionEverything** 是一套自托管的匿名化平台，自动完成非结构化文档中 PII 的识别与处理。系统采用**双流水线架构** — OCR + NER 处理文本实体，YOLO11 实例分割检测视觉元素 — 再进行结果融合，实现全面覆盖。全部推理在本地完成：**数据不会离开你的网络**。

**参考标准：** GDPR &middot; 《个人信息保护法》 &middot; GB/T 37964-2019 &middot; 《面向数据流通的匿名化处理实施指南》 &middot; 《面向数据流通的匿名化效果评估方法》

---

## 核心能力

| &nbsp; | 能力 | 说明 |
|:---:|---|---|
| :mag: | **混合 NER** | 正则规则 + AI 语义识别（llama.cpp / Qwen3-0.6B） |
| :framed_picture: | **视觉 PII 检测** | YOLO11 实例分割，覆盖印章、签名、人脸、证件等 **21 类**目标 |
| :page_facing_up: | **多格式支持** | Word (.docx)、PDF、扫描件 PDF、JPG、PNG |
| :zap: | **批量处理** | 五步向导：配置 → 上传 → 队列识别 → 审阅确认 → 打包导出 |
| :shield: | **100% 本地部署** | 全部推理在本地运行，零云端依赖 |
| :dart: | **标准合规** | GDPR、个保法、GB/T 37964-2019 |
| :globe_with_meridians: | **中英文双语** | 一键切换中英文界面 |
| :gear: | **REST API** | 85+ 端点，SSE 实时进度，Swagger / ReDoc 文档 |
| :test_tube: | **端到端测试** | 76 条 Playwright 测试覆盖完整流水线 |

---

## 截图

<!-- screenshot: 工作台单文件流程 -->

<!-- screenshot: 批量审阅三栏布局 -->

<!-- screenshot: 双流水线检测结果叠加 -->

---

## 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/TracyWang95/DataInfra-RedactionEverything.git
cd DataInfra-RedactionEverything

# 仅 CPU（不启动 GPU 服务）
docker compose up -d

# 启用 GPU 服务（OCR、NER、Vision）
docker compose --profile gpu up -d
```

打开 **http://localhost:3000** 即可使用。

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

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEBUG` | `false` | 启用调试日志 |
| `AUTH_ENABLED` | `false` | 启用 JWT 认证 |
| `OCR_BASE_URL` | `http://localhost:8082` | PaddleOCR 服务地址 |
| `HAS_LLAMACPP_BASE_URL` | `http://localhost:8080/v1` | HaS NER 服务地址 |
| `HAS_IMAGE_BASE_URL` | `http://localhost:8081` | HaS Image 服务地址 |
| `HAS_IMAGE_WEIGHTS` | 自动检测 | YOLO11 权重文件路径 |
| `JOB_DB_PATH` | `data/jobs.sqlite3` | SQLite 任务数据库路径 |

### GPU 加速

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

## 安全

请参阅 **[SECURITY.md](./SECURITY.md)** 了解安全策略和漏洞披露流程。核心原则：本平台专为**本地部署**设计 — 不向外部传输任何数据。

---

<div align="center">

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)

如果这个项目对你有帮助，请给一个 Star ⭐

</div>
