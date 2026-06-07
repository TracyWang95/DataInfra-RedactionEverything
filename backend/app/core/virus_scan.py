"""
病毒扫描集成 — ClamAV（clamd）接口。

策略：
- 上传文件后、解析前扫描
- ClamAV 不可用时降级为仅告警（不阻塞上传）
- 发现病毒时拒绝文件并删除

需要安装：pip install pyclamd
ClamAV daemon 需单独部署（clamd 监听 TCP 3310 或 Unix socket）。
"""
import logging
import os

logger = logging.getLogger(__name__)

# ClamAV 连接配置
CLAMD_HOST = os.environ.get("CLAMD_HOST", "127.0.0.1")
CLAMD_PORT = int(os.environ.get("CLAMD_PORT", "3310"))
CLAMD_TIMEOUT = int(os.environ.get("CLAMD_TIMEOUT", "30"))


class ScanResult:
    """病毒扫描结果"""
    def __init__(self, clean: bool, virus_name: str | None = None, error: str | None = None):
        self.clean = clean
        self.virus_name = virus_name
        self.error = error  # 扫描器不可用时的错误信息

    @property
    def available(self) -> bool:
        """扫描器是否可用（error 为 None 表示可用）"""
        return self.error is None


def _get_clamd():
    """获取 ClamAV 客户端（延迟导入，不可用时返回 None）"""
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=CLAMD_HOST, port=CLAMD_PORT, timeout=CLAMD_TIMEOUT)
        if cd.ping():
            return cd
    except ImportError:
        logger.debug("pyclamd not installed, virus scanning disabled")
    except Exception as e:
        logger.debug("ClamAV connection failed: %s", e)
    return None


def scan_file(file_path: str) -> ScanResult:
    """
    扫描文件是否包含病毒。

    返回 ScanResult:
    - clean=True, error=None → 文件安全
    - clean=False, virus_name=... → 发现病毒
    - clean=True, error=... → 扫描器不可用（降级放行+告警）
    """
    cd = _get_clamd()
    if cd is None:
        return ScanResult(clean=True, error="ClamAV not available, scan skipped")

    try:
        result = cd.scan_file(os.path.abspath(file_path))
        if result is None:
            return ScanResult(clean=True)

        # result 格式：{'/path/to/file': ('FOUND', 'VirusName')}
        for _path, (status, virus) in result.items():
            if status == "FOUND":
                logger.warning("VIRUS DETECTED in %s: %s", file_path, virus)
                return ScanResult(clean=False, virus_name=virus)

        return ScanResult(clean=True)
    except Exception as e:
        logger.warning("Virus scan error for %s: %s (degraded: allowing file)", file_path, e)
        return ScanResult(clean=True, error=str(e))


def is_available() -> bool:
    """检查 ClamAV 是否可用"""
    return _get_clamd() is not None
