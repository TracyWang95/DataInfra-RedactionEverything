# HaS 本地模型部署指南

## 概述

HaS (Hide And Seek) 是一款面向敏感文档匿名化的本地 NER 模型，基于 `xuanwulab/HaS_4.0_0.6B_GGUF`。

## 模型位置

```
<项目根目录>/backend/models/has/has_4.0_0.6B.gguf
```

## 启动 HaS 服务

### 方法一：使用 llama.cpp 预编译版本（推荐）

1. 下载 llama.cpp releases: https://github.com/ggerganov/llama.cpp/releases
2. 解压后运行:

```powershell
cd <项目根目录>/backend
.\llama-server.exe -m .\models\has\has_4.0_0.6B.gguf --host 0.0.0.0 --port 8080
```

### 方法二：使用 Python (llama-cpp-python)

```powershell
# 安装（CPU版本，较快）
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

# 或编译安装（需要 CMake）
pip install llama-cpp-python

# 启动服务
python -m llama_cpp.server --model .\models\has\has_4.0_0.6B.gguf --host 0.0.0.0 --port 8080
```

### 方法三：使用 Ollama

```powershell
# 先将 GGUF 转换为 Ollama 格式
ollama create has -f Modelfile

# 运行
ollama serve
```

## 验证服务

服务启动后，访问: http://127.0.0.1:8080/v1

测试 NER:
```python
import httpx

response = httpx.post(
    "http://127.0.0.1:8080/v1/chat/completions",
    json={
        "messages": [{
            "role": "user",
            "content": '''Recognize the following entity types in the text.
Specified types:["人名","组织","地址"]
<text>北京市朝阳区人民法院张法官审理了原告李明与被告ABC公司的合同纠纷案件。</text>'''
        }]
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

期望输出:
```json
{"人名":["张法官","李明"],"组织":["北京市朝阳区人民法院","ABC公司"],"地址":[]}
```

## 系统架构

```
用户上传文件
     ↓
文件解析 (Word/PDF)
     ↓
混合 NER 识别
  ├── HaS 本地模型 (主力) ← 需要启动 llama-server
  └── 正则匹配 (补充)
     ↓
实体去重 + 指代消解
     ↓
前端展示 + 脱敏
```

## 常见问题

### Q: HaS 服务不可用时怎么办？
A: 系统会自动降级到纯正则匹配模式，但识别效果会下降。

### Q: 模型加载很慢？
A: 首次加载约需 30 秒，之后会更快。确保有足够内存（建议 4GB+）。

### Q: 如何使用 GPU 加速？
A: 安装 CUDA 版本的 llama-cpp-python:
```
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
```
