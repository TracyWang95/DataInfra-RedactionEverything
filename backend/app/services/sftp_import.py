# Copyright 2026 DataInfra-RedactionEverything Contributors
"""SFTP 主动拉取（第五段方案二）：平台从内网另一台服务器拉文件进批量任务。

- 源配置每用户各自持有；凭据 Fernet 加密（复用 structured 的密钥）
- paramiko 懒加载（默认不 import；测试注入 fake client）
- 远程路径强制约束在源的 root_path 之内
- 落地后登记链全量复用 process_upload
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import secrets
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.services.structured_connections import decrypt_credential, encrypt_credential

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_SFTP_TIMEOUT = 15.0

# 测试注入点：返回具备 listdir_attr(path)/get(remote, local)/close() 的对象
_client_factory: Callable[..., Any] | None = None


def _store_path() -> str:
    return os.path.join(settings.DATA_DIR, "sftp_sources.json")


def _load() -> dict[str, Any]:
    path = _store_path()
    if not os.path.exists(path):
        return {"sources": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {"sources": {}}
    except (OSError, json.JSONDecodeError):
        logger.exception("sftp_sources.json unreadable")
        return {"sources": {}}


def _save(doc: dict[str, Any]) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _check_host_allowed(host: str) -> None:
    allowlist = [h.strip() for h in (settings.SFTP_HOST_ALLOWLIST or "").split(",") if h.strip()]
    if allowlist and host not in allowlist:
        raise HTTPException(
            status_code=400,
            detail=f"主机 {host} 不在允许清单内（SFTP_HOST_ALLOWLIST）",
        )


def create_source(
    owner_id: str,
    *,
    name: str,
    host: str,
    port: int = 22,
    username: str,
    password: str | None = None,
    private_key: str | None = None,
    root_path: str = "/",
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name or not (host or "").strip() or not (username or "").strip():
        raise HTTPException(status_code=400, detail="名称/主机/账号均为必填")
    if not (1 <= int(port) <= 65535):
        raise HTTPException(status_code=400, detail="端口须为 1-65535")
    if not password and not private_key:
        raise HTTPException(status_code=400, detail="密码或私钥至少提供一项")
    _check_host_allowed(host.strip())
    with _lock:
        doc = _load()
        sources = doc.setdefault("sources", {})
        source_id = secrets.token_hex(8)
        sources[source_id] = {
            "owner_id": owner_id,
            "name": clean_name,
            "host": host.strip(),
            "port": int(port),
            "username": username.strip(),
            "root_path": posixpath.normpath(root_path or "/"),
            "credential": encrypt_credential(
                {"password": password or "", "private_key": private_key or ""}
            ),
            "created_at": datetime.now(UTC).isoformat(),
        }
        _save(doc)
    return {"source_id": source_id, "name": clean_name, "host": host.strip()}


def list_sources(owner_id: str) -> list[dict[str, Any]]:
    doc = _load()
    out = []
    for source_id, src in sorted(doc.get("sources", {}).items()):
        if not isinstance(src, dict) or src.get("owner_id") != owner_id:
            continue
        out.append({
            "source_id": source_id,
            "name": src.get("name"),
            "host": src.get("host"),
            "port": src.get("port"),
            "username": src.get("username"),
            "root_path": src.get("root_path"),
        })
    return out


def delete_source(owner_id: str, source_id: str) -> bool:
    with _lock:
        doc = _load()
        src = doc.get("sources", {}).get(source_id)
        if not isinstance(src, dict) or src.get("owner_id") != owner_id:
            return False
        del doc["sources"][source_id]
        _save(doc)
        return True


def _get_source(owner_id: str, source_id: str) -> dict[str, Any]:
    src = _load().get("sources", {}).get(source_id)
    if not isinstance(src, dict) or src.get("owner_id") != owner_id:
        raise HTTPException(status_code=404, detail="SFTP 源不存在")
    return src


def _resolve_remote(src: dict[str, Any], path: str) -> str:
    """远程路径约束：normpath 后必须落在 root_path 内。"""
    root = posixpath.normpath(str(src.get("root_path") or "/"))
    target = posixpath.normpath(posixpath.join(root, (path or "").lstrip("/")))
    if target != root and not target.startswith(root.rstrip("/") + "/"):
        raise HTTPException(status_code=400, detail="路径越出源的根目录")
    return target


def _open_client(src: dict[str, Any]):
    if _client_factory is not None:
        return _client_factory(src)
    import io as _io

    import paramiko  # 懒加载：未配置 SFTP 时永不 import

    cred = decrypt_credential(src.get("credential") or {})
    transport = paramiko.Transport((str(src["host"]), int(src["port"])))
    try:
        if cred.get("private_key"):
            pkey = paramiko.RSAKey.from_private_key(_io.StringIO(cred["private_key"]))
            transport.connect(username=str(src["username"]), pkey=pkey)
        else:
            transport.connect(username=str(src["username"]), password=cred.get("password", ""))
        transport.banner_timeout = _SFTP_TIMEOUT
        client = paramiko.SFTPClient.from_transport(transport)
        client.get_channel().settimeout(_SFTP_TIMEOUT)  # type: ignore[union-attr]
        return client
    except Exception:
        transport.close()
        raise


def browse(owner_id: str, source_id: str, path: str = "") -> dict[str, Any]:
    """列远程目录：返回受支持扩展名文件与子目录。"""
    src = _get_source(owner_id, source_id)
    target = _resolve_remote(src, path)
    client = _open_client(src)
    try:
        entries = client.listdir_attr(target)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"远程目录不存在: {target}")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SFTP 连接失败: {exc}")
    finally:
        try:
            client.close()
        except Exception:
            pass
    files, dirs = [], []
    import stat as _stat

    for entry in entries[:20000]:
        name = entry.filename
        if _stat.S_ISDIR(entry.st_mode or 0):
            dirs.append(name)
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in settings.ALLOWED_EXTENSIONS:
            files.append({"name": name, "size": int(entry.st_size or 0)})
    files.sort(key=lambda x: x["name"])
    dirs.sort()
    return {"path": target, "files": files, "dirs": dirs}


async def pull_files(
    owner_id: str,
    source_id: str,
    remote_names: list[str],
    *,
    path: str = "",
    job_id: str | None = None,
) -> dict[str, Any]:
    """拉取远程文件并登记。部分成功语义，登记链复用 process_upload。"""
    from app.core.file_validation import validate_magic_bytes
    from app.services.file_management_service import process_upload

    src = _get_source(owner_id, source_id)
    base = _resolve_remote(src, path)
    imported: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    client = _open_client(src)
    try:
        for name in remote_names[:200]:
            if "/" in name or "\\" in name or name in (".", ".."):
                failed.append({"name": name, "reason": "非法文件名"})
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in settings.ALLOWED_EXTENSIONS:
                failed.append({"name": name, "reason": f"不支持的类型 {ext}"})
                continue
            remote = posixpath.join(base, name)
            file_id = str(uuid.uuid4())
            tmp_dest = os.path.join(settings.UPLOAD_DIR, f".pulling_{file_id}{ext}")
            dest = os.path.join(settings.UPLOAD_DIR, f"{file_id}{ext}")
            try:
                client.get(remote, tmp_dest)
                size = os.path.getsize(tmp_dest)
                if size > settings.MAX_FILE_SIZE:
                    raise ValueError("文件过大")
                if not validate_magic_bytes(tmp_dest, ext):
                    raise ValueError(f"文件内容与扩展名 {ext} 不匹配")
                shutil.move(tmp_dest, dest)
                response, _jid = await process_upload(
                    file_path=dest,
                    file_ext=ext,
                    filename=name,
                    file_size=size,
                    batch_group_id=None,
                    job_id=job_id,
                    upload_source="batch" if job_id else None,
                    owner_id=owner_id,
                )
                imported.append({"name": name, "file_id": response.file_id})
            except Exception as exc:  # noqa: BLE001 — 单文件失败继续
                for leftover in (tmp_dest, dest):
                    if os.path.exists(leftover):
                        try:
                            os.remove(leftover)
                        except OSError:
                            pass
                failed.append({"name": name, "reason": str(exc)[:200] or "拉取失败"})
    finally:
        try:
            client.close()
        except Exception:
            pass
    return {"imported": imported, "failed": failed}
