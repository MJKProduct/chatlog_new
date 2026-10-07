from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class IdentityQuality(str, Enum):
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SIMULATED_SUCCEEDED = "SIMULATED_SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class FilterOutcome(str, Enum):
    MATCHED = "MATCHED"
    IGNORED = "IGNORED"


@dataclass
class MessageEvent:
    account_id: str
    source: str
    event_key: str
    conversation_id: str
    sender_id: str
    is_self: Optional[bool]
    message_type: int
    content: str
    message_time: datetime
    received_at: datetime
    raw_hash: str
    schema_version: str = "w0-1"
    identity_quality: IdentityQuality = IdentityQuality.CONFIRMED
    source_message_id: Optional[str] = None
    synthetic: bool = True
    conversation_display_name: str = ""
    raw_layer: str = "internal_event"
    semantic_fingerprint: str = ""
    chatlog_seq: Optional[int] = None
    ingest_blocked: bool = False
    block_reason: str = ""


@dataclass
class FilterDecision:
    event_key: str
    outcome: FilterOutcome
    reason: str
    rule_id: Optional[str] = None


@dataclass
class ReplyTask:
    id: Optional[int]
    account_id: str
    event_key: str
    rule_id: str
    rule_version: str
    reply_text_snapshot: str
    conversation_id: str
    status: TaskStatus
    simulation: bool = True
    retry_count: int = 0


@dataclass
class ExecutionAttempt:
    task_id: int
    attempt_no: int
    phase: str
    detail: str
    created_at: datetime


@dataclass
class ExecutionResult:
    success: bool
    status: TaskStatus
    simulation: bool = True
    detail: str = ""
    synthetic: bool = True


@dataclass
class WebhookBatchEnvelope:
    talker: str
    sender: str
    keyword: str
    last_time: str
    length: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    synthetic: bool = True
    raw_layer: str = "chatlog_webhook_fixture"
    validation_errors: list[str] = field(default_factory=list)
