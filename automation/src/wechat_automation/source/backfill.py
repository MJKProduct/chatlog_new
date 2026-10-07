from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlparse

from wechat_automation.config import AppConfig
from wechat_automation.source.chatlog_decoder import decode_chatlog_message
from wechat_automation.contracts import MessageEvent
from wechat_automation.clock import Clock
from wechat_automation.store.sqlite_store import SQLiteStore


class HTTPTransport(Protocol):
    def get_json(self, url: str) -> tuple[int, Any]: ...


@dataclass
class BackfillResult:
    fetched: int
    ingested: int
    pages_ok: int
    pages_failed: int
    checkpoint_advanced: bool
    synthetic: bool = True
    error: str | None = None


class BackfillConfigError(ValueError):
    pass


def format_go_time_range(start: datetime, end: datetime) -> str:
    """Go TimeRangeOf accepts '~' between two RFC3339-like time points."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start > end:
        raise BackfillConfigError("start_after_end")
    return f"{start.isoformat()}~{end.isoformat()}"


def backfill_checkpoint_name(talker: str, query: dict[str, Any]) -> str:
    blob = json.dumps({"talker": talker, **query}, sort_keys=True)
    sig = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"chatlog_backfill:{talker}:{sig}"


def chatlog_query_url(
    base: str,
    talker: str,
    time_range: str,
    limit: int,
    offset: int,
    *,
    sender: str = "",
    keyword: str = "",
) -> str:
    from urllib.parse import urlencode

    q = urlencode(
        {
            "format": "json",
            "talker": talker,
            "time": time_range,
            "limit": str(limit),
            "offset": str(offset),
            "sender": sender,
            "keyword": keyword,
        }
    )
    return f"{base.rstrip('/')}/api/v1/chatlog?{q}"


def validate_backfill_params(
    cfg: AppConfig, window_start: datetime, window_end: datetime
) -> tuple[int, int]:
    page_size = int(cfg.backfill.get("page_size", 50))
    overlap = int(cfg.backfill.get("overlap_seconds", 5))
    if page_size <= 0:
        raise BackfillConfigError("page_size_must_be_positive")
    if overlap < 0:
        raise BackfillConfigError("overlap_must_be_non_negative")
    if window_start > window_end:
        raise BackfillConfigError("start_after_end")
    return page_size, overlap


def run_backfill_window(
    cfg: AppConfig,
    store: SQLiteStore,
    ingest_fn: Callable[[list[MessageEvent]], dict[str, int]],
    base_url: str,
    talker: str,
    window_start: datetime,
    window_end: datetime,
    transport: HTTPTransport,
    clock: Clock | None = None,
    sender: str = "",
    keyword: str = "",
) -> BackfillResult:
    if transport is None:
        raise BackfillConfigError("transport_required_explicit_injection")
    clk = clock or Clock()
    page_size, overlap = validate_backfill_params(cfg, window_start, window_end)
    query = {"sender": sender, "keyword": keyword, "page_size": page_size}
    cp_name = backfill_checkpoint_name(talker, query)
    cursor_raw = store.get_checkpoint(cp_name, cfg.account_id)
    effective_start = window_start
    if cursor_raw:
        effective_start = datetime.fromisoformat(cursor_raw) - timedelta(seconds=overlap)
        if effective_start.tzinfo is None:
            effective_start = effective_start.replace(tzinfo=timezone.utc)

    time_range = format_go_time_range(effective_start, window_end)
    offset = 0
    all_events: list[MessageEvent] = []
    pages_ok = 0
    pages_failed = 0
    received_at = clk.utcnow()

    error: str | None = None
    try:
        while True:
            url = chatlog_query_url(
                base_url,
                talker,
                time_range,
                page_size,
                offset,
                sender=sender,
                keyword=keyword,
            )
            status, payload = transport.get_json(url)
            if status != 200 or not isinstance(payload, list):
                pages_failed += 1
                error = "page_fetch_failed"
                break
            pages_ok += 1
            if not payload:
                break
            for msg in payload:
                all_events.append(
                    decode_chatlog_message(cfg.account_id, msg, received_at, source="backfill")
                )
            if len(payload) < page_size:
                break
            offset += page_size
    except Exception as exc:  # noqa: BLE001 — surface as structured backfill failure
        pages_failed += 1
        error = f"backfill_exception:{type(exc).__name__}"

    checkpoint_advanced = False
    ingested = 0
    if pages_failed == 0:
        try:
            stats = ingest_fn(all_events)
            ingested = stats.get("tasks_created", 0)
            store.set_checkpoint(cp_name, cfg.account_id, window_end.isoformat())
            checkpoint_advanced = True
        except Exception as exc:  # noqa: BLE001
            error = f"ingest_exception:{type(exc).__name__}"

    return BackfillResult(
        fetched=len(all_events),
        ingested=ingested,
        pages_ok=pages_ok,
        pages_failed=pages_failed,
        checkpoint_advanced=checkpoint_advanced,
        error=error if pages_failed or error else None,
    )


def parse_chatlog_query(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return {k: v[0] if v else "" for k, v in qs.items()}
