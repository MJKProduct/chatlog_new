# Phase W0-F1 定向修正报告

日期：2026-09-28  
基线 HEAD：`a7162bca9454fa43b5950a2414670983fe180e56`  
输入：独立复核结论 `INDEPENDENT_REVIEW_BLOCKED`（F1–F7）

## 状态

```
W0_F1_IMPLEMENTATION_PASS          ← 本地 pytest 30/30（见 .runtime/runs/*/w0_f1_gate_summary.json）
INDEPENDENT_REVIEW_PENDING
OFFLINE_AUTOMATION_W0_PASS         ← 历史 W0 门禁摘要保留，未追改
REAL_WECHAT_ACCEPTANCE_PENDING
WINDOWS_UI_NOT_TESTED
REAL_SEND_NOT_TESTED
```

> 独立复核方原结论 `OFFLINE_AUTOMATION_W0_BLOCKED` 仍作历史记录；F1 修正后由新一轮独立复核确认。

## 缺陷 → 修复映射

| ID | 问题 | 修复要点 | 证据测试 |
|----|------|----------|----------|
| F1 | RUNNING 中断无恢复 | PID 存活检测 + `recover_interrupted_tasks`；started→UNKNOWN，仅 claim→PENDING | `test_f1_recover_*`, `test_f1_queue_continues_after_unknown`（**真实子进程** `_exit(23)`） |
| F2 | 身份/seq 不可靠 | Go 忠实 fixture（仅 `seq`+`isSelf` bool）；无效/缺失 seq→UNKNOWN；拒绝 API 外 `id` | `test_f2_*`, 回归 `test_03` |
| F3 | 补查 time 参数错误 | `format_go_time_range` 使用 `~` + ISO 秒精度 | `test_f3_*`, `test_13`, StrictChatlogStub |
| F4 | 游标未按会话隔离 | `backfill_checkpoint_name(talker, query_sig)` | `test_f4_checkpoint_isolated_per_talker` |
| F5 | 门禁/测试覆盖 | 新增 F1 定向用例；gate 从 pytest 输出采集计数 | `test_w0_f1_fixes.py`, `cmd_gate` |
| F6 | 模式/executor 未严关 | 仅 `offline+simulation+mock`；mock outcome 枚举；补查强制 transport | `test_f6_*`, `test_15` |
| F7 | demo/gate 覆盖证据 | `run_id` 目录；latest 指针；**不覆盖** `w0_gate_summary.json` | `runtime_paths.py`, `demo/scenarios.py` |

## 仍待验证（未声称通过）

- Windows 专用 spawn/terminate 路径（本机为 Windows Python 3.14，子进程测试已跑；Linux 复核结果不等价）
- 真实 chatlog HTTP、Webhook 真机载荷
- 真实微信 UI / 发送

## 运行

```powershell
cd automation
.\.venv\Scripts\Activate.ps1
python -m pytest -q tests
python -m wechat_automation gate
```

复核包：`automation/.local-validation/W0_F1_Review_Package.zip`（若已生成）。

---

## W0 阶段收口（追加，2026-09-29，不修订上文）

F1 结论保留；离线阶段最终定稿见 [W0_Closure.md](W0_Closure.md)（**OFFLINE_AUTOMATION_W0_PASS**）。
