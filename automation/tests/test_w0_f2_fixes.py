from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wechat_automation.contracts import TaskStatus
from wechat_automation.demo.fixtures import _msg, happy_path_envelope
from wechat_automation.pipeline.ingest import ingest_events, ingest_webhook_batch
from wechat_automation.process_liveness import PidLiveness, check_pid_liveness
from wechat_automation.recovery import recover_interrupted_tasks
from wechat_automation.scheduler.worker import process_one_task, run_worker_once
from wechat_automation.source.backfill import run_backfill_window
from wechat_automation.source.chatlog_decoder import decode_chatlog_message, parse_webhook_batch
from wechat_automation.source.message_identity import INTERNAL_SIM_ID_FIELD, parse_chatlog_seq
from tests.conftest import CONFIG_PATH
from tests.test_helpers import StrictChatlogStubTransport
from tests.support import force_task_status_for_test
from wechat_automation.store.sqlite_store import SQLiteStore


def test_f2_liveness_current_process_alive() -> None:
    assert check_pid_liveness(os.getpid()) == PidLiveness.ALIVE


def test_f2_seq_strict_types() -> None:
    assert parse_chatlog_seq(True)[0] is None
    assert parse_chatlog_seq(1.9)[0] is None
    assert parse_chatlog_seq("12")[0] is None


def test_f2_seq_conflict_recorded(cfg, store: SQLiteStore) -> None:
    ts = "2026-09-28T08:00:05+00:00"
    body = {
        "length": 2,
        "messages": [
            _msg(seq=202609280777001, talker="wxid_test_peer_a", sender="a", content="help A", time_iso=ts),
            _msg(seq=202609280777001, talker="wxid_test_peer_a", sender="b", content="help B", time_iso=ts),
        ],
    }
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["new_events"] == 1
    assert stats.get("identity_conflicts", 0) == 1


def test_f2_webhook_rejects_internal_sim_id(cfg, store: SQLiteStore) -> None:
    body = happy_path_envelope()
    body["messages"][0][INTERNAL_SIM_ID_FIELD] = "injected"
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["tasks_created"] == 0


def test_f2_r1_recovery_cas_no_clobber(cfg, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    dead_pid = 999999
    store.claim_next_pending_task("worker-A", cfg.lock_ttl_seconds, owner_pid=dead_pid)
    stale = store.get_running_snapshot(1)
    assert stale
    recover_interrupted_tasks(store)
    store.claim_next_pending_task("worker-B", cfg.lock_ttl_seconds, owner_pid=os.getpid())
    store.mark_execution_started(1, "worker-B", os.getpid(), 1)
    outcome = store.recover_running_task_cas(
        task_id=1,
        expected_claim_token=str(stale["claim_token"]),
        expected_owner_worker_id=str(stale["owner_worker_id"]),
        expected_owner_pid=int(stale["owner_pid"]),
        mark_unknown=True,
    )
    assert outcome == "cas_conflict"
    snap = store.get_running_snapshot(1)
    assert snap is not None
    assert snap["owner_worker_id"] == "worker-B"
    assert snap["execution_phase"] == "started"


def test_f2_r3_executor_exception_unknown(cfg, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    body2 = happy_path_envelope()
    body2["messages"][0]["seq"] = 202609280888001
    ingest_webhook_batch(cfg, store, parse_webhook_batch(body2))
    cfg.mock_executor = {
        "default_outcome": "raise_exception",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    outcome = process_one_task(cfg, store)
    assert outcome.kind.value in ("executor_error", "processed")
    assert store.count_tasks_by_status(TaskStatus.UNKNOWN) >= 1
    cfg.mock_executor = {"default_outcome": "success", "target_map": {"wxid_test_peer_a": "mock-target-a"}}
    run_worker_once(cfg, store, max_tasks=5)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) >= 1


def test_f2_two_round_late_backfill(cfg, store: SQLiteStore, tmp_path: Path) -> None:
    msg1 = happy_path_envelope()["messages"][0]
    ts = "2026-09-28T08:00:05+00:00"
    msg2 = _msg(seq=202609280555002, talker="wxid_test_peer_a", sender="u", content="help late", time_iso=ts)
    transport1 = StrictChatlogStubTransport(
        {0: [msg1]},
        expect_talker="wxid_test_peer_a",
        expect_limit=2,
    )
    start = datetime(2026, 9, 28, 8, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, 8, 0, 10, tzinfo=timezone.utc)

    def ingest_fn(evts):
        return ingest_events(cfg, store, evts)

    run_backfill_window(
        cfg, store, ingest_fn, "http://stub", "wxid_test_peer_a", start, end, transport=transport1
    )
    transport2 = StrictChatlogStubTransport(
        {0: [msg2]},
        expect_talker="wxid_test_peer_a",
        expect_limit=2,
    )
    run_backfill_window(
        cfg, store, ingest_fn, "http://stub", "wxid_test_peer_a", start, end, transport=transport2
    )
    assert store.count_events() >= 2


def test_f2_peak_active_one(cfg, store: SQLiteStore) -> None:
    """Single-process sequential run (not cross-process concurrency evidence)."""
    body = happy_path_envelope()
    body["length"] = 2
    body["messages"].append(
        _msg(seq=202609280666001, talker="wxid_test_peer_a", sender="u", content="help")
    )
    ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    run_worker_once(cfg, store, max_tasks=2)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 2
