"""Start the local HaS Text llama.cpp-compatible server."""

from __future__ import annotations

import os
import sys
from pathlib import Path


CANONICAL_MODEL_NAME = "HaS_Text_0209_0.6B_Q4_K_M.gguf"
UPSTREAM_MODEL_NAME = "has_4.0_0.6B.gguf"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "has" / CANONICAL_MODEL_NAME

MODEL_PATH = Path(os.environ.get("HAS_MODEL_PATH", str(DEFAULT_MODEL))).expanduser()

if not MODEL_PATH.exists():
    for alt in [
        Path(r"D:\has_models") / CANONICAL_MODEL_NAME,
        Path("/mnt/d/has_models") / CANONICAL_MODEL_NAME,
        ROOT / "models" / "has" / UPSTREAM_MODEL_NAME,
    ]:
        if alt.exists():
            MODEL_PATH = alt
            break

HOST = os.environ.get("HAS_TEXT_HOST", "0.0.0.0")
PORT = int(os.environ.get("HAS_TEXT_PORT", "8080"))
N_CTX = int(os.environ.get("HAS_TEXT_N_CTX", "8192"))
N_GPU_LAYERS = int(os.environ.get("HAS_TEXT_N_GPU_LAYERS", "-1"))
ALLOW_CPU = os.environ.get("HAS_TEXT_ALLOW_CPU", "").strip().lower() in {"1", "true", "yes", "on"}


def _print_missing_model_help() -> None:
    print(f"\nERROR: HaS Text model file was not found: {MODEL_PATH}")
    print("\nExpected project filename:")
    print(f"  {CANONICAL_MODEL_NAME}")
    print("\nDownload the upstream GGUF and copy/rename it to the project filename:")
    print(
        "  python -c \"from huggingface_hub import hf_hub_download; "
        "hf_hub_download(repo_id='xuanwulab/HaS_4.0_0.6B_GGUF', "
        f"filename='{UPSTREAM_MODEL_NAME}', local_dir='/mnt/d/has_models')\""
    )
    print(f"  cp /mnt/d/has_models/{UPSTREAM_MODEL_NAME} /mnt/d/has_models/{CANONICAL_MODEL_NAME}")
    print("\nAlternative Docker target:")
    print(f"  backend/models/has/{CANONICAL_MODEL_NAME}")
    print("\nSee docs/MODELS.md for the full model layout.")


def main() -> None:
    print("=" * 50)
    print("  HaS Text local model service")
    print("=" * 50)

    if not MODEL_PATH.exists():
        _print_missing_model_help()
        sys.exit(1)

    print(f"\nModel path: {MODEL_PATH}")
    print(f"Server URL: http://{HOST}:{PORT}/v1")
    print(f"Context length: {N_CTX}")
    print(f"GPU layers: {N_GPU_LAYERS} (-1 means all layers; 0 means CPU)")
    print(f"GPU-only mode: {'no' if ALLOW_CPU or N_GPU_LAYERS == 0 else 'yes'}")
    print("\nLoading model...")

    try:
        import uvicorn
        import llama_cpp
        from llama_cpp.server.app import create_app
        from llama_cpp.server.settings import ModelSettings, ServerSettings

        supports_gpu = getattr(llama_cpp, "llama_supports_gpu_offload", lambda: None)()
        if N_GPU_LAYERS != 0 and not ALLOW_CPU and supports_gpu is False:
            print("\nERROR: llama-cpp-python was built without GPU offload support.")
            print("HaS Text defaults to GPU-only mode to avoid silent CPU fallback.")
            print("Install a CUDA/Vulkan-enabled llama.cpp runtime or set HAS_TEXT_ALLOW_CPU=1 for debug-only CPU mode.")
            sys.exit(1)

        app = create_app(
            server_settings=ServerSettings(host=HOST, port=PORT),
            model_settings=[
                ModelSettings(
                    model=str(MODEL_PATH),
                    n_ctx=N_CTX,
                    n_gpu_layers=N_GPU_LAYERS,
                    chat_format="chatml",
                )
            ],
        )

        print("\nModel loaded. Starting server...\n")
        uvicorn.run(app, host=HOST, port=PORT)

    except ImportError:
        print("\nERROR: llama-cpp-python is not installed.")
        print("\nInstall it with:")
        print("  pip install llama-cpp-python")
        print("\nOr use a prebuilt CPU wheel:")
        print("  pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu")
        sys.exit(1)
    except Exception as exc:
        print(f"\nFailed to start HaS Text service: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
