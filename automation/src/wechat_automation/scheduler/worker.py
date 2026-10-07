from __future__ import annotations

import os

from wechat_automation.config import AppConfig
from wechat_automation.contracts import TaskStatus
from wechat_automation.executor.mock import MockExecutor, MockExecutorConfig
from wechat_automation.recovery import recover_interrupted_tasks
from wechat_automation.scheduler.outcomes import ProcessOutcome, ProcessOutcomeKind
from wechat_automation.store.sqlite_store import SQLiteStore, new_worker_id


def build_executor(cfg: AppConfig) -> MockExecutor:
    if cfg.executor != "mock":
        raise ValueError(f"W0-F2 allows executor=mock only, got {cfg.executor!r}")
    return MockExecutor(MockExecutorConfig.from_dict(cfg.mock_executor))


def process_one_task(
    cfg: AppConfig,
    store: SQLiteStore,
    worker_id: str | None = None,
    *,
    skip_recovery: bool = False,
) -> ProcessOutcome:
    if not skip_recovery:
        recover_interrupted_tasks(store)
    wid = worker_id or new_worker_id()
    pid = os.getpid()
    executor = build_executor(cfg)
    task = store.claim_next_pending_task(wid, cfg.lock_ttl_seconds, owner_pid=pid)
    if not task or task.id is None:
        return ProcessOutcome(ProcessOutcomeKind.NO_WORK)

    blocked, block_reason = store.is_task_execution_blocked(task.id)
    if blocked:
        store.complete_task_if_owner(
            task.id,
            wid,
            pid,
            TaskStatus.CANCELLED,
            task.retry_count + 1,
            "execution_blocked",
            block_reason,
        )
        return ProcessOutcome(ProcessOutcomeKind.PROCESSED, f"blocked:{block_reason}")

    attempt_no = task.retry_count + 1
    try:
        store.mark_execution_started(task.id, wid, pid, attempt_no)
    except RuntimeError:
        return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "execution_started_owner_mismatch")

    try:
        result = executor.execute(task)
    except Exception as exc:  # noqa: BLE001 — structured executor failure path
        ok = store.complete_task_if_owner(
            task.id,
            wid,
            pid,
            TaskStatus.UNKNOWN,
            attempt_no,
            "execution_exception",
            f"{type(exc).__name__}:{exc}",
        )
        if not ok:
            return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "complete_failed_after_exception")
        return ProcessOutcome(ProcessOutcomeKind.EXECUTOR_ERROR, str(exc))

    if result.status == TaskStatus.SIMULATED_SUCCEEDED:
        ok = store.complete_task_if_owner(
            task.id,
            wid,
            pid,
            TaskStatus.SIMULATED_SUCCEEDED,
            attempt_no,
            "execution_finished",
            result.detail,
        )
        if not ok:
            return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "complete_failed_success")
        return ProcessOutcome(ProcessOutcomeKind.PROCESSED, result.detail)

    if result.status == TaskStatus.UNKNOWN:
        ok = store.complete_task_if_owner(
            task.id,
            wid,
            pid,
            TaskStatus.UNKNOWN,
            attempt_no,
            "execution_unknown",
            result.detail,
        )
        if not ok:
            return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "complete_failed_unknown")
        return ProcessOutcome(ProcessOutcomeKind.PROCESSED, result.detail)

    if result.detail == "mock_transient_error" and task.retry_count + 1 < cfg.max_retries:
        ok = store.complete_task_if_owner(
            task.id,
            wid,
            pid,
            TaskStatus.PENDING,
            attempt_no,
            "execution_retry",
            result.detail,
            retry_count=task.retry_count + 1,
        )
        if not ok:
            return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "complete_failed_retry")
        return ProcessOutcome(ProcessOutcomeKind.PROCESSED, "retry_scheduled")

    ok = store.complete_task_if_owner(
        task.id,
        wid,
        pid,
        TaskStatus.FAILED,
        attempt_no,
        "execution_failed",
        result.detail,
        retry_count=task.retry_count + 1,
    )
    if not ok:
        return ProcessOutcome(ProcessOutcomeKind.OWNERSHIP_LOST, "complete_failed_terminal")
    return ProcessOutcome(ProcessOutcomeKind.PROCESSED, result.detail)


def run_worker_once(cfg: AppConfig, store: SQLiteStore, max_tasks: int = 100) -> int:
    recover_interrupted_tasks(store)
    processed = 0
    for _ in range(max_tasks):
        outcome = process_one_task(cfg, store, skip_recovery=True)
        if outcome.kind == ProcessOutcomeKind.NO_WORK:
            break
        if outcome.counts_as_processed:
            processed += 1
    return processed
