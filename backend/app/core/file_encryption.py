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

    def encrypt_file(self, input_path: str, output_path: str) -> None:
        """加密文件（就地或指定输出路径）。"""
        if not self.enabled or self._key is None:
            # 未启用加密，直接拷贝
            if input_path != output_path:
                import shutil
                shutil.copy2(input_path, output_path)
            return

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)
        nonce = secrets.token_bytes(16)

        with open(input_path, "rb") as f:
            plaintext = f.read()

        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        with open(output_path, "wb") as f:
            f.write(nonce)
            f.write(ciphertext)

    def decrypt_file(self, input_path: str, output_path: str) -> None:
        """解密文件。"""
        if not self.enabled or self._key is None:
            if input_path != output_path:
                import shutil
                shutil.copy2(input_path, output_path)
            return

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)

        with open(input_path, "rb") as f:
            data = f.read()

        nonce = data[:16]
        ciphertext = data[16:]

        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        with open(output_path, "wb") as f:
            f.write(plaintext)

    def decrypt_to_bytes(self, input_path: str) -> bytes:
        """解密文件到内存。"""
        if not self.enabled or self._key is None:
            with open(input_path, "rb") as f:
                return f.read()

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._key)

        with open(input_path, "rb") as f:
            data = f.read()

        nonce = data[:16]
        ciphertext = data[16:]
        return aesgcm.decrypt(nonce, ciphertext, None)
