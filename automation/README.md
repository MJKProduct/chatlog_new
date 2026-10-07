# WeChat Automation — Phase W0 (Offline / Simulation)

独立 Python 模块，实现 **不依赖微信登录** 的离线闭环：

`模拟 chatlog 消息 → 规范化 → 持久化去重 → 规则判断 → 创建回复任务 → 串行模拟执行 → 保存结果 → 重启恢复`

> **simulation=true**：本阶段所有执行结果为 `SIMULATED_SUCCEEDED`，真实微信读取/UI/发送均为 **NOT_TESTED**。

## 环境

- Python 3.11+
- 无 uiautomation / pywin32 依赖

## Windows PowerShell 快速开始

```powershell
cd C:\Users\Lenovo\Documents\chatlog_new\automation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

### 命令

```powershell
# 离线自检（配置、SQLite 可写；不探测微信）
python -m wechat_automation doctor --offline

# 合成样例 happy path 闭环
python -m wechat_automation demo --scenario happy_path

# 重放 fixture（可选执行 worker）
python -m wechat_automation replay --fixture .local-validation\happy_path.json --run-worker

# 处理待办任务后退出
python -m wechat_automation worker --once

# 状态 JSON（含 mode / simulation 标识）
python -m wechat_automation status --json

# 离线验收门禁（pytest + 写入 .runtime/w0_gate_summary.json）
python -m wechat_automation gate
```

默认配置：`configs/offline.example.json`。运行产物写入 **`automation/.runtime/`**（已在仓库根 `.gitignore` 忽略）。

## 架构

| 模块 | 职责 |
|------|------|
| `contracts` | 内部事件、任务、执行结果 |
| `source` | chatlog 解码、Fixture、补查（HTTP stub） |
| `rules` | 会话白名单 + 文本关键词固定回复 |
| `store` | SQLite 事务、事件/任务唯一约束、游标、执行锁 |
| `scheduler` | 任务领取、串行执行、重试 |
| `executor` | `MockExecutor`（模拟）；`windows` 显式未实现 |
| `cli` | doctor / demo / replay / worker / status / gate |

## 任务状态

`PENDING` → `RUNNING` → `SIMULATED_SUCCEEDED` | `FAILED` | `UNKNOWN` | `CANCELLED`

过滤原因与任务状态分离；被忽略的消息 **不** 创建发送任务。

## 已知限制（W0）

- 不接 LLM/RAG、不做真实发送/文件/加好友/群发
- 不连接默认 `127.0.0.1` 上已有 chatlog 服务；补查仅通过注入 HTTP stub 验证
- `mode=live` 启动时报 **未实现/未验收**
- Windows 真机 UI、真实发送：**NOT_TESTED**

详细验收与审计见 `docs/tasks/Windows_WeChat_W0_Report.md`。  
W0-F1 / W0-F2 见 `docs/tasks/W0_F1_Report.md`、`docs/tasks/W0_F2_Report.md`；门禁写入 `.runtime/runs/<run_id>/`（不覆盖历史摘要）。
