"""Pytest plugin: structured gate report (nodeid, phases, wasxfail, collection errors)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

GATE_REPORT_VERSION = 1

_session: dict[str, Any] = {"tests": {}, "collection_errors": []}
_report_path: str | None = None


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--gate-report",
        action="store",
        default=None,
        help="Write structured JSON gate report for W0 gate evaluation",
    )


def pytest_configure(config) -> None:
    global _report_path
    _report_path = config.getoption("--gate-report")
    _session["tests"] = {}
    _session["collection_errors"] = []


def _record_test_report(report, *, item_keywords: set[str] | None = None) -> None:
    nodeid = report.nodeid
    rec = _session["tests"].setdefault(
        nodeid,
        {
            "phases": {},
            "has_xfail_marker": False,
            "wasxfail": None,
            "call_outcome": None,
        },
    )
    rec["phases"][report.when] = report.outcome
    if report.when == "call":
        rec["call_outcome"] = report.outcome
        wf = getattr(report, "wasxfail", None)
        if wf:
            rec["wasxfail"] = str(wf)
        keywords = getattr(report, "keywords", {}) or {}
        if "xfail" in keywords:
            rec["has_xfail_marker"] = True
    if item_keywords and "xfail" in item_keywords:
        rec["has_xfail_marker"] = True


def pytest_runtest_logreport(report) -> None:
    if report.when not in ("setup", "call", "teardown"):
        return
    _record_test_report(report)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    if report.when not in ("setup", "call", "teardown"):
        return
    _record_test_report(report, item_keywords=set(item.keywords))


def pytest_collectreport(report) -> None:
    if report.failed:
        longrepr = str(report.longrepr) if report.longrepr else "collection_failed"
        _session["collection_errors"].append(
            {
                "nodeid": getattr(report, "nodeid", None),
                "outcome": report.outcome,
                "detail": longrepr[:2000],
            }
        )


def pytest_sessionfinish(session, exitstatus) -> None:
    if not _report_path:
        return
    payload = {
        "version": GATE_REPORT_VERSION,
        "valid": True,
        "exitstatus": int(exitstatus),
        "collection_errors": list(_session["collection_errors"]),
        "tests": _session["tests"],
    }
    path = Path(_report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
