from __future__ import annotations

import json
import multiprocessing
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from wechat_automation.config import AppConfig, KeywordRule, load_config
from wechat_automation.contracts import TaskStatus
from wechat_automation.demo.fixtures import (
    duplicate_event_envelope,
    filtered_messages_envelope,
    happy_path_envelope,
    patch_unknown_self,
    same_content_different_ids_envelope,
    self_message_loop_envelope,
    _msg,
)
from wechat_automation.executor.mock import MockExecutor, MockExecutorConfig
from wechat_automation.pipeline.ingest import ingest_events, ingest_webhook_batch
from wechat_automation.scheduler.worker import process_one_task, run_worker_once
from wechat_automation.source.backfill import run_backfill_window
from tests.test_helpers import StrictChatlogStubTransport
from wechat_automation.source.chatlog_decoder import (
    decode_chatlog_message,
    parse_webhook_batch,
)
from wechat_automation.source.fixture_source import load_webhook_fixture
from wechat_automation.store.sqlite_store import SQLiteStore
from wechat_automation.webhook.receiver import LocalWebhookServer


from tests.conftest import CONFIG_PATH

VALIDATION = Path(__file__).resolve().parents[1] / ".local-validation"


def _envelope(body: dict) -> Any:
    return parse_webhook_batch(body)


def test_01_single_message_happy_path(cfg: AppConfig, store: SQLiteStore) -> None:
    stats = ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    assert stats["tasks_created"] == 1
    run_worker_once(cfg, store, max_tasks=5)
    assert store.count_tasks() == 1
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1


def test_02_duplicate_event_single_task(cfg: AppConfig, store: SQLiteStore) -> None:
    env = _envelope(happy_path_envelope())
    ingest_webhook_batch(cfg, store, env)
    ingest_webhook_batch(cfg, store, _envelope(duplicate_event_envelope()))
    assert store.count_tasks() == 1


def test_03_same_content_different_ids(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(same_content_different_ids_envelope()))
    assert store.count_tasks() == 2


def test_04_replay_after_success_no_reexecute(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    run_worker_once(cfg, store)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    run_worker_once(cfg, store)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1
    assert store.count_tasks_by_status(TaskStatus.PENDING) == 0


def test_05_self_message_no_loop(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(self_message_loop_envelope()))
    assert store.count_tasks() == 0


def test_06_filtered_cases(cfg: AppConfig, store: SQLiteStore) -> None:
    body = filtered_messages_envelope()
    patch_unknown_self(body)
    ingest_webhook_batch(cfg, store, _envelope(body))
    assert store.count_tasks() == 0
    summary = store.status_summary()
    assert summary["decisions_by_outcome"].get("IGNORED", 0) >= 4


def test_07_ambiguous_target_blocks(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    cfg.mock_executor = {
        "default_outcome": "ambiguous_name",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    run_worker_once(cfg, store)
    assert store.count_tasks_by_status(TaskStatus.FAILED) == 1


def _worker_proc(db_path: str, config_path: str, out_q: multiprocessing.Queue) -> None:
    c = load_config(Path(config_path))
    s = SQLiteStore(Path(db_path))
    n = 0
    for _ in range(20):
        if process_one_task(c, s).counts_as_processed:
            n += 1
    out_q.put(n)


def test_08_two_workers_mutex(cfg: AppConfig, tmp_path: Path) -> None:
    db = tmp_path / "mutex.db"
    store = SQLiteStore(db)
    ingest_webhook_batch(cfg, store, _envelope(same_content_different_ids_envelope()))
    q: multiprocessing.Queue = multiprocessing.Queue()
    p1 = multiprocessing.Process(target=_worker_proc, args=(str(db), str(CONFIG_PATH), q))
    p2 = multiprocessing.Process(target=_worker_proc, args=(str(db), str(CONFIG_PATH), q))
    p1.start()
    p2.start()
    p1.join(timeout=30)
    p2.join(timeout=30)
    results = [q.get(timeout=5), q.get(timeout=5)]
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 2
    assert store.count_tasks_by_status(TaskStatus.RUNNING) == 0
    assert sum(results) >= 2


def test_09_transient_retry(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    cfg.mock_executor = {
        "default_outcome": "transient",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    run_worker_once(cfg, store, max_tasks=5)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1


def test_10_unknown_no_resend(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    cfg.mock_executor = {
        "default_outcome": "unknown_after_start",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    run_worker_once(cfg, store, max_tasks=3)
    assert store.count_tasks_by_status(TaskStatus.UNKNOWN) == 1
    run_worker_once(cfg, store, max_tasks=3)
    assert store.count_tasks_by_status(TaskStatus.UNKNOWN) == 1


def test_11_transaction_rollback(cfg: AppConfig, tmp_path: Path) -> None:
    db = tmp_path / "tx.db"
    store = SQLiteStore(db)
    env = _envelope(happy_path_envelope())
    events = [
        decode_chatlog_message(
            cfg.account_id,
            env.messages[0],
            datetime.now(timezone.utc),
        )
    ]

    original = store.insert_event_if_new

    def boom(conn, event):  # type: ignore[no-untyped-def]
        original(conn, event)
        raise RuntimeError("simulate mid-tx failure")

    with patch.object(store, "insert_event_if_new", side_effect=boom):
        with pytest.raises(RuntimeError):
            ingest_events(cfg, store, events)
    assert store.count_events() == 0
    assert store.count_tasks() == 0


def test_12_backfill_dedupe_with_webhook(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    pages = {
        0: [
            happy_path_envelope()["messages"][0],
        ],
        1: [],
    }

    transport = StrictChatlogStubTransport({0: pages[0], 1: pages[1]})

    def ingest_fn(evts):  # type: ignore[no-untyped-def]
        from wechat_automation.pipeline.ingest import ingest_events as ie

        return ie(cfg, store, evts)

    start = datetime(2026, 9, 28, tzinfo=timezone.utc)
    end = datetime(2026, 9, 29, tzinfo=timezone.utc)
    result = run_backfill_window(
        cfg,
        store,
        ingest_fn,
        "http://stub.local",
        "wxid_test_peer_a",
        start,
        end,
        transport=transport,
    )
    assert result.pages_failed == 0
    assert store.count_tasks() == 1
    assert "~" in transport.requests[0]["time"]


def test_13_pagination_boundaries(cfg: AppConfig, store: SQLiteStore) -> None:
    msgs = [
            _msg(
                seq=20260928100001 + i,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content="help",
                time_iso=f"2026-09-28T08:00:{i:02d}+00:00",
            )
        for i in range(5)
    ]

    transport = StrictChatlogStubTransport(
        {0: msgs[:2], 2: msgs[2:4], 4: msgs[4:]}
    )
    cfg.backfill["page_size"] = 2

    def ingest_fn(evts):  # type: ignore[no-untyped-def]
        from wechat_automation.pipeline.ingest import ingest_events as ie

        return ie(cfg, store, evts)

    result = run_backfill_window(
        cfg,
        store,
        ingest_fn,
        "http://stub.local",
        "wxid_test_peer_a",
        datetime(2026, 9, 28, tzinfo=timezone.utc),
        datetime(2026, 9, 29, tzinfo=timezone.utc),
        transport=transport,
    )
    assert result.pages_failed == 0
    assert result.checkpoint_advanced is True
    assert store.count_tasks() == 5


def test_14_invalid_json_isolated(cfg: AppConfig, store: SQLiteStore) -> None:
    received = []

    def handler(body: dict) -> dict:
        try:
            stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
            received.append(stats)
            return {"accepted": True, "stats": stats, "simulation": True}
        except Exception as exc:  # noqa: BLE001
            store.record_rejection("handler_error", str(exc))
            return {"accepted": False, "reason": str(exc)}

    server = LocalWebhookServer(handler)
    server.start()
    try:
        import urllib.request

        bad = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/",
            data=b"{not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(Exception):
            urllib.request.urlopen(bad, timeout=5)
        good_body = json.dumps(happy_path_envelope()).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/",
            data=good_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
    finally:
        server.stop()
    assert store.count_tasks() == 1


def test_15_live_mode_rejected(tmp_path: Path) -> None:
    live = tmp_path / "live.json"
    live.write_text(
        json.dumps(
            {
                "mode": "live",
                "account_id": "x",
                "rule_version": "v1",
                "allowed_conversation_ids": ["a"],
                "keyword_rules": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_config(live)


def test_16_simulation_flags(cfg: AppConfig, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, _envelope(happy_path_envelope()))
    run_worker_once(cfg, store)
    ex = MockExecutor(MockExecutorConfig.from_dict(cfg.mock_executor))
    task = store.get_task(1)
    assert task is not None
    result = ex.execute(task)
    assert result.simulation is True
    assert result.status == TaskStatus.SIMULATED_SUCCEEDED
