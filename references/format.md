# 快照 JSON 格式速查

`detect` 命令读取的快照结构：

```json
{
  "tasks": [
    {
      "id": "1",
      "subject": "任务标题",
      "description": "任务描述，可多句。以'结果/完成/产出/交付/结论'开头的句子会被优先纳入简介。",
      "status": "completed",
      "owner": "可选，负责人"
    }
  ]
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 字符串，任务唯一标识；脚本按它做增量 diff，**生命周期内勿变更** |
| `subject` | 是 | 任务标题，作为简介头条 |
| `description` | 否 | 自由文本；简介压缩取前 1–2 句 |
| `status` | 否 | 默认 `pending` |
| `owner` | 否 | 仅记录，不影响检测 |

## status 枚举

| 值 | 含义 | delta 标记 |
|----|------|-----------|
| `pending` | 待处理 | （出现在待处理区） |
| `in_progress` | 进行中 | 🔄 PROG（状态变更时） |
| `completed` | 已完成 | ✅ DONE（状态变更时） |
| `deleted` | 已移除 | 🗑 RM（从快照消失时） |

## delta 输出约定

- 无变化：stdout 为空（退出码 0）。
- 新任务：`🆕 NEW   #id subject`
- 完成：`✅ DONE  #id subject  (旧→completed)`
- 状态变更：`🔄 PROG  #id subject  (旧→新)`
- 移除：`🗑 RM    #id subject`

## 状态目录产物

| 文件 | 作用 |
|------|------|
| `state.json` | 上一次快照（id → {status, subject, description}） |
| `briefs.json` | 已生成简介缓存（id → 文本），永不重算未变任务 |
| `progress.md` | 实时进度报告，每次 detect 重写 |
