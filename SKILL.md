---
name: ai-task-detector
description: 'Auto-detect AI task completion and generate a brief per-task intro with near-zero extra token cost. Use when an agent works through a task list and needs to (1) know which tasks just changed, (2) produce a concise human-readable summary of each finished task, and (3) keep a live progress report updated in real time, without re-reading full task history or re-summarizing each step. Trigger phrases: "track task progress", "auto-summarize completed tasks", "实时任务进度", "自动生成任务简介", "minimal-token task monitor".'
agent_created: true
---

# AI 任务自动检测工具（ai-task-detector）

## 目的

在 AI 逐步执行任务的过程中，**自动检测任务完成情况**，并**依据任务内容自动生成简要介绍**，
随开发进度**实时更新**，同时把额外 token 消耗压到最低。

核心思想：所有"重活"（任务快照 diff、简介生成）都用纯 Python 脚本在本地完成，
LLM 只需要喂入一份结构化的小快照、读回一个**仅含变更行的紧凑 delta**。
这样 LLM 既不需要回看完整任务历史，也不需要在每一步重新总结。

## 何时使用

- 正在用任务列表（`TaskCreate` / `TaskUpdate` / `TaskList`）推进多步工作。
- 希望对外（用户 / 看板）实时展示"已完成什么、做到哪了"。
- 希望每个完成的任务自动生成一句简洁介绍，但**不愿为每次更新多花 token**。
- 触发语示例：「跟踪任务进度」「自动总结完成的任务」「实时任务进度」「最小 token 监控」。

## 为什么 token 消耗最小

1. **Diff 只在脚本里算**：脚本对比上一次快照，只输出变化的几行，LLM 不读全量。
2. **简介按任务缓存**：每个任务的简介生成一次后存入 `briefs.json`，后续永不重算。
3. **模板化生成，零模型调用**：默认用规则（取任务标题 + 描述前两句 / 结果句）生成简介，
   不调用大模型。仅在内容确实模糊、需要润色时，才由 LLM 可选地补一句——且默认关闭。
4. **进度报告是写文件**：`progress.md` 由脚本重写，LLM 不必把它读进上下文。

## 工作流程

### 1. 初始化（每个项目一次）

```bash
python <skill>/scripts/task_detector.py init --state-dir .ai_task_detector
```

状态目录默认 `.ai_task_detector`，内含 `state.json` / `briefs.json` / `progress.md`。
可换路径，例如放到 `.workbuddy/ai_task_detector`。

### 2. 组装快照（轻量，结构化）

在 Write/Edit **之前**或之后，把当前任务状态整理成一份小 JSON（结构化、几乎不占 token）：

```json
{
  "tasks": [
    {"id": "1", "subject": "搭建登录页", "description": "完成表单与校验。结果：登录接口联调通过。",
     "status": "completed", "owner": "fe-dev"},
    {"id": "2", "subject": "编写单元测试", "description": "覆盖核心分支", "status": "in_progress"}
  ]
}
```

- `status` 取值：`pending` | `in_progress` | `completed` | `deleted`
- 只需要"受影响的任务"，不必每次全量；脚本按 `id` 做增量 diff。
- 该 JSON 可直接 `TaskList`/`TaskGet` 后由 LLM 快速拼出（结构化，成本极低）。

### 3. 检测 + 实时更新（关键步骤）

```bash
python <skill>/scripts/task_detector.py detect \
  --snapshot /path/to/snapshot.json --state-dir .ai_task_detector
```

脚本会：
- 对比上一次快照，计算增量；
- 为每个新完成的 / 进行中的任务生成（并缓存）简介；
- 重写 `progress.md`（实时进度报告）；
- **仅把变更行打印到 stdout**，例如：

```
✅ DONE  #1 搭建登录页  (in_progress→completed)
🆕 NEW   #3 补充 API 文档
🔄 PROG  #2 编写单元测试  (pending→in_progress)
```

**没有变化时，stdout 为空**（退出码仍为 0）——这就是"实时但零噪声"。
LLM 只需看这几行就知道发生了什么，无需回看历史。

集成节奏（实现"跟随 AI 开发而实时更新"）：在每次 `TaskUpdate`（状态变更）或自然里程碑后，
立即跑一次 `detect`。把它的 stdout delta 当作进度信号即可。

### 4. 查看 / 交付进度报告

```bash
python <skill>/scripts/task_detector.py report --state-dir .ai_task_detector --cat
```

`progress.md` 即面向用户的实时简报，结构为：总览计数 → 已完成（带简介）→ 进行中 → 待处理。
可直接 `present_files` 交给用户，或嵌入最终回复。

### 5. 重置（可选）

```bash
python <skill>/scripts/task_detector.py reset --state-dir .ai_task_detector
```

## 简介生成规则（默认，无需模型）

- 标题 = `subject`。
- 摘要 = 描述压缩到前 1–2 句（每句截断 90 字），若描述包含"结果/完成/产出/交付/结论"等
  结果句则优先纳入。
- 尾部追加 `状态 · 更新时间`。
示例（任务 #1 描述"完成表单与校验。结果：登录接口联调通过。"）：

```
### 搭建登录页
完成表单与校验。结果：登录接口联调通过。
- 状态：`completed` · 更新：2026-07-19 13:xx UTC
```

## 资源

- `scripts/task_detector.py` — 纯标准库 Python，零依赖；命令 `init` / `detect` / `report` / `reset`。
  支持 `--snapshot FILE` 或直接管道 stdin 读取快照。
- `references/format.md` — 快照 JSON 字段与状态枚举的速查表。

## 注意事项

- 脚本只认 `id` 做增量，请勿在任务生命周期内复用/变更 `id`。
- 默认不调用大模型；如需更"像人写"的简介，在 `detect` 报告新完成后，可选地对单条任务
  让 LLM 润色一句并写回 `briefs.json`（非必须，会额外消耗 token）。
- 状态目录建议加入 `.gitignore`（属运行时产物，非源码）。
