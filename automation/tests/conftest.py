from __future__ import annotations

from pathlib import Path

import pytest

from wechat_automation.config import AppConfig, load_config
from wechat_automation.store.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "offline.example.json"


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(CONFIG_PATH)


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "test.db")


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "win32_only: test requires Windows (excluded from Linux gate required set)",
    )
