# 淘天 BSR 周度自动化 Workflow

## 目标

对齐亚马逊战略周报仓库的生产化边界：根目录提供可调度入口、配置模板、测试和治理说明；项目级 skill 继续承载淘天 BSR 查询、报告渲染和飞书 Base 写入实现。

## 推荐调度

- 时区：Asia/Shanghai
- 频率：每周一 10:00
- RRULE：`FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0;BYSECOND=0`
- 默认命令：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py
```

默认命令不会写入飞书 Base。写入阶段应由人工确认报告后，带审批文件执行。
未显式传入 `--date` 时，生产运行只从 Doris 查询最新报告日期，不读取本地旧 `tool-results` 推断日期。`--dry-run` 必须显式传入 `--date`。

## 阶段

1. `sync`：同步 Doris 源数据到目标周表。
2. `query`：生成 `new_products.json`、`up_products.json`、`down_products.json` 和 `summary_counts.json`。
3. `render_report`：生成本地 Markdown 快报；`summary_counts.json` 缺失或缺类目计数时失败退出。
4. `history_base`：可选，写入历史全量 Base 日期表。需要审批文件。
5. `independent_base`：可选，复制/写入/核验独立日期 Base。需要审批文件。
6. `summary`：写出 `logs/tt-bsr-weekly-workflow/<run_id>/summary.json` 和 `run-report.md`。

## 审批文件

写入类参数必须显式传入 `--approval-file`。文件格式：

```json
{
  "approved": true,
  "report_date": "2026-06-15"
}
```

`report_date` 必须与命令中的 `--date` 或本次自动解析出的报告日期一致。审批文件不应提交到仓库。
根 wrapper 和 skill 内直接写入脚本都会校验审批文件；`--yes` 不能替代审批。

## 常用命令

安全演练：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --dry-run
```

跳过同步，只重新查询和渲染：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --skip-sync
```

审批后写 Base：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --approval-file /path/to/approval.json \
  --write-history-base \
  --sync-independent-base \
  --yes
```

## 验收标准

- 根目录测试通过：`python3 -m pytest -q`
- 编译检查通过：`python3 -m compileall -q .agents tests`
- 运行摘要不包含明文 token、密码或 Base URL token。
- 失败摘要返回非零状态，便于调度器报警。
- Base 写入必须经过审批文件门禁。
