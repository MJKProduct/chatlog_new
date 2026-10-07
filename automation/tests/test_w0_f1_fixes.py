from __future__ import annotations

import multiprocessing
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wechat_automation.config import load_config
from wechat_automation.contracts import TaskStatus
from wechat_automation.demo.fixtures import _msg, happy_path_envelope
from wechat_automation.pipeline.ingest import ingest_events, ingest_webhook_batch
from wechat_automation.recovery import recover_interrupted_tasks
from wechat_automation.scheduler.worker import process_one_task, run_worker_once
from wechat_automation.source.backfill import (
    BackfillConfigError,
    format_go_time_range,
    run_backfill_window,
)
from wechat_automation.source.chatlog_decoder import decode_chatlog_message, parse_webhook_batch
from tests.test_helpers import StrictChatlogStubTransport
from wechat_automation.store.sqlite_store import SQLiteStore


from tests.conftest import CONFIG_PATH


def _ingest_fn(cfg, store):
    def fn(evts):
        return ingest_events(cfg, store, evts)

    return fn


def test_f2_no_seq_no_task(cfg, store: SQLiteStore) -> None:
    body = happy_path_envelope()
    body["messages"][0].pop("seq", None)
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["tasks_created"] == 0


def test_f2_invalid_seq_zero_collapses(cfg, store: SQLiteStore) -> None:
    body = {
        "talker": "wxid_test_peer_a",
        "messages": [
            _msg(seq=0, talker="wxid_test_peer_a", sender="a", content="help"),
            _msg(seq=0, talker="wxid_test_peer_a", sender="b", content="help2"),
        ],
        "length": 2,
    }
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["new_events"] == 2
    assert stats["tasks_created"] == 0


def test_f2_go_faithful_seq_creates_task(cfg, store: SQLiteStore) -> None:
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    assert stats["tasks_created"] == 1


def test_f2_isself_must_be_bool(cfg, store: SQLiteStore) -> None:
    body = happy_path_envelope()
    body["messages"][0]["isSelf"] = "false"
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["tasks_created"] == 0


def test_f3_time_range_uses_tilde() -> None:
    start = datetime(2026, 9, 28, 8, 0, 5, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, 8, 0, 10, tzinfo=timezone.utc)
    tr = format_go_time_range(start, end)
    assert "~" in tr
    assert "2026-09-28T08:00:05" in tr


def test_f3_stub_rejects_slash_date_range(cfg, store: SQLiteStore) -> None:
    transport = StrictChatlogStubTransport({0: []})

    class BadTransport:
        def get_json(self, url: str):
            return 200, []

    # Force bad URL in test by calling stub validator indirectly
    q = transport
    status, _ = q.get_json(
        "http://stub/api/v1/chatlog?format=json&talker=a&time=2026-09-20/2026-09-28&limit=2&offset=0"
    )
    assert status == 400


def test_f4_checkpoint_isolated_per_talker(cfg, store: SQLiteStore) -> None:
    msg_a = happy_path_envelope()["messages"][0]
    transport_a = StrictChatlogStubTransport({0: [msg_a], 2: []})
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, tzinfo=timezone.utc)
    run_backfill_window(
        cfg,
        store,
        _ingest_fn(cfg, store),
        "http://stub.local",
        "wxid_test_peer_a",
        start,
        end,
        transport=transport_a,
    )
    transport_b = StrictChatlogStubTransport({0: [msg_a]})
    result_b = run_backfill_window(
        cfg,
        store,
        _ingest_fn(cfg, store),
        "http://stub.local",
        "wxid_other_b",
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 5, tzinfo=timezone.utc),
        transport=transport_b,
    )
    assert "~" in transport_b.requests[0]["time"]
    assert "2026-09-01" in transport_b.requests[0]["time"]


def test_f6_rejects_simulation_false(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    raw = CONFIG_PATH.read_text(encoding="utf-8").replace('"simulation": true', '"simulation": false')
    bad.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(bad)


def test_f6_backfill_requires_transport(cfg, store: SQLiteStore) -> None:
    with pytest.raises(BackfillConfigError):
        run_backfill_window(
            cfg,
            store,
            _ingest_fn(cfg, store),
            "http://x",
            "t",
            datetime(2026, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 9, 2, tzinfo=timezone.utc),
            transport=None,  # type: ignore[arg-type]
        )


def _claim_only_worker(db_path: str, config_path: str) -> None:
    cfg = load_config(Path(config_path))
    store = SQLiteStore(Path(db_path))
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    wid = "crash-claim-worker"
    task = store.claim_next_pending_task(wid, cfg.lock_ttl_seconds, owner_pid=os.getpid())
    assert task is not None
    os._exit(23)


def test_f1_recover_claimed_not_started(cfg, tmp_path: Path) -> None:
    db = tmp_path / "recover_claim.db"
    p = multiprocessing.Process(target=_claim_only_worker, args=(str(db), str(CONFIG_PATH)))
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 23
    store = SQLiteStore(db)
    stats = recover_interrupted_tasks(store)
    assert stats["recovered_pending"] == 1
    assert store.count_tasks_by_status(TaskStatus.PENDING) == 1


def _crash_after_side_effect_worker(db_path: str, config_path: str, marker: str) -> None:
    os.environ["W0_SIM_SIDE_EFFECT_MARKER"] = marker
    cfg = load_config(Path(config_path))
    cfg.mock_executor = {
        "default_outcome": "crash_after_side_effect",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    store = SQLiteStore(Path(db_path))
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    process_one_task(cfg, store)


def test_f1_recover_unknown_after_side_effect(cfg, tmp_path: Path) -> None:
    db = tmp_path / "recover_unknown.db"
    marker = tmp_path / "side_effect.marker"
    p = multiprocessing.Process(
        target=_crash_after_side_effect_worker,
        args=(str(db), str(CONFIG_PATH), str(marker)),
    )
    p.start()
    p.join(timeout=30)
    assert p.exitcode == 23
    assert marker.read_text(encoding="utf-8").startswith("simulated_side_effect")
    store = SQLiteStore(db)
    stats = recover_interrupted_tasks(store)
    assert stats["marked_unknown"] == 1
    assert store.count_tasks_by_status(TaskStatus.UNKNOWN) == 1


def test_f1_queue_continues_after_unknown(cfg, tmp_path: Path) -> None:
    db = tmp_path / "queue.db"
    store = SQLiteStore(db)
    body = happy_path_envelope()
    body["length"] = 2
    body["messages"].append(
        _msg(seq=202609280099001, talker="wxid_test_peer_a", sender="u", content="help")
    )
    ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    from tests.support import force_task_status_for_test

    force_task_status_for_test(store, 1, TaskStatus.UNKNOWN)
    run_worker_once(cfg, store, max_tasks=5)
    assert store.count_tasks_by_status(TaskStatus.UNKNOWN) == 1
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1


def test_f3_pagination_failure_keeps_checkpoint(cfg, store: SQLiteStore) -> None:
    msg = happy_path_envelope()["messages"][0]
    msg2 = _msg(seq=20260928100099, talker="wxid_test_peer_a", sender="u", content="help")
    transport = StrictChatlogStubTransport({0: [msg, msg2]}, fail_offsets={1})
    cfg.backfill["page_size"] = 1
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, tzinfo=timezone.utc)
    result = run_backfill_window(
        cfg,
        store,
        _ingest_fn(cfg, store),
        "http://stub.local",
        "wxid_test_peer_a",
        start,
        end,
        transport=transport,
    )
    assert result.pages_failed == 1
    assert result.checkpoint_advanced is False


def test_f2_same_second_different_seq(cfg, store: SQLiteStore) -> None:
    ts = "2026-09-28T08:00:05+00:00"
    body = {
        "talker": "wxid_test_peer_a",
        "length": 2,
        "messages": [
            _msg(seq=202609280050001, talker="wxid_test_peer_a", sender="a", content="help", time_iso=ts),
            _msg(seq=202609280050002, talker="wxid_test_peer_a", sender="b", content="help", time_iso=ts),
        ],
    }
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["tasks_created"] == 2
