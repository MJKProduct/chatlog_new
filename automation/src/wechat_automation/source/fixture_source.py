from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wechat_automation.source.chatlog_decoder import parse_webhook_batch, decode_webhook_envelope
from wechat_automation.contracts import MessageEvent, WebhookBatchEnvelope
from wechat_automation.clock import Clock


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_webhook_fixture(path: Path) -> WebhookBatchEnvelope:
    body = load_fixture(path)
    if "envelope" in body:
        body = body["envelope"]
    return parse_webhook_batch(body)


def events_from_fixture(path: Path, account_id: str, clock: Clock | None = None) -> list[MessageEvent]:
    envelope = load_webhook_fixture(path)
    return decode_webhook_envelope(account_id, envelope, clock=clock)
