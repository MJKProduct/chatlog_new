from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from uuid import uuid4

from wechat_automation.process_liveness import (
    PidLiveness,
    check_pid_liveness,
    get_process_instance_marker,
)

from wechat_automation.contracts import (
    FilterDecision,
    FilterOutcome,
    MessageEvent,
    ReplyTask,
    TaskStatus,
)
from wechat_automation.clock import Clock


class SQLiteStore:
    def __init__(self, db_path: Path, clock: Clock | None = None) -> None:
        self.db_path = db_path
        self.clock = clock or Clock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._migrate_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            else:
                conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.transaction() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_message_id TEXT,
                    event_key TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    is_self INTEGER,
                    message_type INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    message_time TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    raw_hash TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    identity_quality TEXT NOT NULL,
                    synthetic INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT,
                    UNIQUE(account_id, event_key)
                );
                CREATE TABLE IF NOT EXISTS event_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    rule_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(account_id, event_key)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    reply_text_snapshot TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    simulation INTEGER NOT NULL DEFAULT 1,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(account_id, event_key, rule_id)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    attempt_no INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    name TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    cursor_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(name, account_id)
                );
                CREATE TABLE IF NOT EXISTS execution_lock (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    holder TEXT,
                    acquired_at TEXT,
                    expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS rejected_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reason TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS identity_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    existing_fingerprint TEXT NOT NULL,
                    incoming_fingerprint TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    claim_token TEXT,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ingest_isolations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(account_id, event_key)
                );
                INSERT OR IGNORE INTO execution_lock (id, holder, acquired_at, expires_at)
                VALUES (1, NULL, NULL, NULL);
                """
            )

    def _migrate_schema(self) -> None:
        with self.connect() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
            for ddl in (
                "ALTER TABLE tasks ADD COLUMN owner_worker_id TEXT",
                "ALTER TABLE tasks ADD COLUMN owner_pid INTEGER",
                "ALTER TABLE tasks ADD COLUMN owner_pid_instance TEXT",
                "ALTER TABLE tasks ADD COLUMN execution_phase TEXT",
                "ALTER TABLE tasks ADD COLUMN claim_token TEXT",
                "ALTER TABLE tasks ADD COLUMN isolation_reason TEXT",
            ):
                col = ddl.split("ADD COLUMN ")[1].split()[0]
                if col not in cols:
                    conn.execute(ddl)
                    cols.add(col)
            ev_cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
            if "semantic_fingerprint" not in ev_cols:
                conn.execute("ALTER TABLE events ADD COLUMN semantic_fingerprint TEXT NOT NULL DEFAULT ''")

    def _now_iso(self) -> str:
        return self.clock.utcnow().isoformat()

    def insert_event_if_new(self, conn: sqlite3.Connection, event: MessageEvent) -> str:
        """Returns inserted | duplicate | identity_conflict."""
        is_self_val: Optional[int]
        if event.is_self is None:
            is_self_val = None
        else:
            is_self_val = 1 if event.is_self else 0
        try:
            conn.execute(
                """
                INSERT INTO events (
                    account_id, source, source_message_id, event_key, conversation_id,
                    sender_id, is_self, message_type, content, message_time, received_at,
                    raw_hash, schema_version, identity_quality, synthetic, payload_json,
                    semantic_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.account_id,
                    event.source,
                    event.source_message_id,
                    event.event_key,
                    event.conversation_id,
                    event.sender_id,
                    is_self_val,
                    event.message_type,
                    event.content,
                    event.message_time.isoformat(),
                    event.received_at.isoformat(),
                    event.raw_hash,
                    event.schema_version,
                    event.identity_quality.value,
                    1 if event.synthetic else 0,
                    json.dumps({"layer": event.raw_layer}, ensure_ascii=False),
                    event.semantic_fingerprint,
                ),
            )
            return "inserted"
        except sqlite3.IntegrityError:
            row = conn.execute(
                """
                SELECT semantic_fingerprint FROM events
                WHERE account_id=? AND event_key=?
                """,
                (event.account_id, event.event_key),
            ).fetchone()
            if not row:
                return "duplicate"
            existing_fp = str(row["semantic_fingerprint"] or "")
            incoming_fp = event.semantic_fingerprint or ""
            if existing_fp and incoming_fp and existing_fp != incoming_fp:
                conn.execute(
                    """
                    INSERT INTO identity_conflicts
                    (account_id, event_key, existing_fingerprint, incoming_fingerprint, detail, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.account_id,
                        event.event_key,
                        existing_fp,
                        incoming_fp,
                        "semantic_mismatch_same_event_key",
                        self._now_iso(),
                    ),
                )
                self.isolate_pending_tasks_for_event(
                    conn, event.account_id, event.event_key, "identity_conflict"
                )
                return "identity_conflict"
            return "duplicate"

    def record_isolated_event(
        self, conn: sqlite3.Connection, account_id: str, event_key: str, reason: str
    ) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO ingest_isolations
            (account_id, event_key, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, event_key, reason, self._now_iso()),
        )

    def isolate_pending_tasks_for_event(
        self, conn: sqlite3.Connection, account_id: str, event_key: str, reason: str
    ) -> int:
        cur = conn.execute(
            """
            UPDATE tasks SET status=?, isolation_reason=?, updated_at=?,
                owner_worker_id=NULL, owner_pid=NULL, owner_pid_instance=NULL, claim_token=NULL
            WHERE account_id=? AND event_key=? AND status=?
            """,
            (
                TaskStatus.CANCELLED.value,
                reason,
                self._now_iso(),
                account_id,
                event_key,
                TaskStatus.PENDING.value,
            ),
        )
        return int(cur.rowcount)

    def has_identity_conflict(self, conn: sqlite3.Connection, account_id: str, event_key: str) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM identity_conflicts
            WHERE account_id=? AND event_key=? LIMIT 1
            """,
            (account_id, event_key),
        ).fetchone()
        return row is not None

    def is_task_execution_blocked(self, task_id: int) -> tuple[bool, str]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT t.account_id, t.event_key, t.status, t.isolation_reason
                FROM tasks t WHERE t.id=?
                """,
                (task_id,),
            ).fetchone()
            if not row:
                return True, "task_missing"
            if row["isolation_reason"]:
                return True, str(row["isolation_reason"])
            if row["status"] != TaskStatus.PENDING.value and row["status"] != TaskStatus.RUNNING.value:
                return False, ""
            if self.has_identity_conflict(conn, row["account_id"], row["event_key"]):
                return True, "identity_conflict"
            iso = conn.execute(
                """
                SELECT reason FROM ingest_isolations
                WHERE account_id=? AND event_key=? LIMIT 1
                """,
                (row["account_id"], row["event_key"]),
            ).fetchone()
            if iso:
                return True, str(iso["reason"])
            return False, ""

    def save_decision(self, conn: sqlite3.Connection, account_id: str, decision: FilterDecision) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO event_decisions
            (account_id, event_key, outcome, reason, rule_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                decision.event_key,
                decision.outcome.value,
                decision.reason,
                decision.rule_id,
                self._now_iso(),
            ),
        )

    def create_task_if_absent(
        self, conn: sqlite3.Connection, task: ReplyTask
    ) -> tuple[Optional[int], bool]:
        now = self._now_iso()
        try:
            cur = conn.execute(
                """
                INSERT INTO tasks (
                    account_id, event_key, rule_id, rule_version, reply_text_snapshot,
                    conversation_id, status, simulation, retry_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.account_id,
                    task.event_key,
                    task.rule_id,
                    task.rule_version,
                    task.reply_text_snapshot,
                    task.conversation_id,
                    task.status.value,
                    1 if task.simulation else 0,
                    task.retry_count,
                    now,
                    now,
                ),
            )
            return int(cur.lastrowid), True
        except sqlite3.IntegrityError:
            row = conn.execute(
                """
                SELECT id FROM tasks
                WHERE account_id=? AND event_key=? AND rule_id=?
                """,
                (task.account_id, task.event_key, task.rule_id),
            ).fetchone()
            if row:
                return int(row["id"]), False
            return None, False

    def count_tasks(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()
            return int(row["c"])

    def count_tasks_by_status(self, status: TaskStatus) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM tasks WHERE status=?", (status.value,)
            ).fetchone()
            return int(row["c"])

    def count_events(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()
            return int(row["c"])

    def log_attempt(
        self, conn: sqlite3.Connection, task_id: int, attempt_no: int, phase: str, detail: str
    ) -> None:
        conn.execute(
            """
            INSERT INTO attempts (task_id, attempt_no, phase, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, attempt_no, phase, detail, self._now_iso()),
        )

    def acquire_execution_lock(self, holder: str, ttl_seconds: int) -> bool:
        now = self.clock.utcnow()
        expires = now.timestamp() + ttl_seconds
        expires_iso = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()
        now_iso = now.isoformat()
        with self.transaction(immediate=True) as conn:
            row = conn.execute("SELECT holder, expires_at FROM execution_lock WHERE id=1").fetchone()
            exp = row["expires_at"]
            if row["holder"] and exp:
                exp_dt = datetime.fromisoformat(exp)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt > now and row["holder"] != holder:
                    return False
            conn.execute(
                """
                UPDATE execution_lock SET holder=?, acquired_at=?, expires_at=? WHERE id=1
                """,
                (holder, now_iso, expires_iso),
            )
            return True

    def release_execution_lock(self, holder: str) -> None:
        with self.transaction(immediate=True) as conn:
            conn.execute(
                """
                UPDATE execution_lock SET holder=NULL, acquired_at=NULL, expires_at=NULL
                WHERE id=1 AND holder=?
                """,
                (holder,),
            )

    def _count_active_running(self, conn: sqlite3.Connection) -> int:
        rows = conn.execute(
            "SELECT id, owner_pid, owner_pid_instance FROM tasks WHERE status=?",
            (TaskStatus.RUNNING.value,),
        ).fetchall()
        active = 0
        for row in rows:
            pid = row["owner_pid"]
            if pid is None:
                active += 1
                continue
            instance = row["owner_pid_instance"]
            instance_str = str(instance) if instance is not None else None
            live = check_pid_liveness(int(pid), expected_instance=instance_str)
            if live in (PidLiveness.ALIVE, PidLiveness.UNKNOWN):
                active += 1
        return active

    def claim_next_pending_task(
        self, worker_id: str, ttl_seconds: int, owner_pid: int | None = None
    ) -> Optional[ReplyTask]:
        pid = owner_pid if owner_pid is not None else os.getpid()
        pid_instance = get_process_instance_marker(pid)
        if not self.acquire_execution_lock(worker_id, ttl_seconds):
            return None
        try:
            with self.transaction(immediate=True) as conn:
                if self._count_active_running(conn) > 0:
                    return None
                row = conn.execute(
                    """
                    SELECT t.* FROM tasks t
                    WHERE t.status=? AND (t.isolation_reason IS NULL OR t.isolation_reason='')
                      AND NOT EXISTS (
                        SELECT 1 FROM identity_conflicts ic
                        WHERE ic.account_id=t.account_id AND ic.event_key=t.event_key
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM ingest_isolations ii
                        WHERE ii.account_id=t.account_id AND ii.event_key=t.event_key
                      )
                    ORDER BY t.id LIMIT 1
                    """,
                    (TaskStatus.PENDING.value,),
                ).fetchone()
                if not row:
                    return None
                if self.has_identity_conflict(conn, row["account_id"], row["event_key"]):
                    return None
                token = uuid4().hex
                conn.execute(
                    """
                    UPDATE tasks SET status=?, updated_at=?, owner_worker_id=?, owner_pid=?,
                        owner_pid_instance=?, execution_phase=?, claim_token=? WHERE id=? AND status=?
                    """,
                    (
                        TaskStatus.RUNNING.value,
                        self._now_iso(),
                        worker_id,
                        pid,
                        pid_instance,
                        "claimed",
                        token,
                        row["id"],
                        TaskStatus.PENDING.value,
                    ),
                )
                claimed = conn.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone()
                return self._row_to_task(claimed, TaskStatus.RUNNING)
        finally:
            self.release_execution_lock(worker_id)

    def _row_to_task(self, row: sqlite3.Row, status: TaskStatus) -> ReplyTask:
        return ReplyTask(
            id=int(row["id"]),
            account_id=row["account_id"],
            event_key=row["event_key"],
            rule_id=row["rule_id"],
            rule_version=row["rule_version"],
            reply_text_snapshot=row["reply_text_snapshot"],
            conversation_id=row["conversation_id"],
            status=status,
            simulation=bool(row["simulation"]),
            retry_count=int(row["retry_count"]),
        )

    def mark_execution_started(self, task_id: int, worker_id: str, owner_pid: int, attempt_no: int) -> None:
        with self.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE tasks SET execution_phase=?, updated_at=?
                WHERE id=? AND status=? AND owner_worker_id=? AND owner_pid=?
                """,
                (
                    "started",
                    self._now_iso(),
                    task_id,
                    TaskStatus.RUNNING.value,
                    worker_id,
                    owner_pid,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError("execution_started_owner_mismatch")
            self.log_attempt(conn, task_id, attempt_no, "execution_started", "simulation=true")

    def complete_task_if_owner(
        self,
        task_id: int,
        worker_id: str,
        owner_pid: int,
        status: TaskStatus,
        attempt_no: int,
        attempt_phase: str,
        attempt_detail: str,
        retry_count: Optional[int] = None,
    ) -> bool:
        with self.transaction() as conn:
            if retry_count is None:
                cur = conn.execute(
                    """
                    UPDATE tasks SET status=?, updated_at=?, execution_phase=?, owner_worker_id=NULL,
                        owner_pid=NULL, claim_token=NULL
                    WHERE id=? AND status=? AND owner_worker_id=? AND owner_pid=?
                    """,
                    (
                        status.value,
                        self._now_iso(),
                        "finished",
                        task_id,
                        TaskStatus.RUNNING.value,
                        worker_id,
                        owner_pid,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE tasks SET status=?, updated_at=?, execution_phase=?, owner_worker_id=NULL,
                        owner_pid=NULL, claim_token=NULL, retry_count=?
                    WHERE id=? AND status=? AND owner_worker_id=? AND owner_pid=?
                    """,
                    (
                        status.value,
                        self._now_iso(),
                        "finished",
                        retry_count,
                        task_id,
                        TaskStatus.RUNNING.value,
                        worker_id,
                        owner_pid,
                    ),
                )
            if cur.rowcount != 1:
                return False
            self.log_attempt(conn, task_id, attempt_no, attempt_phase, attempt_detail)
            return True

    def has_attempt_phase(self, task_id: int, phase: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM attempts WHERE task_id=? AND phase=? LIMIT 1",
                (task_id, phase),
            ).fetchone()
            return row is not None

    def has_attempt_phase_for_attempt(self, task_id: int, attempt_no: int, phase: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM attempts WHERE task_id=? AND attempt_no=? AND phase=? LIMIT 1
                """,
                (task_id, attempt_no, phase),
            ).fetchone()
            return row is not None

    def list_running_task_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM tasks WHERE status=? ORDER BY id",
                (TaskStatus.RUNNING.value,),
            ).fetchall()
            return [int(r["id"]) for r in rows]

    def get_running_snapshot(self, task_id: int) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id=? AND status=?",
                (task_id, TaskStatus.RUNNING.value),
            ).fetchone()
            return dict(row) if row else None

    def recover_running_task_cas(
        self,
        *,
        task_id: int,
        expected_claim_token: str,
        expected_owner_worker_id: str,
        expected_owner_pid: Optional[int],
        mark_unknown: bool,
    ) -> str:
        new_status = TaskStatus.UNKNOWN if mark_unknown else TaskStatus.PENDING
        with self.transaction(immediate=True) as conn:
            if expected_owner_pid is None:
                cur = conn.execute(
                    """
                    UPDATE tasks SET status=?, updated_at=?, owner_worker_id=NULL, owner_pid=NULL,
                        claim_token=NULL, execution_phase=?
                    WHERE id=? AND status=? AND claim_token=? AND owner_worker_id=?
                      AND owner_pid IS NULL
                    """,
                    (
                        new_status.value,
                        self._now_iso(),
                        "recovered",
                        task_id,
                        TaskStatus.RUNNING.value,
                        expected_claim_token,
                        expected_owner_worker_id,
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE tasks SET status=?, updated_at=?, owner_worker_id=NULL, owner_pid=NULL,
                        claim_token=NULL, execution_phase=?
                    WHERE id=? AND status=? AND claim_token=? AND owner_worker_id=?
                      AND owner_pid=?
                    """,
                    (
                        new_status.value,
                        self._now_iso(),
                        "recovered",
                        task_id,
                        TaskStatus.RUNNING.value,
                        expected_claim_token,
                        expected_owner_worker_id,
                        expected_owner_pid,
                    ),
                )
            if cur.rowcount != 1:
                return "cas_conflict"
            conn.execute(
                """
                INSERT INTO recovery_audit (task_id, action, claim_token, detail, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    new_status.value,
                    expected_claim_token,
                    "mark_unknown" if mark_unknown else "recover_pending",
                    self._now_iso(),
                ),
            )
            return "marked_unknown" if mark_unknown else "recovered_pending"

    def update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        retry_count: Optional[int] = None,
    ) -> None:
        with self.transaction() as conn:
            if retry_count is None:
                conn.execute(
                    "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
                    (status.value, self._now_iso(), task_id),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status=?, retry_count=?, updated_at=? WHERE id=?",
                    (status.value, retry_count, self._now_iso(), task_id),
                )

    def get_task(self, task_id: int) -> Optional[ReplyTask]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            return ReplyTask(
                id=int(row["id"]),
                account_id=row["account_id"],
                event_key=row["event_key"],
                rule_id=row["rule_id"],
                rule_version=row["rule_version"],
                reply_text_snapshot=row["reply_text_snapshot"],
                conversation_id=row["conversation_id"],
                status=TaskStatus(row["status"]),
                simulation=bool(row["simulation"]),
                retry_count=int(row["retry_count"]),
            )

    def get_checkpoint(self, name: str, account_id: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT cursor_value FROM checkpoints WHERE name=? AND account_id=?",
                (name, account_id),
            ).fetchone()
            return row["cursor_value"] if row else None

    def set_checkpoint(self, name: str, account_id: str, cursor_value: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (name, account_id, cursor_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name, account_id) DO UPDATE SET
                    cursor_value=excluded.cursor_value,
                    updated_at=excluded.updated_at
                """,
                (name, account_id, cursor_value, self._now_iso()),
            )

    def record_rejection(self, reason: str, detail: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO rejected_batches (reason, detail, created_at) VALUES (?, ?, ?)",
                (reason, detail, self._now_iso()),
            )

    def status_summary(self) -> dict:
        with self.connect() as conn:
            tasks = conn.execute(
                "SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"
            ).fetchall()
            decisions = conn.execute(
                "SELECT outcome, COUNT(*) AS c FROM event_decisions GROUP BY outcome"
            ).fetchall()
            rejections = conn.execute("SELECT COUNT(*) AS c FROM rejected_batches").fetchone()
            return {
                "events": self.count_events(),
                "tasks_by_status": {r["status"]: int(r["c"]) for r in tasks},
                "decisions_by_outcome": {r["outcome"]: int(r["c"]) for r in decisions},
                "rejected_batches": int(rejections["c"]),
            }


def new_worker_id() -> str:
    return f"worker-{uuid4().hex[:12]}"
