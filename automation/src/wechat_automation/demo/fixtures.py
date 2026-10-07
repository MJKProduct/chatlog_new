from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wechat_automation.source.message_identity import INTERNAL_SIM_ID_FIELD


def _msg(
    *,
    seq: int,
    talker: str,
    sender: str,
    content: str,
    is_self: bool = False,
    msg_type: int = 1,
    talker_name: str = "测试会话",
    time_iso: str | None = None,
    internal_sim_id: str | None = None,
) -> dict[str, Any]:
    """Go-faithful chatlog message JSON (seq + isSelf bool); internal_sim_id for tests only."""
    m: dict[str, Any] = {
        "seq": seq,
        "time": time_iso or datetime(2026, 9, 28, 8, 0, seq % 60, tzinfo=timezone.utc).isoformat(),
        "talker": talker,
        "talkerName": talker_name,
        "isChatRoom": False,
        "sender": sender,
        "senderName": "Peer",
        "isSelf": is_self,
        "type": msg_type,
        "subType": 1,
        "content": content,
    }
    if internal_sim_id is not None:
        m[INTERNAL_SIM_ID_FIELD] = internal_sim_id
    return m


def happy_path_envelope() -> dict[str, Any]:
    return {
        "talker": "wxid_test_peer_a",
        "sender": "",
        "keyword": "",
        "lastTime": "2026-09-28 16:00:01",
        "length": 1,
        "messages": [
            _msg(
                seq=202609280001001,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content="你好，help 请问在吗？",
            )
        ],
        "synthetic": True,
    }


def write_fixture(path: Path, envelope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"envelope": envelope, "synthetic": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def duplicate_event_envelope() -> dict[str, Any]:
    return happy_path_envelope()


def same_content_different_ids_envelope() -> dict[str, Any]:
    base = "相同文本内容 help"
    return {
        "talker": "wxid_test_peer_a",
        "sender": "",
        "keyword": "",
        "lastTime": "2026-09-28 16:00:02",
        "length": 2,
        "messages": [
            _msg(
                seq=202609280010001,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content=base,
            ),
            _msg(
                seq=202609280010002,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content=base,
            ),
        ],
        "synthetic": True,
    }


def self_message_loop_envelope() -> dict[str, Any]:
    return {
        "talker": "wxid_test_peer_a",
        "sender": "",
        "keyword": "",
        "lastTime": "2026-09-28 16:00:03",
        "length": 1,
        "messages": [
            _msg(
                seq=202609280020001,
                talker="wxid_test_peer_a",
                sender="wxid_self",
                content="【模拟回复】已收到，稍后联系您。",
                is_self=True,
            )
        ],
        "synthetic": True,
    }


def filtered_messages_envelope() -> dict[str, Any]:
    return {
        "talker": "wxid_test_peer_a",
        "sender": "",
        "keyword": "",
        "lastTime": "2026-09-28 16:00:04",
        "length": 4,
        "messages": [
            _msg(
                seq=202609280030001,
                talker="wxid_not_allowed",
                sender="wxid_x",
                content="help",
            ),
            _msg(
                seq=202609280030002,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content="help",
                msg_type=10000,
            ),
            _msg(
                seq=202609280030003,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content="photo",
                msg_type=3,
            ),
            _msg(
                seq=202609280030004,
                talker="wxid_test_peer_a",
                sender="wxid_peer_user",
                content="help",
            ),
        ],
        "synthetic": True,
    }


def patch_unknown_self(envelope: dict[str, Any]) -> None:
    for m in envelope["messages"]:
        if m.get("seq") == 202609280030004:
            m.pop("isSelf", None)
