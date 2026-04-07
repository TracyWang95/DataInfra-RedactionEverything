# Copyright 2026 DataInfra-RedactionEverything Contributors
# SPDX-License-Identifier: Apache-2.0

"""
文件加密存储 — AES-256-GCM 对上传文件加密落盘。

密钥管理：
- 首次启动自动生成 256 位密钥，持久化到 data/encryption_key.json
- 密钥文件权限 600（仅属主可读）
- 可通过环境变量 FILE_ENCRYPTION_KEY 覆盖

加密格式：
- [16 bytes nonce] + [N bytes ciphertext] + [16 bytes tag]
"""
import json
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

_KEY_LENGTH = 32  # AES-256


def _load_or_create_key(data_dir: str) -> bytes:
    """加载或生成文件加密密钥。"""
    # 环境变量优先
    env_key = os.environ.get("FILE_ENCRYPTION_KEY", "").strip()
    if env_key:
        key = bytes.fromhex(env_key)
        if len(key) == _KEY_LENGTH:
            return key
        logger.warning("FILE_ENCRYPTION_KEY 长度不正确 (%d bytes)，使用持久化密钥", len(key))

    key_path = os.path.join(data_dir, "encryption_key.json")
    if os.path.exists(key_path):
        try:
            with open(key_path, "r") as f:
                hex_key = json.load(f).get("key", "")
            key = bytes.fromhex(hex_key)
            if len(key) == _KEY_LENGTH:
                return key
        except Exception:
            logger.warning("加密密钥文件损坏，重新生成")

    # 生成新密钥
    key = secrets.token_bytes(_KEY_LENGTH)
    os.makedirs(data_dir, exist_ok=True)
    with open(key_path, "w") as f:
        json.dump({"key": key.hex()}, f)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass  # Windows
    logger.info("Generated new file encryption key: %s", key_path)
    return key


class FileEncryptor:
    """AES-256-GCM 文件加密/解密。"""

    def __init__(self, data_dir: str, enabled: bool = False):
        self.enabled = enabled
        self._key: Optional[bytes] = None
        self._data_dir = data_dir
        if enabled:
            self._key = _load_or_create_key(data_dir)

    # Chunked encryption format (v2):
    #   [8 bytes magic "ENCV2\x00\x00\x00"] + [4 bytes chunk_size BE uint32]
    #   + for each chunk: [16 bytes nonce] + [AESGCM(plaintext_chunk)]
    # Legacy format (v1): [16 bytes nonce] + [AESGCM(entire_file)]

    _MAGIC = b"ENCV2\x00\x00\x00"
    _CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

    def encrypt_file(self, input_path: str, output_path: str) -> None:
        """加密文件（流式分块，内存占用 ≤ chunk_size + overhead）。"""
        if not self.enabled or self._key is None:
            if input_path != output_path:
                import shutil
                shutil.copy2(input_path, output_path)
            return

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)

        with open(input_path, "rb") as fin, open(output_path, "wb") as fout:
            fout.write(self._MAGIC)
            fout.write(self._CHUNK_SIZE.to_bytes(4, "big"))

            while True:
                chunk = fin.read(self._CHUNK_SIZE)
                if not chunk:
                    break
                nonce = secrets.token_bytes(16)
                ct = aesgcm.encrypt(nonce, chunk, None)
                fout.write(nonce)
                fout.write(len(ct).to_bytes(4, "big"))
                fout.write(ct)

    def _is_v2(self, f) -> bool:
        """Check if file uses chunked v2 format."""
        header = f.read(len(self._MAGIC))
        if header == self._MAGIC:
            return True
        f.seek(0)
        return False

    def decrypt_file(self, input_path: str, output_path: str) -> None:
        """解密文件（自动识别 v1/v2 格式）。"""
        if not self.enabled or self._key is None:
            if input_path != output_path:
                import shutil
                shutil.copy2(input_path, output_path)
            return

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)

        with open(input_path, "rb") as fin:
            if self._is_v2(fin):
                fin.read(4)  # skip chunk_size header
                with open(output_path, "wb") as fout:
                    while True:
                        nonce = fin.read(16)
                        if not nonce:
                            break
                        ct_len = int.from_bytes(fin.read(4), "big")
                        ct = fin.read(ct_len)
                        fout.write(aesgcm.decrypt(nonce, ct, None))
            else:
                # Legacy v1 format
                data = fin.read()
                nonce = data[:16]
                ciphertext = data[16:]
                with open(output_path, "wb") as fout:
                    fout.write(aesgcm.decrypt(nonce, ciphertext, None))

    def decrypt_to_bytes(self, input_path: str) -> bytes:
        """解密文件到内存。"""
        if not self.enabled or self._key is None:
            with open(input_path, "rb") as f:
                return f.read()

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)

        with open(input_path, "rb") as fin:
            if self._is_v2(fin):
                fin.read(4)  # skip chunk_size header
                parts: list[bytes] = []
                while True:
                    nonce = fin.read(16)
                    if not nonce:
                        break
                    ct_len = int.from_bytes(fin.read(4), "big")
                    ct = fin.read(ct_len)
                    parts.append(aesgcm.decrypt(nonce, ct, None))
                return b"".join(parts)
            else:
                # Legacy v1 format
                data = fin.read()
                nonce = data[:16]
                ciphertext = data[16:]
                return aesgcm.decrypt(nonce, ciphertext, None)
