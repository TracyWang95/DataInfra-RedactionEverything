# PaddleOCR-VL 安装指南

> 本文档专为 Windows 用户准备，帮助你从零配置 PaddleOCR-VL-1.5 环境。

---

## 📋 环境要求

| 组件 | 要求 |
|------|------|
| **操作系统** | Windows 10/11 |
| **Python** | 3.10.x（**必须是 3.10，不是 3.11/3.12**） |
| **CUDA** | 11.8 或 12.1（推荐 11.8） |
| **cuDNN** | 8.6+ |
| **GPU** | NVIDIA（建议 RTX 3060 及以上，6GB+ 显存） |

> ⚠️ **关键提示**：PyTorch、CUDA、cuDNN 版本必须严格对应，这是 PaddlePaddle 的核心依赖。

---

## 🔧 安装步骤

### 1️⃣ 安装 Conda（如果没有）

推荐使用 [Miniconda](https://docs.conda.io/en/latest/miniconda.html)：

```powershell
# 下载 Miniconda（Windows 64-bit）
# https://docs.conda.io/en/latest/miniconda.html

# 安装完成后，打开 Anaconda Prompt 或 PowerShell
conda --version  # 应显示版本号
```

---

### 2️⃣ 创建独立 Conda 环境

```powershell
# 创建 Python 3.10 环境（名称可自定义，这里用 oda）
conda create -n oda python=3.10 -y

# 激活环境
conda activate oda

# 确认 Python 版本
python --version
# 输出应为: Python 3.10.x
```

---

### 3️⃣ 安装 PyTorch（GPU 版）

这是最关键的一步，**必须与 CUDA 版本匹配**：

```powershell
# 方法一：CUDA 11.8（推荐）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 方法二：CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**验证安装：**

```python
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA version: {torch.version.cuda}')"
```

期望输出：
```
PyTorch: 2.x.x+cu118
CUDA available: True
CUDA version: 11.8
```

> 🚨 如果 `CUDA available: False`，说明 PyTorch 和 CUDA 版本不匹配，需要重新安装。

---

### 4️⃣ 安装 PaddlePaddle（GPU 版）

```powershell
# CUDA 11.8 版本
pip install paddlepaddle-gpu==2.6.2 -i https://mirror.baidu.com/pypi/simple

# 或 CUDA 12.1 版本
# pip install paddlepaddle-gpu==2.6.2.post120 -i https://mirror.baidu.com/pypi/simple
```

**验证安装：**

```python
python -c "import paddle; print(f'PaddlePaddle: {paddle.__version__}'); print(f'GPU available: {paddle.device.is_compiled_with_cuda()}')"
```

期望输出：
```
PaddlePaddle: 2.6.2
GPU available: True
```

---

### 5️⃣ 安装 PaddleOCR

```powershell
# 安装 PaddleOCR（带文档解析功能）
pip install "paddleocr[doc-parser]>=2.10.0"
```

这会自动安装：
- `paddleocr` - OCR 核心库
- `paddlenlp` - NLP 依赖
- `paddleclas` - 分类模型

---

### 6️⃣ 验证 PaddleOCR-VL

```python
# 测试脚本
from paddleocr import PaddleOCRVL

# 初始化（首次会下载模型，约 2GB）
ocr = PaddleOCRVL()

# 测试图片（换成你的图片路径）
result = ocr.predict("test.png", max_new_tokens=256)
print(result)
```

首次运行会下载模型到本地缓存（`~/.paddleocr/`），后续直接使用缓存。

---

## 🏃 运行 OCR 服务

```powershell
# 确保在 oda 环境中
conda activate oda

# 进入项目 backend 目录（将路径改为你的克隆位置）
cd <项目根目录>\backend

# 启动 OCR 微服务（端口 8082）
python ocr_server.py
```

看到以下输出说明成功：

```
[OCR] PaddleOCR-VL-1.5 loaded
[OCR] Warming up...
[OCR] Warmup complete!
INFO:     Uvicorn running on http://0.0.0.0:8082
```

---

## 🔥 常见问题 & 解决方案

### Q1: `DLL load failed` 或 `No module named 'paddle'`

**原因**：CUDA / cuDNN 版本不匹配

**解决**：
```powershell
# 1. 检查 NVIDIA 驱动
nvidia-smi
# 确保驱动版本 >= 450.x

# 2. 检查 CUDA 工具包
nvcc --version
# 应显示 CUDA 11.8 或 12.1

# 3. 重新安装 PaddlePaddle
pip uninstall paddlepaddle-gpu -y
pip install paddlepaddle-gpu==2.6.2 -i https://mirror.baidu.com/pypi/simple
```

---

### Q2: `Could not locate zlibwapi.dll`

**原因**：缺少 zlib 库

**解决**：
```powershell
# 下载 zlibwapi.dll 并放到 CUDA bin 目录
# 通常是 C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin

# 或者用 conda 安装
conda install -c conda-forge zlib
```

---

### Q3: `RuntimeError: CUDA out of memory`

**原因**：显存不足

**解决**：
- 使用更小的图片（缩放到 1600px 以内）
- 关闭其他占用显存的程序
- 设置环境变量限制显存：
  ```powershell
  $env:CUDA_VISIBLE_DEVICES = "0"
  $env:FLAGS_fraction_of_gpu_memory_to_use = "0.8"
  ```

---

### Q4: PaddleOCR-VL 加载失败，降级到 PaddleOCR-2.x

这是正常的 fallback 机制。如果看到：
```
[OCR] PaddleOCR-VL init failed: xxx
[OCR] PaddleOCR-2.x loaded (fallback)
```

说明 PaddleOCR-VL 模型加载出错，系统自动降级到传统 OCR。

**解决**：
```powershell
# 删除模型缓存，重新下载
Remove-Item -Recurse -Force "$env:USERPROFILE\.paddleocr"

# 重新启动服务
python ocr_server.py
```

---

### Q5: 首次启动很慢

正常现象！首次运行会：
1. 下载 PaddleOCR-VL 模型（约 2GB）
2. 预热模型（Warmup）

后续启动会直接使用缓存，速度很快。

---

## 📦 完整安装脚本（一键版）

```powershell
# 保存为 install_paddleocr.ps1

# 1. 创建环境
conda create -n oda python=3.10 -y
conda activate oda

# 2. 安装 PyTorch (CUDA 11.8)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 3. 安装 PaddlePaddle
pip install paddlepaddle-gpu==2.6.2 -i https://mirror.baidu.com/pypi/simple

# 4. 安装 PaddleOCR
pip install "paddleocr[doc-parser]>=2.10.0"

# 5. 验证
python -c "import paddle; print('Paddle OK:', paddle.device.is_compiled_with_cuda())"
python -c "from paddleocr import PaddleOCRVL; print('PaddleOCR-VL OK')"

Write-Host "安装完成！" -ForegroundColor Green
```

---

## 🔗 参考资源

- [PaddleOCR 官方文档](https://paddlepaddle.github.io/PaddleOCR/)
- [PaddlePaddle 安装指南](https://www.paddlepaddle.org.cn/install/quick)
- [PyTorch 官方安装](https://pytorch.org/get-started/locally/)
- [CUDA Toolkit 下载](https://developer.nvidia.com/cuda-toolkit-archive)

---

## ✅ 环境检查清单

| 检查项 | 命令 | 预期结果 |
|--------|------|----------|
| Python 版本 | `python --version` | `3.10.x` |
| PyTorch CUDA | `python -c "import torch; print(torch.cuda.is_available())"` | `True` |
| PaddlePaddle CUDA | `python -c "import paddle; print(paddle.device.is_compiled_with_cuda())"` | `True` |
| PaddleOCR-VL | `python -c "from paddleocr import PaddleOCRVL"` | 无报错 |
| NVIDIA 驱动 | `nvidia-smi` | 显示 GPU 信息 |

---

**配置成功后，即可运行 `python ocr_server.py` 启动 OCR 服务！** 🎉
