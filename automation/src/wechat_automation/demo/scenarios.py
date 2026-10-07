from __future__ import annotations

import json
from pathlib import Path

from wechat_automation.config import AppConfig, ensure_runtime_dirs, load_config
from wechat_automation.demo.fixtures import happy_path_envelope, write_fixture
from wechat_automation.pipeline.ingest import ingest_webhook_batch
from wechat_automation.runtime_paths import allocate_run_dir, write_latest_pointer
from wechat_automation.scheduler.worker import run_worker_once
from wechat_automation.source.fixture_source import load_webhook_fixture
from wechat_automation.store.sqlite_store import SQLiteStore


def run_happy_path(config_path: Path) -> dict:
    cfg = load_config(config_path)
    ensure_runtime_dirs(cfg)
    run_id, run_dir = allocate_run_dir(cfg.runtime_dir, prefix="demo-happy")
    demo_db = run_dir / "happy_path.db"
    store = SQLiteStore(demo_db)
    fixture = run_dir / "input.json"
    write_fixture(fixture, happy_path_envelope())
    envelope = load_webhook_fixture(fixture)
    ingest_stats = ingest_webhook_batch(cfg, store, envelope)
    processed = run_worker_once(cfg, store, max_tasks=10)
    summary = store.status_summary()
    result = {
        "run_id": run_id,
        "ingest": ingest_stats,
        "worker_processed": processed,
        "summary": summary,
        "simulation": True,
        "database": str(demo_db),
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_latest_pointer(cfg.runtime_dir, "demo_happy_path", run_id, run_dir)
    return result
