from __future__ import annotations

from app.core.config import BACKEND_DIR, Settings


def test_settings_resolve_repo_local_paths_from_backend_dir(monkeypatch) -> None:
    monkeypatch.setenv("DEBUG", "release")
    monkeypatch.setenv("DATA_DIR", "./data")
    monkeypatch.setenv("UPLOAD_DIR", "./uploads")
    monkeypatch.setenv("OUTPUT_DIR", "./outputs")

    settings = Settings()

    assert settings.DEBUG is False
    assert settings.DATA_DIR == str((BACKEND_DIR / "data").resolve())
    assert settings.UPLOAD_DIR == str((BACKEND_DIR / "uploads").resolve())
    assert settings.OUTPUT_DIR == str((BACKEND_DIR / "outputs").resolve())
    assert settings.JOB_DB_PATH == str((BACKEND_DIR / "data" / "jobs.sqlite3").resolve())
