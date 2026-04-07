"""
HaS 模型服务启动脚本 (Python版本)
使用 llama-cpp-python 运行 HaS 4.0 0.6B GGUF 模型

安装依赖:
  pip install llama-cpp-python

如果需要 GPU 加速:
  CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
"""

import os
import sys

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "has", "has_4.0_0.6B.gguf")
HOST = "0.0.0.0"
PORT = 8080


def main():
    print("=" * 50)
    print("  HaS 本地模型服务 (Python)")
    print("=" * 50)
    
    # 检查模型文件
    if not os.path.exists(MODEL_PATH):
        print(f"\n错误: 模型文件不存在: {MODEL_PATH}")
        print("\n请先下载模型:")
        print("  python -c \"from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='xuanwulab/HaS_4.0_0.6B_GGUF', filename='has_4.0_0.6B.gguf', local_dir='./models/has')\"")
        sys.exit(1)
    
    print(f"\n模型路径: {MODEL_PATH}")
    print(f"服务地址: http://{HOST}:{PORT}/v1")
    print("\n加载模型中，请稍候...")
    
    try:
        from llama_cpp.server.app import create_app
        from llama_cpp.server.settings import ModelSettings, ServerSettings
        import uvicorn
        
        # 创建应用
        app = create_app(
            server_settings=ServerSettings(host=HOST, port=PORT),
            model_settings=[
                ModelSettings(
                    model=MODEL_PATH,
                    n_ctx=4096,
                    n_gpu_layers=-1,  # 使用所有可用GPU层
                    chat_format="chatml",
                )
            ],
        )
        
        print("\n模型加载成功！启动服务...\n")
        
        # 启动服务
        uvicorn.run(app, host=HOST, port=PORT)
        
    except ImportError:
        print("\n错误: 未安装 llama-cpp-python")
        print("\n请安装:")
        print("  pip install llama-cpp-python")
        print("\n或使用预编译版本:")
        print("  pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu")
        sys.exit(1)
    except Exception as e:
        print(f"\n启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
