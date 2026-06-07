<div align="center">

# DataInfra &middot; RedactionEverything

**本地优先的非结构化数据脱敏：文档、扫描 PDF、图片、Word、纯文本**

RedactionEverything 是一个面向真实文件中敏感信息的本地优先脱敏工作台。它将语义 NER、OCR、视觉特征定位、可配置行业 Schema、人工复核、批量处理与导出工作流结合在一起，让敏感内容可以被发现、复核与匿名化，而无需把原始文件发送到远程 API。

[![License](https://img.shields.io/badge/license-Personal%20Use-blue.svg)](./LICENSE)
[![CI](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml/badge.svg)](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything.svg?style=flat&logo=github&label=Stars&cacheSeconds=3600)](https://github.com/TracyWang95/DataInfra-RedactionEverything/stargazers)

**语言：** [English](./README.md) | 中文

> 本项目采用自定义的 [个人使用许可证](./LICENSE)。个人可免费用于个人、非商业目的。付费交付、咨询交付、公司、机构、政府部门、团队、托管服务、生产部署、OEM 再分发以及商业集成需要单独的商业许可证。
>
> 商业授权、支持、采购条款与定制交付：**wwang11@alumni.nd.edu**

<p>
  <a href="#概览">概览</a> &middot;
  <a href="#定位">定位</a> &middot;
  <a href="#功能">功能</a> &middot;
  <a href="#最新验证更新">最新更新</a> &middot;
  <a href="#快速开始">快速开始</a> &middot;
  <a href="#架构">架构</a> &middot;
  <a href="#模型服务">模型服务</a> &middot;
  <a href="#模型致谢">模型致谢</a> &middot;
  <a href="#局限与显存">局限</a> &middot;
  <a href="#多租户部署">多租户</a> &middot;
  <a href="#用户隔离">用户隔离</a> &middot;
  <a href="#安全与部署">安全</a> &middot;
  <a href="#许可证">许可证</a>
</p>

</div>

---

## 概览

**RedactionEverything** 是一套面向本地部署的文档匿名化系统。它把非结构化文件拆分为文本链路与视觉链路，识别姓名、机构、证件号、账户、地址、金额、日期、印章、人脸、签字等敏感要素，并提供复核界面、批量任务管理以及可导出的脱敏结果。

目标不是一个狭义的固定规则 PII 扫描器，而是围绕可配置 Schema 构建：

- 通用 Schema 覆盖人物、机构、联系方式、证件、账户、金额、日期、地址与常见标识。
- 行业 Schema 覆盖法律、金融、医疗场景下的领域识别项。
- 文本识别默认由 HaS Text 语义 NER 完成；正则仅作为用户自定义的兜底能力保留。
- 视觉识别将“OCR + HaS”应用于抽取出的文本，并由单一的 LocateAnything-3B 视觉特征服务定位人脸、印章、签字等视觉语义目标，再辅以本地 OpenCV 检测器补全骑缝章与边缘章。
- 原始文件、配置、识别结果与导出产物默认保留在本地或内网运行环境中。

---

## 定位

RedactionEverything 被设计为一个完整的脱敏工作台，而不是纯文本隐私过滤器。诸如 [OpenAI Privacy Filter](https://github.com/openai/privacy-filter) 这类项目，是文本 token 级 PII 检测的高吞吐基线，很有价值。本项目针对的是问题的另一层：杂乱的中文与中英混排业务文档、扫描 PDF、Word 合同、图片、视觉隐私区域、人工复核、批量交付与本地部署。

区别在于范围，而非措辞：

- **语言与 Schema 深度：** 中文合同、法律文件、金融文档、医疗材料与中英混排内容，往往需要领域 Schema，而非一个很小的固定标签集。
- **文档现实：** 生产文件很少是干净文本，包含 PDF 版式、OCR 噪声、表格、印章、签字、截图、照片与扫描页。
- **视觉覆盖：** “OCR + HaS”处理图片中的文字，LocateAnything-3B 定位人脸、证件、银行卡、印章、屏幕与手写签字等视觉特征；本地 OpenCV 检测器补全红色与暗色的骑缝章/边缘章。
- **运营工作流：** 识别只是第一步。系统包含复核、修正、勾选、批量处理、任务状态、结果历史与导出打包。
- **隐私边界：** 默认架构把原始文件与模型推理保留在本地或内网，而不是依赖托管的外部 API。

---

## 功能

| 能力 | 说明 |
|---|---|
| 单文件处理 | 上传 TXT、DOCX、PDF、扫描 PDF、PNG、JPG 等文件，在一个流程内完成识别、复核、脱敏与导出。 |
| 批量处理 | 选择 Schema，上传混合队列，运行识别，逐个文件复核，并导出打包结果。 |
| 任务中心 | 跟踪任务状态、进度、复核续作、详情与删除。运行中的任务需先取消再删除。 |
| 处理结果 | 查看已处理文件、单文件输出、批量树状结果、分页勾选与打包下载。 |
| 文本语义 NER | HaS Text 直接根据配置的 NER 标签识别实体，不依赖内置的穷举规则映射。 |
| OCR + HaS | 图片与扫描件先由 PaddleOCR-VL / PP-StructureV3 转为文本块，再由 HaS Text 做语义识别并映射回坐标。 |
| 视觉特征 | 单一的 LocateAnything-3B 服务定位固定视觉预设（人脸、指纹、证件、银行卡、印章、屏幕、二维码/条码、签字等）以及任意用户自定义视觉标签。 |
| 印章补全 | 本地 OpenCV 检测器补全 LocateAnything 遗漏的红色与暗色/灰色骑缝章与边缘章，并与已有印章框去重。 |
| 可配置 Schema | 内置通用、法律、金融、医疗预设；支持自定义文本与视觉识别项，标签精确（不做家族合并）。 |
| 本地部署 | 前端、后端与模型服务可运行在本地或内网 GPU 工作站。 |

---

## 最新验证更新

当前分支聚焦于视觉链路的收敛、视觉推理提速与识别 Schema 的精简。这些改动是通用工程改进，而非针对具体文档的硬规则：

| 方面 | 更新 |
|---|---|
| 视觉链路收敛 | 原先“HaS-Image-YOLO + GLM-VLM”的分裂视觉链路，被单一的 **LocateAnything-3B** 视觉特征服务取代，统一覆盖固定预设、用户自定义视觉标签与签字。视觉隐私目标现在以一个“视觉特征”能力进行配置与展示。 |
| 骑缝章补全 | 本地 OpenCV 印章检测器补全 LocateAnything 遗漏的**红色与暗色/灰色**边缘章与骑缝章。它是纯补充，按 IoU 与重叠率与已有印章框去重。 |
| 视觉推理提速 | LocateAnything 对单图启用无掩码 SDPA 快路径，并在启动时进行“热到目标”预热，让用户的第一次请求即为已预热状态。首次检测时延从约 30s 降到数秒。 |
| 识别清单精简 | 系统预设被收窄并去重。**默认**清单现为通用九项；法律、金融、医疗预设各自只保留领域专属项。识别项原子化、标签精确。 |
| 新增医疗原子项 | 新增 登记号（registration number）与 住院号（inpatient number）作为一等医疗标识，与病历号区分。 |
| 单 GPU 调度 | GPU 重推理由共享队列守护，使 OCR、HaS NER 与 LocateAnything 不会压垮单张 16 GB 显卡。 |
| OCR 与表格召回 | OCR 文本框采用更强的坐标、模糊与视觉行匹配，恢复被空格拆散或碎裂的机构名；表头、单元格与数值列恢复单价、合计、账户、合同金额等敏感值。 |
| 用户与租户隔离 | 识别项、预设、视觉链路设置、文件、任务、复核草稿、历史、预览、导出与清理操作均按已认证用户隔离。`super_admin` 保留系统配置与用户管理权限。 |
| UI/UX 打磨 | 一轮广泛的原子级 UI 修复（排版、对齐、间距、配色、圆角、状态徽标），以及全局顶栏/侧栏分隔线对齐，使每页框架线一致。 |

本轮使用的验证命令：

```bash
cd backend
ruff check app/
python -c "from app.main import app; print(app.title)"

cd ../frontend
npm run build
```

UI 回归通过 Playwright 对本地服务运行，覆盖单文件与批量上传、识别、复核、脱敏、ZIP 导出、质量报告导出、控制台错误与窄屏溢出。

---

## 快速开始

### 环境要求

| 依赖 | 推荐版本 |
|---|---|
| Node.js | 24 LTS |
| Python | 3.11 |
| GPU | NVIDIA GPU；完整视觉链路推荐 16 GB 显存 |
| CUDA | 与本地 Paddle / vLLM 构建匹配 |

模型权重、真实样本、上传文件、运行时数据库、日志与导出结果不纳入本仓库。请在自己的环境中配置本地路径。

### 一键本地启动（Windows + WSL）

在仓库根目录：

```bash
npm run dev
```

它按固定顺序启动：WSL 内的 vLLM 模型服务与 OCR 包装服务、LocateAnything 视觉特征服务、后端 API，最后是前端。只有当模型服务在线且预热完成后才打印就绪信号：

```text
[dev] ready: http://localhost:3000
```

默认情况下，较重的 PaddleOCR-VL 模型**关闭**，文本链路直接走 PP-StructureV3，从而为 HaS Text 与 LocateAnything 让出显存。设置 `OCR_VL_ENABLED=1` 可同时在 `8118` 端口启动 PaddleOCR-VL。

停止所有本地服务：

```bash
npm run stop
```

若 WSL localhost 端口转发不可用，启动脚本会自动改用 WSL IP 访问 vLLM/OCR 服务，避免前端把它们误报为离线。模型服务应保持在 GPU/CUDA 上；如果 `/health/services` 对任一关键模型报告 CPU 回退风险，请先修复运行时再处理文件。

### 手动启动后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/services
```

### 手动启动前端

```bash
cd frontend
npm ci
npm run dev -- --host 0.0.0.0 --port 3000
```

打开 `http://localhost:3000`。

### Docker

仅 CPU 的 API 与前端：

```bash
docker compose up -d
```

完整 GPU 模型栈（启动 `ocr`、`ner`、`visual-features`）：

```bash
docker compose --profile gpu up -d
```

生产部署前，请配置 `.env`、模型挂载、GPU 运行时、认证、反向代理与访问控制策略。

---

## 架构

```text
                   TXT / DOCX / PDF / IMG
                            |
                   FastAPI 编排
                            |
        +-------------------+--------------------+
        |                                        |
   文本 + OCR 链路                          视觉特征链路
   PaddleOCR-VL 1.6（可选）                LocateAnything-3B
   + PP-StructureV3                       （MoonViT 视觉塔 +
        |                                  Qwen2 LM 主干）
   HaS Text 语义 NER                              |
        |                                + OpenCV 印章补全
        |                                  （红色 / 暗色印章）
        +-------------------+--------------------+
                            |
                    坐标合并 / 去重
                            |
                    复核、脱敏、导出
```

---

## 模型服务

默认本地端口：

| 服务 | 端口 | 说明 |
|---|---:|---|
| 后端 API | 8000 | 上传、任务、预设、识别、脱敏、导出 |
| 前端 | 3000 | 浏览器工作台 |
| HaS Text | 8080 | OpenAI 兼容语义 NER 服务（vLLM） |
| PaddleOCR / PP-StructureV3 | 8082 | OCR、版式、表格与文本框 |
| PaddleOCR-VL 1.6 | 8118 | 可选 VL OCR（vLLM）；默认关闭 |
| LocateAnything 视觉特征 | 8090 | MoonViT 视觉塔；视觉预设与自定义标签 |
| LocateAnything LM 主干 | 8091 | LocateAnything 的可选 Qwen2 LM（vLLM，prompt-embeds） |

常用环境变量（完整模板见 [`.env.example`](./.env.example)）：

```env
# 非 Docker 的本地开发
OCR_BASE_URL=http://127.0.0.1:8082
HAS_TEXT_RUNTIME=vllm
HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:8080/v1
VISUAL_FEATURES_BASE_URL=http://127.0.0.1:8090
LOCATE_ANYTHING_PORT=8090
LOCATE_ANYTHING_MAX_NEW_TOKENS=8192
# 可选 VL OCR
OCR_VL_ENABLED=0
OCR_VLLM_URL=http://127.0.0.1:8118/v1
```

显存紧张时，请优先调整上下文长度、最大生成 token、并发与图像尺寸，再考虑让任一关键模型悄悄回退到 CPU。CPU 回退通常表现为界面长时间等待、结果缺失或服务探活离线。

---

## 视觉特征预设

内置视觉特征集包含 22 个固定类别：

`face`、`fingerprint`、`palmprint`、`id_card`、`hk_macau_permit`、`passport`、`employee_badge`、`license_plate`、`bank_card`、`physical_key`、`receipt`、`shipping_label`、`official_seal`、`whiteboard`、`sticky_note`、`mobile_screen`、`monitor_screen`、`medical_wristband`、`qr_code`、`barcode`、`paper`、`signature`。

用户可在识别设置界面新增自定义视觉特征标签。自定义标签存放在视觉特征链路下，并通过同一个 LocateAnything 服务以提示词方式识别。

---

## 模型致谢

RedactionEverything 是编排与产品层。它不主张拥有第三方模型权重，本仓库也不再分发这些权重。请从各自的官方仓库下载模型、阅读模型卡，并在部署前遵守相应许可证与条款。

| 组件 | 上游模型或项目 | 用途 |
|---|---|---|
| PaddleOCR-VL / PP-StructureV3 | [PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)、[PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | 文档 OCR、版式理解、表格、文本框与页面结构抽取 |
| HaS Text | [xuanwulab/HaS_4.0_0.6B](https://huggingface.co/xuanwulab/HaS_4.0_0.6B) | 文本与 OCR 文本块的语义 NER |
| LocateAnything-3B | LocateAnything 视觉定位模型（请从官方上游获取权重） | 视觉特征定位：预设、自定义标签与签字 |
| vLLM 运行时 | [vLLM](https://github.com/vllm-project/vllm) | 为 HaS Text、PaddleOCR-VL 与 LocateAnything LM 主干提供本地 OpenAI 兼容服务 |
| Transformers 运行时 | [Hugging Face Transformers](https://github.com/huggingface/transformers) | LocateAnything MoonViT 视觉塔的本地运行时 |
| OpenCV | [OpenCV](https://github.com/opencv/opencv) | 本地红色/暗色印章检测，补全骑缝章与边缘章 |

感谢 PaddlePaddle、腾讯玄武实验室、LocateAnything 作者、vLLM、Hugging Face、OpenCV 以及更广泛的开源社区。他们的工作让在消费级 GPU 上实现本地优先的文档脱敏成为可能。

---

## 局限与显存

RedactionEverything 有意把识别保留在本地或内网的推理回路内。系统处理的是原始敏感文件；把这些文件发往在线 API 也许能用上更大的视觉语言模型，但同时削弱了脱敏基础设施本应提供的隐私边界。因此默认的工程方向是单 GPU 工作站部署，通过量化、上下文控制、并发控制与链路调度，把完整工作流压进本地 GPU 运行时。

视觉特征阶段使用单一的 LocateAnything-3B 定位模型，而非一堆专用检测器。它覆盖人脸、指纹、证件、银行卡、印章、二维码/条码、屏幕与手写签字等常见视觉隐私区域，并通过同一提示路径接受用户自定义视觉标签。本地 OpenCV 检测器补全单靠定位易遗漏的红色与暗色骑缝章/边缘章。

这一设计有清晰的资源权衡。完整本地链路可能同时包含 PP-StructureV3、可选的 PaddleOCR-VL、HaS Text 与 LocateAnything-3B。即使有预热、GPU 健康检查、上下文压缩与串行调度，低于 16 GB 显存的设备在显存压力、KV 缓存分配、多页图像或并发请求下仍可能变慢。完整视觉链路推荐 16 GB 及以上 NVIDIA 显存。

如果你的文档不需要视觉识别，可在预设配置或单文件识别面板中关闭视觉特征。只保留 “OCR + HaS” 通常能获得更稳定的时延与更多显存余量。

---

## 预设

系统提供一个通用默认清单，外加三个行业预设：

| 预设 | 用途 |
|---|---|
| 通用（默认） | 人物、证件、护照、电话、邮箱、地址、日期、银行卡、机构——跨领域通用集 |
| 法律 | 当事人、代理人、法院、案号、合同标识与法律文书字段 |
| 金融 | 账户、卡号、交易、金额、机构、客户与金融业务数据 |
| 医疗 | 患者姓名、证件、电话、地址、出生日期、性别、年龄、社保、病历号 / 登记号 / 住院号、日期、时间、医疗机构与科室 |

识别项原子化、标签精确，因此一个标签恰好对应一个识别概念。文本与视觉链路预设相互独立。新建预设时，每个模块都支持全选与清空，便于针对场景快速裁剪 Schema。

---

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React、TypeScript、Vite、Tailwind CSS、Radix UI |
| 后端 | FastAPI、Pydantic、SQLite、本地文件存储 |
| 文本识别 | 通过 vLLM OpenAI 兼容服务的 HaS Text |
| OCR | PaddleOCR-VL / PP-StructureV3 能力 |
| 视觉检测 | LocateAnything-3B 视觉定位 + OpenCV 印章补全 |
| 导出 | 文本、图片、PDF、Word 与批量打包工作流 |

---

## 仓库结构

```text
backend/
  app/          FastAPI 应用、任务队列、识别编排、脱敏、导出
  config/       内置识别 Schema 与行业预设
  scripts/      本地模型服务与预热脚本

frontend/
  src/          React 工作台：单文件、批量、任务中心、结果、预设
  public/       前端静态资源

scripts/        根目录本地启动与停止脚本
```

---

## 安全与部署

- 仓库应只包含应用代码与默认配置。不要提交本地 `.env`、模型权重、真实样本、上传文件、运行时数据库、日志或导出结果。
- 默认部署模式为本地或内网使用。在对公网暴露系统之前，请配置认证、访问控制、反向代理、TLS、日志与密钥轮换策略。
- 认证支持多个本地用户。上传文件、批量任务、复核草稿、下载、预览、导出报告与清理操作均按已认证用户名隔离。首次初始化的用户为 `super_admin`；只有超级管理员可创建用户或修改运行时并发。
- 默认识别由模型能力与配置 Schema 驱动。正则仅作为用户自定义兜底机制存在。
- 将模型、样本、任务数据与导出目录保存在受访问控制与备份策略保护的私有运行时存储中。

---

## 多租户部署

对于需要租户隔离的客户部署，使用实例级隔离：每个租户一个 Docker Compose 项目，拥有各自的 `.env`、域名、JWT 密钥、网络与 Docker 卷。不要在租户间共享 `DATA_DIR`、`UPLOAD_DIR`、`OUTPUT_DIR`、SQLite 存储、导出结果或 `JWT_SECRET_KEY`。

PowerShell 租户启动示例：

```powershell
$env:BACKEND_ENV_FILE=".env.tenant-a"
docker compose --env-file .env.tenant-a -p redaction-tenant-a --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE

$env:BACKEND_ENV_FILE=".env.tenant-b"
docker compose --env-file .env.tenant-b -p redaction-tenant-b --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE
```

使用基于 `.env.production.example` 的每租户生产环境文件。为每个租户设置唯一的 `CORS_ORIGINS` 域名与 `JWT_SECRET_KEY`，保持 `AUTH_ENABLED=true`，并对敏感客户数据保持 `FILE_ENCRYPTION_ENABLED=true`。`BACKEND_ENV_FILE` 必须指向同一个租户环境文件，避免后端容器加载共享的本地 `.env`。

后端任务队列用 `JOB_CONCURRENCY` 控制并发的识别/脱敏作业项。若共享 GPU 需限制为三个并发作业项，请让所有租户实例的 `JOB_CONCURRENCY` 之和不超过 3：

| 部署形态 | 推荐设置 |
|---|---|
| 单租户独占一张 GPU | `JOB_CONCURRENCY=3` |
| 两租户共享一张 GPU | 按 SLA 拆分为 `2 + 1` |
| 三租户共享一张 GPU | 每租户 `JOB_CONCURRENCY=1` |

在共享 GPU 上为获得稳定时延，可从 `BATCH_RECOGNITION_PAGE_CONCURRENCY=1`、`HAS_NER_MAX_PARALLEL_REQUESTS=1`、`VISION_DUAL_PIPELINE_PARALLEL=false` 开始，待测得时延与显存余量后再上调。

---

## 用户隔离

在同一家公司部署内，使用一个应用实例并创建多个本地用户。用户共享同一服务 URL 与队列，但每个已认证用户名只能看到自己的文件、任务、复核草稿、导出、预览与清理范围。

首次登录初始化界面创建 `super_admin`。其余用户只能由超级管理员创建：

```bash
curl -X POST http://localhost:8000/api/v1/auth/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"username":"alice","password":"StrongPassw0rd!"}'
```

`JOB_CONCURRENCY=3` 仍表示整个实例最多同时处理三个后台作业项；额外的用户请求会排队，而不需要新的部署或端口。超级管理员可在“设置 -> 运行时”或通过仅管理员的 API 修改其在线取值：

```bash
curl -X PUT http://localhost:8000/api/v1/auth/concurrency \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"job_concurrency":3}'
```

---

## 贡献

欢迎提交 Issue 与 Pull Request。请让每个 PR 聚焦于一个问题或功能，并避免包含本地样本、实验脚本、模型权重、运行时数据或临时产物。

提交前请至少运行：

```bash
cd backend
ruff check app/

cd ../frontend
npm run build
```

---

## 许可证

本项目采用自定义的 [个人使用许可证](./LICENSE)：

- 个人可免费用于个人、非商业目的，包括个人项目、学习、研究、私人实验与演示。
- 付费交付、咨询交付、公司、机构、政府部门、团队及其他组织，在生产使用、产品集成、SaaS、托管服务、OEM 使用、再分发与采购场景下，需要单独的商业许可证。
- 模型权重、第三方依赖与数据集受各自许可证约束。

商业授权：**wwang11@alumni.nd.edu**

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=TracyWang95/DataInfra-RedactionEverything&type=Date)](https://star-history.com/#TracyWang95/DataInfra-RedactionEverything&Date)
