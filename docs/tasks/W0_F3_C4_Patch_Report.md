# W0-F3-C4 门禁补丁报告

日期：2026-09-28  
输入：独立复核 `W0_F3_INDEPENDENT_REVIEW_BLOCKED_C4`  
范围：**仅 C4 非 strict XPASS 漏判及门禁负例矩阵**（C1–C3 实现保留）

## 结论

- 实施门禁（Windows 本地）：**W0_F3_C4_IMPLEMENTATION_PASS** + **INDEPENDENT_REVIEW_PENDING**
- 机器摘要：`automation/.runtime/runs/gate-f3-c4-*/w0_f3_c4_gate_summary.json`
- 结构化判定：`gate_report.json`（pytest 插件采集）+ `gate_verdict.json`（统一 `evaluate_gate_verdict`）
- 历史 F3 证据目录 **未覆盖**；新 run 使用 `gate-f3-c4-*` 前缀

## 修复摘要

| 项 | 实现 |
|---|---|
| 结构化 pytest 结果 | `src/wechat_automation/pytest_gate_report.py`（phases、wasxfail、xfail 标记、collection_errors） |
| 统一判定 | `cli/gate_eval.py` → `evaluate_gate_verdict` / `evaluate_gate_from_run` / `run_pytest_for_gate` |
| 非 strict XPASS | `call` 为 passed 且 `wasxfail`/xfail 标记 → **BLOCKED**（`xpass`）；不再依赖 JUnit |
| CLI | `cmd_gate` 仅走结构化报告；`gate-f3-c4` / `w0_f3_c4_gate_summary.json` |
| 负例矩阵 | `tests/test_w0_f3_c4_gate_matrix.py`（临时文件，断言 `gate_pass` 与阻断原因） |
| 平台 | `WINDOWS_ONLY_REQUIRED_NODEIDS` + `effective_required_nodeids()`；摘要 `windows_only_gate_evidence` |
| 探针命名 | `test_f3_probe_sequential_counter_self_check_peak_two`（进程内自检，非双进程负对照） |

## 负例矩阵（统一判定）

| 场景 | 期望 |
|---|---|
| 正常通过 | `gate_pass=true` |
| 必需项缺失 | `missing` / BLOCKED |
| skip / xfail / strict XPASS / **strict=False XPASS** | 对应 violation / BLOCKED |
| collection / setup / teardown 失败 | BLOCKED |
| 报告缺失或损坏 | BLOCKED |

## 平台说明

| 测试 | Linux 门禁 | Windows 门禁 |
|---|---|---|
| `test_f3_two_process_peak_active_one` | 跳过（非必需） | 必需 |
| `test_f3_liveness_openprocess_access_denied_unknown` | 跳过（非必需） | 必需 |
| 其余 C1–C3 + C4 矩阵 | 必需（平台无关） | 必需 |

Linux 门禁摘要须标注 `windows_only_gate_evidence: NOT_TESTED`；**不得**将 Linux 通过写成完整 Windows 并发/Win32 注入已测。

## 验证命令

```powershell
cd automation
.\.venv\Scripts\pip.exe install -e .
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m wechat_automation gate
```

## 交付

- 本报告：`docs/tasks/W0_F3_C4_Patch_Report.md`
- 复核包：`automation/.local-validation/W0_F3_C4_Review_Package.zip`
- **REAL_WECHAT_ACCEPTANCE_PENDING** / **WINDOWS_UI_NOT_TESTED** / **REAL_SEND_NOT_TESTED** 不变

---

## W0 阶段收口（追加，2026-09-29，不修订上文）

独立复核：**W0_F3_C4_INDEPENDENT_REVIEW_PASS**（C4 正负例 13 passed；结构化门禁重算 PASS）。  
离线阶段定稿：**OFFLINE_AUTOMATION_W0_PASS**。详见 [W0_Closure.md](W0_Closure.md)。
