# DataInfra-RedactionEverything

<p align="center">
  <strong>匿名化数据基础设施 · 本地敏感信息检测与脱敏</strong><br>
  支持 Word / PDF / 图片等多模态文档的识别、标注与匿名化处理<br>
  <b>全链路本地推理，无云端依赖</b> — 适用于合规数据集建设、档案数字化、多行业文档流水线
</p>

> **品牌说明**：对外产品名为 **DataInfra-RedactionEverything**。GitHub 仓库可能仍为 `TracyWang95/legal-redaction`；你可在 GitHub Settings 中将仓库 **Rename** 为 `DataInfra-RedactionEverything`，与本地文件夹名无关。

---

## ✨ 功能特性

| 模块 | 说明 |
|------|------|
| 📄 **多格式支持** | Word (.doc/.docx)、PDF、图片 (.jpg/.png) |
| 🧠 **OCR + NER 双引擎** | PaddleOCR-VL-1.5（文字识别）+ HaS Text 0209 Q4（命名实体识别） |
| 👁️ **本地视觉识别** | **HaS Image**（Ultralytics YOLO11，21 类分割，端口 8081） |
| ✏️ **交互式编辑** | 识别结果可选 / 可编辑 / 可拉框调整 |
| 🔄 **脱敏模式** | 智能替换 / 掩码 / 结构化替换 |
| 📊 **对比与导出** | 脱敏前后对比预览、下载 |
| 🧪 **测试用例** | `testdata/ce.png` |

---

## 🏗️ 架构总览

本项目采用**双 Pipeline 混合检测架构**，将 OCR 文字识别、NER 语义理解、视觉分割三者有机结合，实现对业务文档与扫描图像中各类敏感信息的精准定位与脱敏。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户上传文件                                    │
│                    (Word / PDF / 图片)                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         文件解析 & 图像提取                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
    ┌───────────────────────────┐   ┌───────────────────────────┐
    │   Pipeline 1: OCR + HaS   │   │  Pipeline 2: HaS Image    │
    │   (文字类敏感信息)          │   │  (视觉类敏感信息)          │
    └───────────────────────────┘   └───────────────────────────┘
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────┐   ┌───────────────────────────┐
    │  PaddleOCR-VL-1.5         │   │  YOLO11 (has_image_server) │
    │  ├─ 文字检测 + 识别        │   │  ├─ 21 类隐私区域分割       │
    │  ├─ 版面分析              │   │  ├─ 章/签名/证件等          │
    │  └─ 精确坐标定位           │   │  └─ 独立进程 :8081         │
    └───────────────────────────┘   └───────────────────────────┘
                    ▼                               │
    ┌───────────────────────────┐                   │
    │  HaS Text 0209 Q4_K_M     │                   │
    │  ├─ 命名实体识别 (NER)     │                   │
    │  ├─ 语义理解              │                   │
    │  └─ 指代消解              │                   │
    └───────────────────────────┘                   │
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────┐   ┌───────────────────────────┐
    │  文字匹配定位              │   │  坐标归一化               │
    │  (实体 → OCR 坐标)        │   │  (0-1 相对坐标)           │
    └───────────────────────────┘   └───────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │      IoU 去重 & 结果融合       │
                    │  (OCR 优先，图像分割补充)       │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │      交互式编辑 & 脱敏应用      │
                    └───────────────────────────────┘
```

---

## 🔬 脱敏算法详解

### 1. 双 Pipeline 混合检测

文档与图像中的敏感信息可分为两大类：

| 类别 | 敏感信息类型 | 检测方式 |
|------|-------------|---------|
| **文字类** | 姓名、身份证号、电话、银行卡号、地址、公司名等 | OCR + HaS NER |
| **视觉类** | 公章、签名、指纹、照片、二维码、水印等 | HaS Image (YOLO) |

传统 OCR 方案只能识别文字，无法处理印章、签名等视觉元素；而纯视觉大模型虽然能识别图像内容，但在精确定位文字边界上存在误差。本项目将两者优势结合：

- **OCR + HaS Pipeline**：擅长精准定位文字类敏感信息，坐标精确到像素级
- **HaS Image Pipeline**：YOLO 分割识别视觉类敏感区域，弥补纯文字 OCR 的盲区

两条 Pipeline **并行运行**，最后通过 IoU（交并比）算法去重融合，确保不遗漏、不重复。

### 2. OCR + HaS Pipeline 工作流程

这是处理文字类敏感信息的核心流程：

```
原始图像
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: PaddleOCR-VL 文字检测                               │
│  ─────────────────────────────────────────────────────────  │
│  • 检测图像中所有文字区域                                      │
│  • 识别文字内容                                              │
│  • 返回每个文字块的精确坐标 (四边形顶点)                        │
│  • 同时检测公章等视觉元素                                      │
└─────────────────────────────────────────────────────────────┘
    │
    │  输出: [{text: "张三", polygon: [[x1,y1]...]}, ...]
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: HaS 命名实体识别 (NER)                              │
│  ─────────────────────────────────────────────────────────  │
│  • 将所有 OCR 文字拼接成完整文本                               │
│  • 调用 HaS 模型进行语义分析                                   │
│  • 识别敏感实体类型（人名、身份证、电话等）                       │
│  • 支持自定义实体类型                                         │
└─────────────────────────────────────────────────────────────┘
    │
    │  输出: [{type: "PERSON", text: "张三"}, {type: "PHONE", text: "13800138000"}]
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 实体-坐标匹配                                       │
│  ─────────────────────────────────────────────────────────  │
│  • 在 OCR 文字块中查找每个敏感实体                             │
│  • 精确匹配：entity_text in block_text                       │
│  • 模糊匹配：SequenceMatcher > 0.85 (处理 OCR 识别误差)        │
│  • 子词定位：根据字符位置比例计算像素坐标                        │
└─────────────────────────────────────────────────────────────┘
    │
    │  输出: [{type: "PERSON", text: "张三", x: 100, y: 200, w: 50, h: 20}]
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 正则规则补充                                        │
│  ─────────────────────────────────────────────────────────  │
│  • 身份证号: [1-9]\d{5}(19|20)\d{2}(0[1-9]|1[0-2])...        │
│  • 手机号: 1[3-9]\d{9}                                       │
│  • 银行卡号: [3-6]\d{15,18}                                  │
│  • 邮箱: [a-zA-Z0-9._%+-]+@...                               │
│  • 与 NER 结果合并去重                                        │
└─────────────────────────────────────────────────────────────┘
```

**为什么要分离 OCR 和 NER？**

这是本项目的核心设计理念。传统方案让大模型同时做 OCR 和 NER，但这会导致：
- 坐标不精确（大模型返回的坐标常有偏差）
- 推理速度慢（视觉+语言双重计算）
- 难以处理复杂版面（表格、多栏等）

本项目采用**分工协作**策略：
- **PaddleOCR-VL**：专注文字检测，提供像素级精确坐标
- **HaS**：专注语义理解，识别敏感实体类型
- **文字匹配**：将两者结果关联，实现精准定位

### 3. HaS Image Pipeline（YOLO11，8081）

处理视觉类隐私区域（21 类分割）：独立微服务 `has_image_server.py`，主后端经 HTTP 调用 `/detect`，输出归一化 0–1 框，与 OCR+HaS 结果做 IoU 去重合并。

### 4. 结果融合与去重

两条 Pipeline 的结果需要智能融合：

```python
def deduplicate_boxes(boxes, iou_threshold=0.3):
    """
    去重策略：
    1. OCR 结果全部保留（坐标更精确）
    2. HaS Image：只保留与 OCR 不重叠的
    3. 重叠判断：IoU > 0.3 视为重复
    """
    ocr_boxes = [b for b in boxes if b.source == "ocr_has"]
    hi_boxes = [b for b in boxes if b.source == "has_image"]

    result = list(ocr_boxes)

    for hi_box in hi_boxes:
        is_duplicate = any(
            calculate_iou(hi_box, ocr_box) > iou_threshold
            for ocr_box in ocr_boxes
        )
        if not is_duplicate:
            result.append(hi_box)

    return result
```

### 5. 敏感信息分类体系

基于 **GB/T 37964-2019《信息安全技术 个人信息去标识化指南》** 构建：

| 分类 | 类型 ID | 说明 | 检测方式 |
|------|---------|------|---------|
| **直接标识符** | PERSON | 姓名 | HaS NER |
| | ID_CARD | 身份证号 | 正则 + NER |
| | PHONE | 电话号码 | 正则 + NER |
| | EMAIL | 电子邮箱 | 正则 |
| | BANK_CARD | 银行卡号 | 正则 + NER |
| | BANK_ACCOUNT | 银行账号 | NER |
| **准标识符** | COMPANY | 公司名称 | NER |
| | ADDRESS | 详细地址 | NER |
| | DATE | 日期 | 正则 + NER |
| | LICENSE_PLATE | 车牌号 | 正则 |
| | CASE_NUMBER | 案件编号 | NER |
| **视觉元素** | SEAL 等 | 公章/版面等（OCR 可识别印章文字） | OCR+HaS |
| | （21 类 slug） | 人脸、证件、二维码、屏幕等分割 | HaS Image |

---

## 📦 模型与服务

| 服务 | 模型/组件 | 用途 | 端口 |
|------|----------|------|------|
| **Backend API** | FastAPI | 主后端服务 | 8000 |
| **OCR** | PaddleOCR-VL-1.5 | 文字检测与识别 | 8082 |
| **NER** | [HaS Text 0209](https://huggingface.co/xuanwulab/HaS_Text_0209_0.6B_Q4) Q4_K_M（Qwen3-0.6B） | 命名实体识别 | 8080 |
| **HaS Image** | YOLO11（`sensitive_seg_best.pt`） | 视觉隐私区域分割 | 8081 |
| **Frontend** | React + Vite | 前端界面 | 3000 |

---

## 🚀 快速开始

### 环境要求

- **操作系统**：Windows 10/11 或 Linux（WSL2 可选）
- **Python**：3.10+
- **Node.js**：18+
- **GPU**：NVIDIA（建议 RTX 4060 及以上，8GB+ 显存）
- **Conda 环境（推荐）**：示例名为 `legal-redaction`（Python 3.10），与 `scripts\start_*.bat` 中的解释器路径一致；也可使用任意环境名并相应修改脚本

### Paddle GPU（推荐，用于 OCR 微服务 8082）

默认从 PyPI 安装会得到 **CPU 版** `paddlepaddle`，推理很慢。请在本机 **先装 GPU 版 Paddle**，再安装 `backend/requirements.txt`：

```powershell
# 1）安装 GPU 版 Paddle（CUDA 12.6 官方源，与 paddlepaddle 3.3.x 对齐）
powershell -ExecutionPolicy Bypass -File .\scripts\install_paddle_gpu.ps1

# 2）再装后端依赖（含 paddleocr）
cd backend
pip install -r requirements.txt
```

验证：

```text
python -c "import paddle; print(paddle.is_compiled_with_cuda(), paddle.get_device())"
```

应输出 `True` 与 `gpu:0`（或类似）。然后启动 `ocr_server.py`（8082），控制台会打印当前 Paddle 设备信息。

### 目录结构（建议）

```
<你的工作目录>/
├── llama.cpp/                  # llama.cpp 可执行文件
│   └── llama-server.exe        # 或 llama-server（Linux）
├── has_models/（或任意目录）      # 本机模型：HaS NER .gguf、HaS Image .pt 等
│   ├── HaS_Text_0209_0.6B_Q4_K_M.gguf   # HaS NER（推荐，见 HAS_NER_GGUF）
│   └── sensitive_seg_best.pt
└── DataInfra-RedactionEverything/   # 本项目（或任意克隆目录名）
    ├── backend/
    ├── frontend/
    └── ...
```

> **提示**：以下命令中的路径请根据你的实际目录结构调整。

---

### 1️⃣ 启动 HaS Image（YOLO，端口 8081）

Windows：执行 `scripts\start_has_image.bat`（默认读取 `HAS_IMAGE_WEIGHTS`，未设置时使用 `has_models/sensitive_seg_best.pt` 或 `backend\models\has_image\sensitive_seg_best.pt`）。

```bash
cd backend
pip install -r requirements.txt   # 含 ultralytics
set HAS_IMAGE_WEIGHTS=D:\path\to\sensitive_seg_best.pt
python has_image_server.py
```

---

### 2️⃣ 启动 HaS（本地 NER 服务）

```bash
# Windows（或下载 GGUF 后用 -m 指向本机路径；脚本 start_has.bat 已默认新仓库）
.\llama-server.exe -hf xuanwulab/HaS_Text_0209_0.6B_Q4 --port 8080 -ngl 99 --host 0.0.0.0 -c 8192 -np 1
```

```bash
# Linux / WSL2
./llama-server -hf xuanwulab/HaS_Text_0209_0.6B_Q4 --port 8080 -ngl 99 --host 0.0.0.0 -c 8192 -np 1
```

---

### 3️⃣ 启动后端

```bash
cd backend
python -m venv venv        # 或使用 conda
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 启动 OCR 微服务（端口 8082）
python ocr_server.py &

# 启动主后端（端口 8000）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

### 4️⃣ 启动前端

```bash
cd frontend
npm install
npm run dev -- --port 3000
```

访问：**http://localhost:3000**

---

### 🚀 一键启动（Windows PowerShell）

**推荐（项目自带脚本，使用 conda 环境 `legal-redaction`）：**

```powershell
$RepoRoot = "repo-root/DataInfra-RedactionEverything"   # 改为你的实际克隆路径
Set-Location $RepoRoot
# 停止 8080/8081/8082/8000/3000 上的监听进程
powershell -ExecutionPolicy Bypass -File .\scripts\stop_all.ps1
# 一键启动全部服务（内部会先尝试释放端口）
powershell -ExecutionPolicy Bypass -File .\scripts\start_all.ps1
```

---

假设目录结构如下（手动逐条启动时参考）：
- `llama.cpp\` - llama.cpp 可执行文件
- `has_models\` - 模型文件
- `$RepoRoot` - 本项目（见上一段 `$RepoRoot`）

```powershell
$RepoRoot = "repo-root/DataInfra-RedactionEverything"   # 改为你的实际克隆路径
# 1. HaS NER 服务 (端口 8080) — 推荐 HaS_Text_0209 Q4_K_M
Start-Process -FilePath "llama.cpp/llama-server.exe" -ArgumentList "-m has_models/HaS_Text_0209_0.6B_Q4_K_M.gguf -ngl 99 --host 0.0.0.0 --port 8080 -c 8192 -np 1"

# 2. HaS Image / YOLO（端口 8081）— 见 scripts\start_has_image.bat
Start-Process -FilePath "$RepoRoot\scripts\start_has_image.bat" -WorkingDirectory $RepoRoot

# 3. PaddleOCR-VL 服务 (端口 8082) — 建议使用 conda env legal-redaction + GPU Paddle
Start-Process powershell -ArgumentList "-Command cd $RepoRoot\backend; conda activate legal-redaction; `$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True'; python ocr_server.py"

# 4. 后端 API (端口 8000)
Start-Process powershell -ArgumentList "-Command cd $RepoRoot\backend; conda activate legal-redaction; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

# 5. 前端 (端口 3000)
Start-Process powershell -ArgumentList "-Command cd $RepoRoot\frontend; npm run dev"
```

**验证服务状态：**
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/services" | ConvertTo-Json
```

---

## 🛠️ 本地模型部署踩坑记录

### HaS Image（YOLO11）

| 问题 | 解决方案 |
|------|----------|
| 8081 `/health` 中 `ready=false` | 检查 `HAS_IMAGE_WEIGHTS` 路径是否存在；`pip install ultralytics` |
| 显存不足 | 使用更小 batch / CPU 推理（较慢） |

权重示例：xuanwulab/HaS_Image 相关发布中的 `sensitive_seg_best.pt`。

---

### PaddleOCR-VL-1.5

- 首次启动时会自动下载到本地缓存（约 2GB）
- 后续运行会复用缓存，无需重复下载

---

### HaS Text 0209（Qwen3-0.6B，Q4_K_M）

- 仓库：`xuanwulab/HaS_Text_0209_0.6B_Q4`；本机 GGUF 见 `scripts/start_has.ps1`
- 通过 llama-server 的 `-hf` 或 `-m` 加载；后端默认连接 `http://127.0.0.1:8080/v1`
- 侧栏展示名可通过环境变量 `HAS_NER_DISPLAY_NAME` 覆盖（默认 `HaS-Text-0209-Q4`）

---

## 🧪 环境检查

Windows PowerShell：

```powershell
.\scripts\check_env.ps1
```

脚本会检查：
- Python / Node / npm
- NVIDIA 驱动
- 模型文件是否存在
- 各服务端口是否监听

---

## 🧪 冒烟测试

详见：`tests/smoke_test.md`

测试用例：`testdata/ce.png`

---

## 📁 项目结构

```
<项目根目录>/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/             # API 路由
│   │   ├── core/            # 配置、HaS Image 客户端等
│   │   └── services/        # 业务逻辑
│   │       ├── vision_service.py      # 双 Pipeline 调度
│   │       ├── hybrid_vision_service.py # OCR+HaS 混合服务
│   │       ├── ocr_service.py         # PaddleOCR 客户端
│   │       └── has_service.py         # HaS NER 服务
│   ├── ocr_server.py        # OCR 微服务入口
│   └── requirements.txt
├── frontend/                # React + Vite 前端
│   ├── src/
│   │   ├── components/      # 通用组件
│   │   └── pages/           # 页面
│   └── package.json
├── scripts/                 # 环境检查脚本
├── testdata/                # 测试用例
└── tests/                   # 测试模板
```

---

## 📖 API 文档

- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc

---

## 🎯 适用场景

本项目特别适合以下业务场景：

| 场景 | 说明 |
|------|------|
| **高质量数据集 / ML 流水线** | 训练或评测前对文档、票据、扫描件做本地匿名化，降低个人信息泄露风险 |
| **多行业文档脱敏** | 合同、政务与医疗表单、金融单据等批量检测与掩码 |
| **档案数字化** | 纸质档案扫描后的隐私保护与可发布版本导出 |
| **合规与出境评估** | 配合 GDPR、《个人信息保护法》等要求的去标识化与最小化暴露面 |

---

## 🤝 贡献

欢迎 Issue 与 PR！详见 [CONTRIBUTING.md](./CONTRIBUTING.md)

---

## 📄 许可证

[MIT License](./LICENSE)

---

## ⭐ Star History

如果这个项目对你有帮助，请点个 Star ⭐
