from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from wechat_automation.source.backfill import parse_chatlog_query


class StrictChatlogStubTransport:
    """Validates chatlog query URL including talker, limit, offset, sender, keyword, time range."""

    def __init__(
        self,
        pages: dict[int, list[dict[str, Any]]],
        *,
        fail_offsets: set[int] | None = None,
        expect_talker: str | None = None,
        expect_sender: str = "",
        expect_keyword: str = "",
        expect_time_contains: str | None = None,
        expect_limit: int | None = None,
    ) -> None:
        self.pages = pages
        self.fail_offsets = fail_offsets or set()
        self.expect_talker = expect_talker
        self.expect_sender = expect_sender
        self.expect_keyword = expect_keyword
        self.expect_time_contains = expect_time_contains
        self.expect_limit = expect_limit
        self.requests: list[dict[str, str]] = []

    def get_json(self, url: str) -> tuple[int, Any]:
        q = parse_chatlog_query(url)
        self.requests.append(q)
        if q.get("format") != "json":
            return 400, {"error": "bad_format"}
        time_param = unquote(q.get("time", ""))
        if "~" not in time_param:
            return 400, {"error": "bad_time_range"}
        if re.match(r"^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$", time_param):
            return 400, {"error": "slash_date_range_not_allowed"}
        if self.expect_talker is not None and q.get("talker") != self.expect_talker:
            return 400, {"error": "unexpected_talker"}
        if q.get("sender", "") != self.expect_sender:
            return 400, {"error": "unexpected_sender"}
        if q.get("keyword", "") != self.expect_keyword:
            return 400, {"error": "unexpected_keyword"}
        if self.expect_limit is not None and int(q.get("limit") or 0) != self.expect_limit:
            return 400, {"error": "unexpected_limit"}
        if self.expect_time_contains and self.expect_time_contains not in time_param:
            return 400, {"error": "unexpected_time_window"}
        offset = int(q.get("offset") or 0)
        if offset in self.fail_offsets:
            return 500, {"error": "page_failed"}
        return 200, self.pages.get(offset, [])
