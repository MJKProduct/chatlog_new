from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from wechat_automation.contracts import TaskStatus
from wechat_automation.demo.fixtures import _msg, happy_path_envelope
from wechat_automation.executor.mock import MockExecutor, MockExecutorConfig
from wechat_automation.pipeline.ingest import ingest_webhook_batch
from wechat_automation.process_liveness import PidLiveness, check_pid_liveness
from wechat_automation.scheduler.worker import process_one_task, run_worker_once
from wechat_automation.source.chatlog_decoder import decode_chatlog_message, parse_webhook_batch
from wechat_automation.source.message_identity import semantic_fingerprint
from wechat_automation.store.sqlite_store import SQLiteStore
from tests.conftest import CONFIG_PATH


def _exec_calls(cfg, store: SQLiteStore) -> int:
    before = store.connect().execute("SELECT COUNT(*) c FROM attempts WHERE phase='execution_finished'").fetchone()["c"]
    run_worker_once(cfg, store, max_tasks=5)
    after = store.connect().execute("SELECT COUNT(*) c FROM attempts WHERE phase='execution_finished'").fetchone()["c"]
    return int(after) - int(before)


def test_f3_same_batch_conflict_blocks_executor(cfg, store: SQLiteStore) -> None:
    ts = "2026-09-28T08:00:05+00:00"
    body = {
        "length": 2,
        "messages": [
            _msg(seq=202609280777001, talker="wxid_test_peer_a", sender="a", content="help A", time_iso=ts),
            _msg(seq=202609280777001, talker="wxid_test_peer_a", sender="b", content="help B", time_iso=ts),
        ],
    }
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    assert stats["identity_conflicts"] == 1
    assert store.count_tasks_by_status(TaskStatus.CANCELLED) >= 1
    assert _exec_calls(cfg, store) == 0


def test_f3_late_conflict_cancels_pending(cfg, store: SQLiteStore) -> None:
    ts = "2026-09-28T08:00:05+00:00"
    first = _msg(seq=202609280888001, talker="wxid_test_peer_a", sender="a", content="help", time_iso=ts)
    ingest_webhook_batch(cfg, store, parse_webhook_batch({"length": 1, "messages": [first]}))
    assert store.count_tasks_by_status(TaskStatus.PENDING) == 1
    second = _msg(seq=202609280888001, talker="wxid_test_peer_a", sender="b", content="other", time_iso=ts)
    stats = ingest_webhook_batch(cfg, store, parse_webhook_batch({"length": 1, "messages": [second]}))
    assert stats["identity_conflicts"] == 1
    assert store.count_tasks_by_status(TaskStatus.PENDING) == 0
    assert store.count_tasks_by_status(TaskStatus.CANCELLED) == 1
    assert _exec_calls(cfg, store) == 0


def test_f3_field_validation_blocks_task_creation(cfg, store: SQLiteStore) -> None:
    base = happy_path_envelope()["messages"][0].copy()
    cases = [
        {**base, "sender": None},
        {k: v for k, v in base.items() if k != "sender"},
        {**base, "type": 1.9},
        {**base, "type": "1"},
        {**base, "content": 123},
    ]
    for i, msg in enumerate(cases):
        s = SQLiteStore(store.db_path.parent / f"val_{i}.db")
        stats = ingest_webhook_batch(cfg, s, parse_webhook_batch({"length": 1, "messages": [msg]}))
        assert stats["tasks_created"] == 0


def test_f3_isself_affects_fingerprint_not_display_fields(cfg) -> None:
    msg = happy_path_envelope()["messages"][0]
    fp1 = semantic_fingerprint(msg, "acct", "wxid_test_peer_a", msg["seq"], is_self=False)
    fp2 = semantic_fingerprint({**msg, "isSelf": True}, "acct", "wxid_test_peer_a", msg["seq"], is_self=True)
    fp3 = semantic_fingerprint({**msg, "host": "ignored"}, "acct", "wxid_test_peer_a", msg["seq"], is_self=False)
    assert fp1 != fp2
    assert fp1 == fp3


def test_f3_liveness_dead_child_process() -> None:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert check_pid_liveness(proc.pid) == PidLiveness.DEAD


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OpenProcess / _kernel32 inject only")
def test_f3_liveness_openprocess_access_denied_unknown() -> None:
    import ctypes

    import wechat_automation.process_liveness as pl

    class FakeK32:
        def OpenProcess(self, *_a, **_k):
            ctypes.set_last_error(5)
            return None

        def CloseHandle(self, *_a, **_k):
            return True

    with patch.object(pl, "_kernel32", FakeK32()):
        assert check_pid_liveness(os.getpid()) == PidLiveness.UNKNOWN


def test_f3_pid_instance_mismatch_unknown(cfg, store: SQLiteStore) -> None:
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    store.claim_next_pending_task("w", cfg.lock_ttl_seconds, owner_pid=os.getpid())
    snap = store.get_running_snapshot(1)
    assert snap
    with patch(
        "wechat_automation.store.sqlite_store.check_pid_liveness",
        return_value=PidLiveness.UNKNOWN,
    ):
        claimed = store.claim_next_pending_task("w2", cfg.lock_ttl_seconds, owner_pid=os.getpid())
    assert claimed is None


def _concurrent_worker(
    db_path: str,
    config_path: str,
    role: str,
    sync_file: str,
    state,
    barrier_task_id: int,
    out_q,
) -> None:  # type: ignore[no-untyped-def]
    from tests import concurrency_probe

    concurrency_probe.bind(state)
    os.environ["W0_CONCURRENCY_PROBE"] = "tests.concurrency_probe"
    if role == "hold":
        os.environ["W0_BARRIER_SYNC_FILE"] = sync_file
        os.environ["W0_BARRIER_TASK_ID"] = str(barrier_task_id)
    else:
        os.environ.pop("W0_BARRIER_SYNC_FILE", None)
        os.environ.pop("W0_BARRIER_TASK_ID", None)
    from pathlib import Path

    from wechat_automation.config import load_config
    from wechat_automation.scheduler.worker import process_one_task
    from wechat_automation.store.sqlite_store import SQLiteStore

    c = load_config(Path(config_path))
    c.mock_executor = {
        "default_outcome": "success",
        "target_map": {"wxid_test_peer_a": "mock-target-a"},
    }
    s = SQLiteStore(Path(db_path))
    rc = 0
    for _ in range(30):
        outcome = process_one_task(c, s)
        if outcome.kind.value == "no_work":
            time.sleep(0.02)
            continue
        if not outcome.counts_as_processed and outcome.kind.value != "no_work":
            rc = 1
    out_q.put(rc)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows dual-process Manager concurrency evidence")
def test_f3_two_process_peak_active_one(cfg, tmp_path: Path) -> None:
    from tests import concurrency_probe

    db = tmp_path / "conc.db"
    store = SQLiteStore(db)
    body = happy_path_envelope()
    body["length"] = 2
    body["messages"].append(
        _msg(seq=202609280666001, talker="wxid_test_peer_a", sender="u", content="help2")
    )
    ingest_webhook_batch(cfg, store, parse_webhook_batch(body))
    row = store.connect().execute("SELECT id FROM tasks ORDER BY id LIMIT 1").fetchone()
    assert row is not None
    barrier_task_id = int(row["id"])

    manager = multiprocessing.Manager()
    state = manager.dict(active=0, peak=0, observed=False)
    lock = manager.Lock()
    state["lock"] = lock
    concurrency_probe.bind(state)

    sync_file = str(tmp_path / "barrier.txt")
    out_q: multiprocessing.Queue = multiprocessing.Queue()
    p_hold = multiprocessing.Process(
        target=_concurrent_worker,
        args=(str(db), str(CONFIG_PATH), "hold", sync_file, state, barrier_task_id, out_q),
    )
    p_other = multiprocessing.Process(
        target=_concurrent_worker,
        args=(str(db), str(CONFIG_PATH), "normal", sync_file, state, barrier_task_id, out_q),
    )
    p_hold.start()
    time.sleep(0.4)
    p_other.start()
    deadline = time.time() + 20
    while time.time() < deadline and not Path(sync_file).exists():
        time.sleep(0.05)
    assert Path(sync_file).exists(), "holder did not enter executor interval"
    time.sleep(0.3)
    Path(sync_file).write_text("release", encoding="utf-8")
    p_hold.join(timeout=30)
    p_other.join(timeout=30)
    assert p_hold.exitcode == 0
    assert p_other.exitcode == 0
    assert out_q.get(timeout=5) == 0
    assert out_q.get(timeout=5) == 0
    assert state["observed"] is True
    assert int(state["peak"]) == 1
    assert int(state.get("task_1_executions", 0)) == 1
    assert int(state.get("task_2_executions", 0)) == 1
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 2
    assert store.count_tasks_by_status(TaskStatus.RUNNING) == 0


def test_f3_probe_sequential_counter_self_check_peak_two() -> None:
    """In-process probe counter self-check (not dual-process negative control)."""
    import threading

    from tests import concurrency_probe

    state: dict = {"active": 0, "peak": 0, "observed": False, "lock": threading.Lock()}
    concurrency_probe.bind(state)

    class DummyTask:
        id = 1

    concurrency_probe.before_execute(DummyTask())
    concurrency_probe.before_execute(DummyTask())
    concurrency_probe.after_execute(DummyTask())
    concurrency_probe.after_execute(DummyTask())
    assert int(state["peak"]) == 2


def test_f3_sequential_peak_not_concurrency_evidence(cfg, store: SQLiteStore) -> None:
    """Documents F2 single-process sequential measurement (not cross-process concurrency)."""
    ingest_webhook_batch(cfg, store, parse_webhook_batch(happy_path_envelope()))
    run_worker_once(cfg, store, max_tasks=1)
    assert store.count_tasks_by_status(TaskStatus.SIMULATED_SUCCEEDED) == 1


def test_f3_gate_eval_missing_required_nodeid(tmp_path: Path) -> None:
    from wechat_automation.cli.gate_eval import evaluate_gate_verdict

    report = {
        "valid": True,
        "tests": {
            "tests/test_w0_acceptance.py::test_01_single_message_happy_path": {
                "phases": {"setup": "passed", "call": "passed", "teardown": "passed"},
                "call_outcome": "passed",
                "has_xfail_marker": False,
                "wasxfail": None,
            }
        },
        "collection_errors": [],
    }
    req = {"tests/test_w0_acceptance.py::test_01_single_message_happy_path", "tests/missing.py::test_x"}
    ev = evaluate_gate_verdict(
        report,
        req,
        pytest_exit_code=0,
        pytest_counts={"passed": 1, "failed": 0, "skipped": 0, "xpassed": 0, "xfailed": 0, "collected": 1},
    )
    assert ev["gate_pass"] is False
    assert "tests/missing.py::test_x" in ev["missing_required"]
