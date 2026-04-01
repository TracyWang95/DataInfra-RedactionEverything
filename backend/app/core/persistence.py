import json
import os
from enum import Enum
from typing import Any, Optional

import aiofiles


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def load_json(path: str, default: Optional[Any] = None) -> Any:
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return default


def save_json(path: str, data: Any) -> None:
    """同步写入 JSON（用于启动阶段等非异步上下文）。"""
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(data), f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


async def save_json_async(path: str, data: Any) -> None:
    """异步写入 JSON，避免阻塞事件循环（用于请求处理上下文）。"""
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    content = json.dumps(to_jsonable(data), ensure_ascii=False, indent=2)
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
        await f.write(content)
        await f.flush()
        # aiofiles 不直接支持 fsync，在非关键路径可接受
    os.replace(tmp_path, path)
