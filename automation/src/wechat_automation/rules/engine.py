from __future__ import annotations

from typing import Optional

from wechat_automation.config import AppConfig, KeywordRule
from wechat_automation.contracts import (
    FilterDecision,
    FilterOutcome,
    IdentityQuality,
    MessageEvent,
    ReplyTask,
    TaskStatus,
)

MESSAGE_TYPE_TEXT = 1
MESSAGE_TYPE_SYSTEM = 10000


def evaluate_event(cfg: AppConfig, event: MessageEvent) -> tuple[FilterDecision, Optional[ReplyTask]]:
    if event.is_self is None:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "is_self_unknown"),
            None,
        )
    if event.is_self:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "self_message"),
            None,
        )
    if event.identity_quality == IdentityQuality.UNKNOWN:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "identity_unknown"),
            None,
        )
    if event.message_type == MESSAGE_TYPE_SYSTEM:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "system_message"),
            None,
        )
    if event.message_type != MESSAGE_TYPE_TEXT:
        return (
            FilterDecision(
                event.event_key,
                FilterOutcome.IGNORED,
                f"non_text_type:{event.message_type}",
            ),
            None,
        )
    if event.conversation_id not in cfg.allowed_conversation_ids:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "not_in_whitelist"),
            None,
        )

    matched: Optional[KeywordRule] = None
    lowered = event.content.casefold()
    for rule in cfg.keyword_rules:
        for kw in rule.keywords:
            if kw.casefold() in lowered:
                matched = rule
                break
        if matched:
            break

    if not matched:
        return (
            FilterDecision(event.event_key, FilterOutcome.IGNORED, "keyword_miss"),
            None,
        )

    task = ReplyTask(
        id=None,
        account_id=event.account_id,
        event_key=event.event_key,
        rule_id=matched.rule_id,
        rule_version=cfg.rule_version,
        reply_text_snapshot=matched.reply_text,
        conversation_id=event.conversation_id,
        status=TaskStatus.PENDING,
        simulation=True,
    )
    return (
        FilterDecision(
            event.event_key,
            FilterOutcome.MATCHED,
            "keyword_hit",
            rule_id=matched.rule_id,
        ),
        task,
    )
