"""Minimal stub so transformers remote-code import checks pass.

LocateAnything processor imports decord at module import time for video paths.
This deployment only serves still images on Ascend; video is unsupported.
"""


class bridge:
    @staticmethod
    def set_bridge(_name: str) -> None:
        return None


class VideoReader:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "decord stub: video input is not supported in this Ascend image-only deployment"
        )
