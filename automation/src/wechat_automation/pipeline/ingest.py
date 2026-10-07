from __future__ import annotations

from typing import Iterable

from wechat_automation.config import AppConfig
from wechat_automation.contracts import MessageEvent, WebhookBatchEnvelope
from wechat_automation.rules.engine import evaluate_event
from wechat_automation.source.chatlog_decoder import decode_webhook_envelope
from wechat_automation.store.sqlite_store import SQLiteStore


def ingest_events(cfg: AppConfig, store: SQLiteStore, events: Iterable[MessageEvent]) -> dict[str, int]:
    created_tasks = 0
    new_events = 0
    skipped_dup = 0
    identity_conflicts = 0
    with store.transaction() as conn:
        for event in events:
            outcome = store.insert_event_if_new(conn, event)
            if outcome == "identity_conflict":
                identity_conflicts += 1
                store.isolate_pending_tasks_for_event(conn, cfg.account_id, event.event_key, "identity_conflict")
                continue
            if outcome != "inserted":
                skipped_dup += 1
                continue
            new_events += 1
            if event.ingest_blocked:
                store.record_isolated_event(conn, cfg.account_id, event.event_key, event.block_reason)
                continue
            decision, task = evaluate_event(cfg, event)
            store.save_decision(conn, cfg.account_id, decision)
            if task is not None:
                _tid, created = store.create_task_if_absent(conn, task)
                if created:
                    created_tasks += 1
    return {
        "new_events": new_events,
        "skipped_duplicate_events": skipped_dup,
        "identity_conflicts": identity_conflicts,
        "tasks_created": created_tasks,
    }


def ingest_webhook_batch(
    cfg: AppConfig,
    store: SQLiteStore,
    envelope: WebhookBatchEnvelope,
) -> dict[str, int]:
    if envelope.validation_errors:
        store.record_rejection("invalid_envelope", ",".join(envelope.validation_errors))
    events = decode_webhook_envelope(cfg.account_id, envelope)
    return ingest_events(cfg, store, events)
