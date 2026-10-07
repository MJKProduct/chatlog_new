"""Test-only helpers (not production API)."""

from __future__ import annotations

from wechat_automation.contracts import TaskStatus
from wechat_automation.store.sqlite_store import SQLiteStore


def force_task_status_for_test(store: SQLiteStore, task_id: int, status: TaskStatus) -> None:
    with store.transaction() as conn:
        conn.execute(
            """
            UPDATE tasks SET status=?, owner_worker_id=NULL, owner_pid=NULL,
                claim_token=NULL, execution_phase='test_mutation', updated_at=datetime('now')
            WHERE id=?
            """,
            (status.value, task_id),
        )
