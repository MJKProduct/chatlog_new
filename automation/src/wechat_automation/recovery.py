from __future__ import annotations

from wechat_automation.process_liveness import PidLiveness, check_pid_liveness
from wechat_automation.store.sqlite_store import SQLiteStore


def recover_interrupted_tasks(store: SQLiteStore) -> dict[str, int]:
    """
    CAS-based recovery. Stale snapshots cannot clobber a new owner/claim_token.
    UNKNOWN liveness does not recover (conservative — may still hold execution channel).
    """
    stats = {
        "recovered_pending": 0,
        "marked_unknown": 0,
        "skipped_alive": 0,
        "skipped_unknown_liveness": 0,
        "cas_conflict": 0,
    }
    task_ids = store.list_running_task_ids()
    for task_id in task_ids:
        snapshot = store.get_running_snapshot(task_id)
        if not snapshot:
            continue
        pid = snapshot.get("owner_pid")
        instance = snapshot.get("owner_pid_instance")
        instance_str = str(instance) if instance is not None else None
        liveness = (
            check_pid_liveness(int(pid), expected_instance=instance_str)
            if pid is not None
            else PidLiveness.UNKNOWN
        )
        if liveness == PidLiveness.ALIVE:
            stats["skipped_alive"] += 1
            continue
        if liveness == PidLiveness.UNKNOWN:
            stats["skipped_unknown_liveness"] += 1
            continue
        attempt_no = int(snapshot["retry_count"]) + 1
        started_current = store.has_attempt_phase_for_attempt(task_id, attempt_no, "execution_started")
        outcome = store.recover_running_task_cas(
            task_id=task_id,
            expected_claim_token=str(snapshot["claim_token"]),
            expected_owner_worker_id=str(snapshot["owner_worker_id"]),
            expected_owner_pid=int(snapshot["owner_pid"]) if snapshot["owner_pid"] is not None else None,
            mark_unknown=started_current,
        )
        if outcome == "recovered_pending":
            stats["recovered_pending"] += 1
        elif outcome == "marked_unknown":
            stats["marked_unknown"] += 1
        elif outcome == "cas_conflict":
            stats["cas_conflict"] += 1
    return stats
