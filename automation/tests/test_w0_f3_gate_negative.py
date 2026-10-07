from __future__ import annotations

from pathlib import Path

from wechat_automation.cli.gate_eval import evaluate_gate_from_run, run_pytest_for_gate
from wechat_automation.cli.required_tests import REQUIRED_TEST_NODEIDS

ROOT = Path(__file__).resolve().parents[1]


def test_f3_gate_negative_missing_required(tmp_path: Path) -> None:
    report = tmp_path / "gate_report.json"
    run = run_pytest_for_gate(
        ROOT,
        ["tests/test_w0_acceptance.py::test_01_single_message_happy_path"],
        report,
    )
    verdict = evaluate_gate_from_run(run, REQUIRED_TEST_NODEIDS)
    assert verdict["gate_pass"] is False
    assert verdict["missing_required"]


def test_f3_gate_negative_non_strict_xpass_via_unified_eval(tmp_path: Path) -> None:
    test_file = tmp_path / "test_xpass_loose.py"
    test_file.write_text(
        """
import pytest
@pytest.mark.xfail(strict=False, reason="negative probe")
def test_required():
    assert True
""",
        encoding="utf-8",
    )
    nodeid = "test_xpass_loose.py::test_required"
    report = tmp_path / "gate_report.json"
    run = run_pytest_for_gate(ROOT, [str(test_file)], report, repo_root=ROOT)
    from wechat_automation.cli.gate_eval import load_structured_report

    nodeid = next(
        k
        for k in load_structured_report(report)["tests"]
        if k.endswith("::test_required")
    )
    verdict = evaluate_gate_from_run(run, frozenset({nodeid}))
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][nodeid] == "xpass"
