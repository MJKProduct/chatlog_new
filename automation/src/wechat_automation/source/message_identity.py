from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Tuple

from wechat_automation.contracts import IdentityQuality

INTERNAL_SIM_ID_FIELD = "_internal_sim_message_id"
INT64_MAX = 9223372036854775807


def parse_strict_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if type(value) is bool:
        return value
    return None


def parse_chatlog_seq(value: Any) -> Tuple[Optional[int], str]:
    if value is None:
        return None, "missing_seq"
    if isinstance(value, bool):
        return None, "seq_bool_rejected"
    if isinstance(value, float):
        return None, "seq_float_rejected"
    if isinstance(value, str):
        return None, "seq_str_rejected"
    if not isinstance(value, int):
        return None, "seq_invalid_type"
    if value <= 0 or value > INT64_MAX:
        return None, "seq_out_of_range"
    return value, "ok"


def parse_message_type(value: Any) -> Tuple[int, str]:
    if isinstance(value, bool):
        return -1, "type_bool_rejected"
    if isinstance(value, float):
        return -1, "type_float_rejected"
    if isinstance(value, str):
        return -1, "type_str_rejected"
    if not isinstance(value, int):
        return -1, "type_invalid"
    return value, "ok"


def validate_required_string_field(value: Any, field: str, *, allow_empty: bool = True) -> Optional[str]:
    if value is None:
        return f"{field}_missing" if not allow_empty else None
    if not isinstance(value, str):
        return f"{field}_not_string"
    if not allow_empty and not value.strip():
        return f"{field}_empty"
    return None


def validate_message_fields(msg: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    talker_err = validate_required_string_field(msg.get("talker"), "talker", allow_empty=False)
    if talker_err:
        errors.append(talker_err)
    if "sender" not in msg or msg.get("sender") is None:
        errors.append("sender_missing")
    elif not isinstance(msg.get("sender"), str):
        errors.append("sender_not_string")
    if "content" in msg and msg.get("content") is not None and not isinstance(msg.get("content"), str):
        errors.append("content_not_string")
    msg_type, type_reason = parse_message_type(msg.get("type", 0))
    if type_reason.endswith("rejected") or type_reason == "type_invalid":
        errors.append(type_reason)
    if msg.get("time") is None:
        errors.append("time_missing")
    return errors


def semantic_fingerprint(
    msg: dict[str, Any],
    account_id: str,
    conversation_id: str,
    seq: Optional[int],
    *,
    is_self: Optional[bool] = None,
) -> str:
    payload = {
        "account_id": account_id,
        "conversation_id": conversation_id,
        "seq": seq,
        "sender": str(msg.get("sender") or ""),
        "type": msg.get("type") if isinstance(msg.get("type"), int) else None,
        "content": str(msg.get("content") or "") if msg.get("content") is not None else "",
        "is_self": is_self,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_go_message_identity(msg: dict[str, Any]) -> Tuple[Optional[int], IdentityQuality, str]:
    """Identity from Go-shaped API messages only (no internal sim fields)."""
    if INTERNAL_SIM_ID_FIELD in msg:
        return None, IdentityQuality.UNKNOWN, "internal_sim_in_go_decoder_rejected"
    seq, reason = parse_chatlog_seq(msg.get("seq"))
    if seq is None:
        return None, IdentityQuality.UNKNOWN, reason
    return seq, IdentityQuality.CONFIRMED, "chatlog_seq"


def resolve_synthetic_message_identity(
    msg: dict[str, Any],
) -> Tuple[Optional[str], Optional[int], IdentityQuality, str]:
    internal = msg.get(INTERNAL_SIM_ID_FIELD)
    if internal is not None:
        return str(internal), None, IdentityQuality.CONFIRMED, "internal_sim_id"
    seq, quality, basis = resolve_go_message_identity(msg)
    return None, seq, quality, basis


def build_event_key(
    account_id: str,
    conversation_id: str,
    *,
    internal_sim_id: Optional[str] = None,
    seq: Optional[int] = None,
    identity_quality: IdentityQuality,
    fallback_hash: str,
) -> str:
    if internal_sim_id:
        return f"{account_id}:{conversation_id}:sim:{internal_sim_id}"
    if seq is not None and identity_quality == IdentityQuality.CONFIRMED:
        return f"{account_id}:{conversation_id}:seq:{seq}"
    return f"{account_id}:{conversation_id}:unverified:{fallback_hash[:32]}"
