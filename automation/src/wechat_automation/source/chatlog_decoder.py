from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from wechat_automation.contracts import IdentityQuality, MessageEvent, WebhookBatchEnvelope
from wechat_automation.clock import Clock
from wechat_automation.source.message_identity import (
    build_event_key,
    parse_message_type,
    parse_strict_bool,
    resolve_go_message_identity,
    resolve_synthetic_message_identity,
    semantic_fingerprint,
    validate_message_fields,
)


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _raw_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def decode_chatlog_message(
    account_id: str,
    msg: dict[str, Any],
    received_at: datetime,
    source: str = "fixture",
) -> MessageEvent:
    """Decode Go API-shaped messages (webhook/backfill). Rejects internal sim id."""
    return _decode_message(account_id, msg, received_at, source=source, allow_internal_sim=False)


def decode_synthetic_message(
    account_id: str,
    msg: dict[str, Any],
    received_at: datetime,
    source: str = "synthetic_fixture",
) -> MessageEvent:
    """Test/demo ingest only; may accept _internal_sim_message_id."""
    return _decode_message(account_id, msg, received_at, source=source, allow_internal_sim=True)


def _decode_message(
    account_id: str,
    msg: dict[str, Any],
    received_at: datetime,
    *,
    source: str,
    allow_internal_sim: bool,
) -> MessageEvent:
    field_errors = validate_message_fields(msg)
    conversation_id = str(msg.get("talker") or "") if isinstance(msg.get("talker"), str) else ""
    sender_id = str(msg.get("sender") or "") if isinstance(msg.get("sender"), str) else ""
    message_type, _type_reason = parse_message_type(msg.get("type", 0))
    if msg.get("content") is None:
        content = ""
    elif isinstance(msg.get("content"), str):
        content = str(msg.get("content"))
    else:
        content = ""
        field_errors.append("content_not_string")
    try:
        message_time = _parse_time(msg.get("time"))
    except Exception:
        message_time = datetime.now(timezone.utc)
        field_errors.append("time_invalid")
    is_self = parse_strict_bool(msg.get("isSelf"))

    internal_sim_id: Optional[str] = None
    seq: Optional[int] = None
    identity_quality: IdentityQuality
    identity_basis: str

    if allow_internal_sim:
        internal_sim_id, seq, identity_quality, identity_basis = resolve_synthetic_message_identity(msg)
    else:
        seq, identity_quality, identity_basis = resolve_go_message_identity(msg)

    if is_self is None:
        identity_quality = IdentityQuality.UNKNOWN
    if field_errors:
        identity_quality = IdentityQuality.UNKNOWN

    raw_hash = _raw_hash(msg)
    event_key = build_event_key(
        account_id,
        conversation_id,
        internal_sim_id=internal_sim_id,
        seq=seq,
        identity_quality=identity_quality,
        fallback_hash=raw_hash,
    )
    source_message_id = internal_sim_id
    layer = "chatlog_webhook_message" if source == "webhook" else "chatlog_message_fixture"
    if internal_sim_id:
        layer = "internal_sim_message"

    fp = semantic_fingerprint(
        msg,
        account_id,
        conversation_id,
        seq,
        is_self=is_self,
    )
    block_reason = ",".join(field_errors) if field_errors else ""
    return MessageEvent(
        account_id=account_id,
        source=source,
        source_message_id=source_message_id,
        event_key=event_key,
        conversation_id=conversation_id,
        sender_id=sender_id,
        is_self=is_self,
        message_type=message_type,
        content=content,
        message_time=message_time,
        received_at=received_at,
        raw_hash=raw_hash,
        identity_quality=identity_quality,
        conversation_display_name=str(msg.get("talkerName") or ""),
        synthetic=True,
        raw_layer=layer,
        semantic_fingerprint=fp,
        chatlog_seq=seq,
        ingest_blocked=bool(block_reason),
        block_reason=block_reason,
    )


def decode_webhook_envelope(
    account_id: str,
    envelope: WebhookBatchEnvelope,
    clock: Clock | None = None,
) -> list[MessageEvent]:
    clk = clock or Clock()
    received_at = clk.utcnow()
    return [
        decode_chatlog_message(account_id, msg, received_at, source="webhook")
        for msg in envelope.messages
    ]


def validate_webhook_envelope(body: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    messages_raw = body.get("messages")
    if not isinstance(messages_raw, list):
        return ["messages_not_list"], []
    length = body.get("length")
    if length is not None and int(length) != len(messages_raw):
        errors.append("length_mismatch")
    clean: list[dict[str, Any]] = []
    for idx, msg in enumerate(messages_raw):
        if not isinstance(msg, dict):
            errors.append(f"message_{idx}_not_object")
            continue
        if not msg.get("talker"):
            errors.append(f"message_{idx}_missing_talker")
            continue
        clean.append(msg)
    return errors, clean


def parse_webhook_batch(body: dict[str, Any]) -> WebhookBatchEnvelope:
    errors, messages = validate_webhook_envelope(body)
    return WebhookBatchEnvelope(
        talker=str(body.get("talker") or ""),
        sender=str(body.get("sender") or ""),
        keyword=str(body.get("keyword") or ""),
        last_time=str(body.get("lastTime") or body.get("last_time") or ""),
        length=int(body.get("length") if body.get("length") is not None else len(messages)),
        messages=messages,
        synthetic=True,
        validation_errors=errors,
    )


def event_semantic_fingerprint(account_id: str, event: MessageEvent, seq: Optional[int]) -> str:
    return semantic_fingerprint(
        {
            "sender": event.sender_id,
            "type": event.message_type,
            "content": event.content,
        },
        account_id,
        event.conversation_id,
        seq,
    )
