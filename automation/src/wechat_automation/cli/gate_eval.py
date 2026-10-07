from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from wechat_automation.cli.required_tests import (
    REQUIRED_TEST_NODEIDS,
    effective_required_nodeids,
)


@dataclass
class PytestGateRun:
    returncode: int
    stdout: str
    stderr: str
    report_path: Path
    log_text: str

    @property
    def counts(self) -> dict[str, int]:
        text = self.log_text
        passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", text)) else 0
        failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", text)) else 0
        skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", text)) else 0
        xpassed = int(m.group(1)) if (m := re.search(r"(\d+) xpassed", text)) else 0
        xfailed = int(m.group(1)) if (m := re.search(r"(\d+) xfailed", text)) else 0
        return {
            "collected": passed + failed + skipped + xpassed + xfailed,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "xpassed": xpassed,
            "xfailed": xfailed,
        }


def load_structured_report(report_path: Path) -> dict | None:
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"valid": False, "version": 0, "tests": {}, "collection_errors": []}
    if not isinstance(data, dict):
        return {"valid": False, "version": 0, "tests": {}, "collection_errors": []}
    data.setdefault("valid", True)
    data.setdefault("tests", {})
    data.setdefault("collection_errors", [])
    return data


def _classify_required_violation(entry: dict | None) -> str | None:
    if entry is None:
        return "missing"
    phases = entry.get("phases") or {}
    call = entry.get("call_outcome") or phases.get("call")
    for phase in ("setup", "call", "teardown"):
        outcome = phases.get(phase)
        if outcome is not None and outcome != "passed":
            if phase == "call" and entry.get("has_xfail_marker"):
                return "xfail" if outcome in ("skipped", "failed") else f"phase_{phase}_{outcome}"
            if phase == "call" and outcome == "skipped":
                return "skipped"
            return f"phase_{phase}_{outcome}"
    if entry.get("has_xfail_marker"):
        if call == "passed" or entry.get("wasxfail"):
            return "xpass"
        return "xfail"
    if call == "skipped":
        return "skipped"
    if call == "failed":
        return "failed"
    if call == "passed" and entry.get("wasxfail"):
        return "xpass"
    if call != "passed":
        return f"call_{call or 'unknown'}"
    return None


def evaluate_gate_verdict(
    report: dict | None,
    required_nodeids: Iterable[str],
    *,
    pytest_exit_code: int,
    pytest_counts: dict[str, int],
) -> dict:
    """Unified gate verdict — CLI and negative tests must use this."""
    required = frozenset(required_nodeids)
    blocked_reasons: list[str] = []
    per_required: dict[str, str | None] = {}

    tests: dict = {}
    if report is None:
        blocked_reasons.append("structured_report_missing")
    elif not report.get("valid", True):
        blocked_reasons.append("structured_report_invalid")
    else:
        if report.get("collection_errors"):
            blocked_reasons.append("collection_error")
        tests = report.get("tests") or {}

    for nodeid in sorted(required):
        violation = _classify_required_violation(tests.get(nodeid))
        per_required[nodeid] = violation
        if violation:
            blocked_reasons.append(f"required:{nodeid}:{violation}")

    if pytest_exit_code != 0:
        blocked_reasons.append(f"pytest_exit_code_{pytest_exit_code}")
    if pytest_counts.get("failed", 0) > 0:
        blocked_reasons.append("pytest_failed_count")
    if pytest_counts.get("xpassed", 0) > 0:
        blocked_reasons.append("pytest_xpassed_count")

    missing = sorted(n for n, v in per_required.items() if v == "missing")
    not_passed = sorted(n for n, v in per_required.items() if v)

    gate_pass = not blocked_reasons
    return {
        "required_nodeids": sorted(required),
        "per_required_violations": per_required,
        "missing_required": missing,
        "required_not_passed": not_passed,
        "blocked_reasons": blocked_reasons,
        "required_ok": not missing and not not_passed and "structured_report_missing" not in blocked_reasons,
        "gate_pass": gate_pass,
    }


def run_pytest_for_gate(
    cwd: Path,
    targets: list[str],
    report_path: Path,
    *,
    log_path: Path | None = None,
    junit_path: Path | None = None,
    repo_root: Path | None = None,
) -> PytestGateRun:
    report_path = report_path.resolve()
    if report_path.exists():
        report_path.unlink()
    root = (repo_root or cwd).resolve()
    env = os.environ.copy()
    src = root / "src"
    if src.is_dir():
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src) + (os.pathsep + prev if prev else "")
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *targets,
        f"--gate-report={report_path}",
        "--rootdir",
        str(root),
    ]
    if junit_path is not None:
        cmd.append(f"--junitxml={junit_path.resolve()}")
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
    log_text = proc.stdout + "\n" + proc.stderr
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(log_text, encoding="utf-8")
    return PytestGateRun(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        report_path=report_path,
        log_text=log_text,
    )


def evaluate_gate_from_run(
    run: PytestGateRun,
    required_nodeids: Iterable[str] | None = None,
) -> dict:
    required = required_nodeids if required_nodeids is not None else effective_required_nodeids()
    report = load_structured_report(run.report_path)
    verdict = evaluate_gate_verdict(
        report,
        required,
        pytest_exit_code=run.returncode,
        pytest_counts=run.counts,
    )
    verdict["pytest"] = run.counts
    verdict["structured_report_path"] = str(run.report_path)
    verdict["report_loaded"] = report is not None and report.get("valid", True)
    if report:
        verdict["collection_errors"] = report.get("collection_errors", [])
        verdict["session_exitstatus"] = report.get("exitstatus")
    return verdict


def evaluate_required_xpass_probe(report_path: Path, required_nodeid: str) -> dict:
    """Minimal repro helper for non-strict XPASS (structured report only)."""
    report = load_structured_report(report_path)
    return evaluate_gate_verdict(
        report,
        frozenset({required_nodeid}),
        pytest_exit_code=0,
        pytest_counts={"collected": 1, "passed": 0, "failed": 0, "skipped": 0, "xpassed": 1, "xfailed": 0},
    )


# Legacy JUnit parse — not used for gate pass/fail (C4).
def evaluate_required(junit_path: Path, required_nodeids: Iterable[str]) -> dict:
    required = frozenset(required_nodeids)
    return {
        "outcomes": {},
        "missing_required": sorted(required),
        "required_not_passed": sorted(required),
        "required_ok": False,
        "gate_pass": False,
        "blocked_reasons": ["junit_only_evaluation_disabled_use_structured_report"],
        "note": "Gate must use evaluate_gate_from_run / structured report (W0-F3-C4)",
    }
