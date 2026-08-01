# ai-task-detector

**Token-minimal AI task completion detector** — 自动检测 AI 任务完成情况，并依据任务内容自动生成简要介绍，随开发进度实时更新，同时把额外 token 消耗压到最低。

> A WorkBuddy skill. All diffing and brief-intro generation run locally in pure Python, so the LLM only reads a tiny delta instead of re-reading the whole task history.

## 它能做什么

- **自动检测任务完成情况**：对比上一次任务快照，只输出变化的几行（新任务 / 完成 / 状态变更 / 移除）。
- **按内容自动生成简要介绍**：每个完成的任务生成一句简介（标题 + 描述摘要），按任务 id 缓存，未变任务永不重算。
- **实时更新进度**：每次检测重写 `progress.md` 实时简报，可直接交付给用户。
- **最小 token 消耗**：默认模板化生成简介，不调用大模型；脚本本地做增量 diff。

## 安装

**方式 A — 解压安装（用户级，跨项目可用）**

将本仓库的 `ai-task-detector/` 目录（含 `SKILL.md`、`scripts/`、`references/`）放到：

```
~/.workbuddy/skills/ai-task-detector/
```

**方式 B — 从 zip 安装**

使用打包好的 `ai-task-detector.zip`（见 Releases），解压到 `~/.workbuddy/skills/` 即可。

## 使用

```bash
# 1. 初始化状态目录（每个项目一次）
python scripts/task_detector.py init --state-dir .ai_task_detector

# 2. 在每次 TaskUpdate / 里程碑后，喂入任务快照，实时检测
python scripts/task_detector.py detect --snapshot snap.json --state-dir .ai_task_detector

# 3. 查看面向用户的实时进度报告
python scripts/task_detector.py report --state-dir .ai_task_detector --cat
```

快照 JSON 格式（`snap.json`）：

```json
{
  "tasks": [
    {"id": "1", "subject": "搭建登录页",
     "description": "实现表单与校验。结果：登录接口联调通过。",
     "status": "completed"}
  ]
}
```

`status` 取值：`pending` | `in_progress` | `completed` | `deleted`。
完整字段说明见 [`references/format.md`](references/format.md)。

## 命令

| 命令 | 作用 |
|------|------|
| `init`   | 创建状态目录与空状态 |
| `detect` | 读取快照（或 stdin），增量 diff，刷新简介与 `progress.md`，仅输出变更行 |
| `report` | 打印 `progress.md` 路径或内容（`--cat`） |
| `reset`  | 清空状态目录 |

## 省 token 的设计

1. **增量 diff 只在脚本里算**：只输出变化行，LLM 不读全量历史。
2. **简介按任务缓存**：生成一次存入 `briefs.json`，未变任务永不重算。
3. **模板化生成，零模型调用**：默认用规则压缩描述成简介，不调大模型。
4. **进度报告写文件**：`progress.md` 由脚本重写，LLM 不必读进上下文。

## License

MIT
