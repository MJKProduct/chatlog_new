from __future__ import annotations

from pathlib import Path

from wechat_automation.cli.gate_eval import (
    evaluate_gate_from_run,
    evaluate_gate_verdict,
    load_structured_report,
    run_pytest_for_gate,
)

ROOT = Path(__file__).resolve().parents[1]


def _nodeid_from_report(report_path: Path, func: str) -> str:
    data = load_structured_report(report_path)
    assert data and data.get("tests")
    for nodeid in data["tests"]:
        if nodeid.endswith(f"::{func}"):
            return nodeid
    raise AssertionError(f"no nodeid ending with ::{func} in {report_path}")


def _run_tmp_gate(tmp_path: Path, filename: str, body: str, func: str) -> dict:
    test_file = tmp_path / filename
    test_file.write_text(body, encoding="utf-8")
    report = tmp_path / "gate_report.json"
    run = run_pytest_for_gate(ROOT, [str(test_file)], report, repo_root=ROOT)
    nodeid = _nodeid_from_report(report, func)
    return evaluate_gate_from_run(run, frozenset({nodeid}))


def test_c4_gate_matrix_passes_on_happy_subset(tmp_path: Path) -> None:
    body = """
def test_required_pass():
    assert True
"""
    verdict = _run_tmp_gate(tmp_path, "test_happy.py", body, "test_required_pass")
    assert verdict["gate_pass"] is True
    assert not verdict["blocked_reasons"]


def test_c4_gate_matrix_blocks_missing_required(tmp_path: Path) -> None:
    body = """
def test_required_pass():
    assert True
"""
    test_file = tmp_path / "test_happy.py"
    test_file.write_text(body, encoding="utf-8")
    report = tmp_path / "gate_report.json"
    run = run_pytest_for_gate(ROOT, [str(test_file)], report, repo_root=ROOT)
    nodeid = _nodeid_from_report(report, "test_required_pass")
    missing_id = "tests/does_not_exist.py::test_missing"
    verdict = evaluate_gate_from_run(run, frozenset({missing_id, nodeid}))
    assert verdict["gate_pass"] is False
    assert "required:tests/does_not_exist.py::test_missing:missing" in verdict["blocked_reasons"]


def test_c4_gate_matrix_blocks_skip(tmp_path: Path) -> None:
    body = """
import pytest
def test_required():
    pytest.skip("gate negative")
"""
    verdict = _run_tmp_gate(tmp_path, "test_skip.py", body, "test_required")
    nodeid = next(k for k, v in verdict["per_required_violations"].items() if v == "skipped")
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][nodeid] == "skipped"


def test_c4_gate_matrix_blocks_xfail(tmp_path: Path) -> None:
    body = """
import pytest
@pytest.mark.xfail(reason="expected fail")
def test_required():
    assert False
"""
    verdict = _run_tmp_gate(tmp_path, "test_xfail.py", body, "test_required")
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][
        next(iter(verdict["per_required_violations"]))
    ] in ("xfail", "phase_call_skipped")


def test_c4_gate_matrix_blocks_strict_xpass(tmp_path: Path) -> None:
    body = """
import pytest
@pytest.mark.xfail(strict=True, reason="gate negative")
def test_required():
    assert True
"""
    verdict = _run_tmp_gate(tmp_path, "test_xpass_strict.py", body, "test_required")
    assert verdict["gate_pass"] is False


def test_c4_gate_matrix_blocks_non_strict_xpass(tmp_path: Path) -> None:
    body = """
import pytest
@pytest.mark.xfail(strict=False, reason="negative probe")
def test_required():
    assert True
"""
    verdict = _run_tmp_gate(tmp_path, "test_xpass_loose.py", body, "test_required")
    nodeid = next(k for k, v in verdict["per_required_violations"].items() if v == "xpass")
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][nodeid] == "xpass"


def test_c4_gate_matrix_blocks_collection_error(tmp_path: Path) -> None:
    bad = tmp_path / "test_collect_error.py"
    bad.write_text("syntax error !!!", encoding="utf-8")
    report = tmp_path / "gate_report.json"
    run = run_pytest_for_gate(ROOT, [str(bad)], report, repo_root=ROOT)
    nodeid = "tests/does_not_exist.py::test_required"
    verdict = evaluate_gate_from_run(run, frozenset({nodeid}))
    assert verdict["gate_pass"] is False
    assert run.returncode != 0 or verdict.get("collection_errors")


def test_c4_gate_matrix_blocks_setup_error(tmp_path: Path) -> None:
    body = """
import pytest
@pytest.fixture
def blow():
    pytest.fail("setup")
def test_required(blow):
    assert True
"""
    verdict = _run_tmp_gate(tmp_path, "test_setup_fail.py", body, "test_required")
    nodeid = next(
        k for k, v in verdict["per_required_violations"].items() if v == "phase_setup_failed"
    )
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][nodeid] == "phase_setup_failed"


def test_c4_gate_matrix_blocks_teardown_error(tmp_path: Path) -> None:
    body = """
import pytest
@pytest.fixture
def blow(request):
    def fin():
        pytest.fail("teardown")
    request.addfinalizer(fin)
    yield
def test_required(blow):
    assert True
"""
    verdict = _run_tmp_gate(tmp_path, "test_teardown_fail.py", body, "test_required")
    nodeid = next(
        k for k, v in verdict["per_required_violations"].items() if v == "phase_teardown_failed"
    )
    assert verdict["gate_pass"] is False
    assert verdict["per_required_violations"][nodeid] == "phase_teardown_failed"


def test_c4_gate_matrix_blocks_corrupt_report() -> None:
    verdict = evaluate_gate_verdict(
        {"valid": False, "tests": {}, "collection_errors": []},
        frozenset({"tests/x.py::test_a"}),
        pytest_exit_code=0,
        pytest_counts={"passed": 1, "failed": 0, "skipped": 0, "xpassed": 0, "xfailed": 0, "collected": 1},
    )
    assert verdict["gate_pass"] is False
    assert "structured_report_invalid" in verdict["blocked_reasons"]


def test_c4_gate_matrix_blocks_missing_report() -> None:
    verdict = evaluate_gate_verdict(
        None,
        frozenset({"tests/x.py::test_a"}),
        pytest_exit_code=0,
        pytest_counts={"passed": 0, "failed": 0, "skipped": 0, "xpassed": 0, "xfailed": 0, "collected": 0},
    )
    assert verdict["gate_pass"] is False
    assert "structured_report_missing" in verdict["blocked_reasons"]
