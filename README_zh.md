<div align="center">

# DataInfra &middot; RedactionEverything

**本地优先的非结构化数据匿名化工作台**

不止个人信息，也不止固定规则。RedactionEverything 面向合同、扫描件、图片、PDF、Word 和纯文本，使用语义模型、OCR、视觉检测和可配置清单，把需要保护的内容识别出来，再交给人工复核和导出流程。

[![License](https://img.shields.io/badge/license-Personal%20Use-blue.svg)](./LICENSE)
[![CI](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml/badge.svg)](https://github.com/TracyWang95/DataInfra-RedactionEverything/actions/workflows/ci.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)
[![GitHub Stars](https://img.shields.io/github/stars/TracyWang95/DataInfra-RedactionEverything.svg?style=flat&logo=github&label=Stars&cacheSeconds=3600)](https://github.com/TracyWang95/DataInfra-RedactionEverything/stargazers)

**语言：** [English](./README.md) | 中文

> 本项目采用自定义 [Personal Use License](./LICENSE)：个人用途可免费使用；付费工作、咨询交付、公司、机构、政府、团队或其他组织的生产使用、集成、SaaS、托管服务和再分发需取得单独商业授权。
>
> 商业授权、支持服务、采购条款或定制交付请联系：**wwang11@alumni.nd.edu**。

<p>
  <a href="#项目简介">项目简介</a> &middot;
  <a href="#项目定位">项目定位</a> &middot;
  <a href="#核心能力">核心能力</a> &middot;
  <a href="#近期已验证更新">近期更新</a> &middot;
  <a href="#快速开始">快速开始</a> &middot;
  <a href="#系统架构">系统架构</a> &middot;
  <a href="#模型服务">模型服务</a> &middot;
  <a href="#模型与致谢">模型与致谢</a> &middot;
  <a href="#技术栈">技术栈</a> &middot;
  <a href="#多租户部署">多租户</a> &middot;
  <a href="#用户隔离">用户隔离</a> &middot;
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
| OCR + HaS | 图像和扫描件先抽取文字块，再用 HaS Text 做语义识别并回写坐标 |
| HaS Image YOLO | 检测人脸、指纹、证件、银行卡、印章、二维码、屏幕等视觉区域 |
| VLM checklist | 作为图像管道补充能力，默认聚焦签字等需要视觉语义判断的区域 |
| 配置清单 | 内置通用、法律、金融、医疗清单，也支持自定义文本、图像和兜底项 |
| 本地部署 | 前端、后端、模型服务都可以在本机或内网 GPU 环境中运行 |

---

## 近期已验证更新

当前分支完成了一轮面向演示、客户部署和真实文档召回的稳定性优化。下面这些改动是通用工程方案，不是针对某张图片、某个公司名或某个字段写死规则：

| 方向 | 更新 |
|---|---|
| 用户与租户隔离 | 识别项、配置清单、视觉 pipeline、文件、任务、复核草稿、历史结果、预览、导出和清理操作都按登录用户隔离；`super_admin` 保留系统配置和用户管理权限。 |
| 单 GPU 调度 | OCR、HaS Image、HaS NER、VLM 等显存密集推理通过统一队列保护，避免 16 GB 单卡被并发请求打满；VLM 作为靠后的视觉语义补充阶段运行。 |
| OCR 召回 | OCR 文本框坐标匹配、模糊匹配和视觉行级匹配增强，可召回间距较大或被切碎的公司/机构名称，不依赖写死公司名。 |
| 表格语义召回 | 利用表头、单元格和数字列语义召回单价、合计、百分比、账户、合同金额等敏感值。 |
| 印章与签字兜底 | HaS Image 仍是主视觉检测；本地红章/暗章兜底和 VLM/笔迹签字检测补充边缘章、骑缝章和手写签字。 |
| NER 稳定性 | HaS NER 增加容错 JSON 解析、长实体分批和更高生成 token 限制，降低响应截断和解析失败概率。 |
| UI/UX 稳定性 | 新用户首次登录进入开始页；设置页暴露管理员、运行配置和监控入口；批量复核/导出状态更清晰；窄屏无横向溢出；图片复核不再过早释放预览 `blob:` URL。 |
| 真实数据验证 | 使用 `D:\ceshi` 真实文件跑完整 UI 批量流程：7/7 上传、识别、复核、匿名化和导出；共 271 个识别项；0 个失败文件；质量报告为 `ready_for_delivery`。 |

本轮验证命令：

```bash
PYTHONPATH=backend pytest backend/tests -q

cd frontend
npm run lint
npm run build
```

真实界面回归使用 Playwright 覆盖了批量上传、识别、复核、匿名化、ZIP 导出、质量报告导出、浏览器 console 错误和 390 px 窄屏布局。

---

## 快速开始

### 环境要求

| 依赖 | 推荐版本 |
|---|---|
| Node.js | 24 LTS |
| Python | 3.11 |
| GPU | NVIDIA GPU，建议 16 GB 显存用于完整图像管道 |
| CUDA | 按 Paddle / vLLM / llama.cpp 的本地版本匹配 |

模型权重、真实样本、上传文件、运行数据库和导出结果不随仓库提交。请按自己的本地路径配置。

### 本地一键启动（Windows + WSL）

本地完整模型链路建议从仓库根目录启动：

```bash
npm run dev
```

这个入口会按固定顺序启动本地服务：WSL 中的 vLLM 模型服务和 OCR 包装服务、Windows 上的 llama.cpp VLM、HaS Image、后端 API，最后启动前端。脚本会先执行模型预热，只有 HaS Text、PaddleOCR-VL、PP-StructureV3、HaS Image 和 GLM VLM 全部预热成功后，才会输出：

```text
[dev] ready: http://localhost:3000
```

关闭所有本地服务：

```bash
npm run stop
```

如果 WSL localhost 转发不可用，启动脚本会自动使用 WSL IP 连接 vLLM/OCR 服务，避免前端服务探测显示离线。模型服务应保持 GPU/CUDA 推理；`/health/services` 中任一模型出现 CPU fallback 风险时，应先修正环境再处理文件。

### 手动启动后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

后端启动后可以检查：

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

打开：

```text
http://localhost:3000
```

### Docker

仓库保留 Dockerfile 和 compose 配置，适合做后端、前端和模型服务容器化。生产环境部署前请确认 `.env`、模型挂载、GPU runtime、认证和反向代理配置。

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
| HaS Text NER   |     | OCR text boxes |     | YOLO / VLM     |
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

默认本地端口如下：

| 服务 | 默认端口 | 说明 |
|---|---:|---|
| 后端 API | 8000 | 上传、任务、配置、识别、导出 |
| 前端 | 3000 | 浏览器工作台 |
| HaS Text | 8080 | OpenAI 兼容接口，文本 NER |
| HaS Image | 8081 | YOLO11 视觉区域检测 |
| PaddleOCR-VL | 8082 | OCR、版面和文字框 |
| VLM | 8090 | OpenAI 兼容接口，视觉语义补充 |

常用环境变量：

```env
OCR_BASE_URL=http://127.0.0.1:8082
HAS_TEXT_RUNTIME=vllm
HAS_TEXT_VLLM_BASE_URL=http://127.0.0.1:8080/v1
HAS_IMAGE_BASE_URL=http://127.0.0.1:8081
VLM_BASE_URL=http://127.0.0.1:8090
VLM_MODEL_NAME=GLM-4.6V-Flash-Q4
```

显存紧张时，优先调整上下文、最大生成长度、并发和图像尺寸；不要让关键模型静默回退到 CPU，否则网页会表现为长时间无结果或服务探测离线。

---

## 模型与致谢

RedactionEverything 是编排层和产品层，不声明拥有第三方模型权重。本仓库不重新分发这些权重；部署前请从官方仓库下载模型，阅读对应 model card，并遵守各模型、权重和运行时项目的许可证与使用条款。

| 组件 | 上游模型或项目 | 用途 |
|---|---|---|
| PaddleOCR-VL | [PaddlePaddle/PaddleOCR-VL](https://huggingface.co/PaddlePaddle/PaddleOCR-VL) | 文档 OCR、版面理解、文字框和页面结构抽取 |
| HaS Text | [xuanwulab/HaS_4.0_0.6B](https://huggingface.co/xuanwulab/HaS_4.0_0.6B)，可选 [xuanwulab/HaS_4.0_0.6B_GGUF](https://huggingface.co/xuanwulab/HaS_4.0_0.6B_GGUF) | 文本和 OCR 文本块的语义 NER |
| HaS Image | [xuanwulab/HaS_Image_0209_FP32](https://huggingface.co/xuanwulab/HaS_Image_0209_FP32) | 基于 YOLO11 的视觉隐私区域分割 |
| GLM VLM | [zai-org/GLM-4.6V-Flash](https://huggingface.co/zai-org/GLM-4.6V-Flash)，本地 llama.cpp 部署可使用兼容 GGUF 量化版本，例如 [unsloth/GLM-4.6V-Flash-GGUF](https://huggingface.co/unsloth/GLM-4.6V-Flash-GGUF) | 通过 rubric/checklist 做视觉语义识别，当前默认聚焦签字 |
| YOLO 运行时 | [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) | HaS Image 实例分割运行框架 |
| llama.cpp 运行时 | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | GGUF 权重的本地 OpenAI 兼容 VLM 服务 |
| vLLM 运行时 | [vLLM](https://github.com/vllm-project/vllm) | HaS Text 和 PaddleOCR-VL 的本地 OpenAI 兼容服务 |

感谢 PaddlePaddle、腾讯玄武实验室、Z.ai、Unsloth、Ultralytics、llama.cpp、vLLM 以及开源模型社区。正是这些模型和运行时项目，让本地优先的文档匿名化能够在消费级 GPU 上落地。

---

## 局限性与显存提示

RedactionEverything 默认坚持本地或内网闭环推理，原因是匿名化系统处理的正是原始敏感文件；把文件交给联网 API 虽然可以使用更大的视觉语言模型，但也会削弱匿名化基础设施本身的隐私边界。因此项目的默认方向是单卡笔记本可部署，并尽量通过量化、上下文控制、并发控制和管道编排把完整链路压到本地 GPU 内运行。

图像管道中的 VLM 不是为了替代 HaS Image YOLO11，而是作为补充能力存在。当前 YOLO11 视觉检测覆盖人脸、指纹、证件、银行卡、印章、二维码、屏幕等常见可视区域，但没有单独训练签字目标检测模型；签字、手写签署痕迹这类目标更依赖视觉语义判断，所以默认使用 GLM-4.6V-Flash Q4 量化模型，通过 rubric/checklist 方式识别签名区域。

这也带来明确的资源取舍：完整本地链路同时包含 PaddleOCR-VL、HaS Text、HaS Image YOLO 和 GLM VLM 四路模型。即使启动脚本已经做了预热、GPU 探测、上下文压缩和 VLM 串行调度，16GB 显存以下的设备仍可能因为显存压力、KV cache、图像页数或并发请求而出现速度下降。建议完整图像管道使用 16GB 及以上 NVIDIA GPU；如果文件场景不需要识别签名，可以在配置清单或单次处理页面关闭 VLM/签字识别项，只保留 OCR+HaS 与 HaS Image，以获得更稳定的速度和显存余量。

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
| OCR | PaddleOCR-VL / PP-Structure 相关能力 |
| 视觉检测 | HaS Image YOLO11、VLM checklist |
| 导出 | 文本、图片、PDF、Word 处理与批量打包 |

---

## 代码结构

```text
backend/
  app/          FastAPI 应用、任务队列、识别编排、脱敏和导出
  config/       内置识别清单和行业预设
  scripts/      本地模型服务启动与预热脚本

frontend/
  src/          React 工作台、任务中心、处理结果、单次处理、批量处理和配置清单
  public/       前端静态资源
```

---

## 多租户部署

客户级租户隔离建议使用实例级隔离：每个租户一个 Docker Compose project，使用独立的 `.env`、域名、JWT 密钥、网络和 Docker volume。不要在不同租户之间共享 `DATA_DIR`、`UPLOAD_DIR`、`OUTPUT_DIR`、SQLite 存储、导出结果或 `JWT_SECRET_KEY`。

PowerShell 示例：

```powershell
$env:BACKEND_ENV_FILE=".env.tenant-a"
docker compose --env-file .env.tenant-a -p redaction-tenant-a --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE

$env:BACKEND_ENV_FILE=".env.tenant-b"
docker compose --env-file .env.tenant-b -p redaction-tenant-b --profile gpu up -d
Remove-Item Env:\BACKEND_ENV_FILE
```

生产环境建议基于 `.env.production.example` 为每个租户准备独立配置。每个租户应设置唯一的 `CORS_ORIGINS` 域名和 `JWT_SECRET_KEY`，敏感客户数据场景保持 `AUTH_ENABLED=true` 与 `FILE_ENCRYPTION_ENABLED=true`。`BACKEND_ENV_FILE` 必须指向同一个租户配置文件，避免后端容器误读共享本地 `.env`。

后端任务队列使用 `JOB_CONCURRENCY` 控制并发识别/匿名化任务项。如果一张共享 GPU 最多允许 3 个并发任务项，应保证所有租户实例的 `JOB_CONCURRENCY` 之和不超过 3：

| 部署形态 | 推荐设置 |
|---|---|
| 单租户独占 GPU | `JOB_CONCURRENCY=3` |
| 两个租户共享一张 GPU | 按 SLA 拆成 `2 + 1` |
| 三个租户共享一张 GPU | 每个租户 `JOB_CONCURRENCY=1` |

共享 GPU 上要获得更稳定延迟，建议从 `BATCH_RECOGNITION_PAGE_CONCURRENCY=1`、`HAS_NER_MAX_PARALLEL_REQUESTS=1`、`VISION_DUAL_PIPELINE_PARALLEL=false` 开始，再根据实测延迟和显存余量逐步上调。

---

## 用户隔离

同一公司内部署时，建议使用一个应用实例并创建多个本地用户。用户共享同一个访问地址和任务队列，但每个登录用户只能看到自己的文件、任务、复核草稿、导出、预览和清理范围。

首次初始化登录页面会创建 `super_admin`。后续普通用户只能由超级管理员创建：

```bash
curl -X POST http://localhost:8000/api/v1/auth/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"username":"alice","password":"StrongPassw0rd!"}'
```

`JOB_CONCURRENCY=3` 表示当前应用实例最多同时处理 3 个后台任务项；额外用户请求会排队，不需要更换端口或重新部署。超级管理员可以在设置页的运行配置里调整并发，也可以调用管理员 API：

```bash
curl -X PUT http://localhost:8000/api/v1/auth/concurrency \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"job_concurrency":3}'
```

---

## 安全与部署

- 仓库只包含应用代码和默认配置，不包含本地 `.env`、模型权重、样本数据、上传文件、运行数据库、日志或导出结果。
- 项目默认面向本地或内网部署；如需公网访问，请配置认证、访问控制、反向代理、TLS、日志留存和密钥轮换策略。
- 认证支持多个本地用户。上传文件、批量任务、复核草稿、下载、预览、导出报告和清理操作都限定在当前登录用户名范围内。首次初始化用户是 `super_admin`；只有超级管理员可以创建用户或调整运行并发。
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
