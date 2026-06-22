# TaoTian-BSR-weekly-report

淘天 BSR 榜单监测快报的定时自动化项目。仓库保存可复现的 workflow、项目级 skill、测试和部署说明；不保存真实凭据、飞书鉴权文件、业务日志、报告产物或历史导出结果。

## 目录

```text
.
├── .agents/
│   ├── skills/TT-bsr-ranking-report/   # 查询、渲染、飞书 Base 写入脚本
│   └── workflows/                      # 可调度入口和 runbook
├── tests/                              # 仓库级 runner 测试
├── .env.example                        # 配置模板，不含真实凭据
├── pyproject.toml                      # Python 版本、依赖和 pytest 配置
└── README.md
```

`.gitignore` 默认排除 `.env`、`logs/`、`tool-results/`、`report_collection/`、`lark-auth/`、虚拟环境和 Python 缓存。

## 安装

需要 Python 3.11+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

在 `.env` 填入 Doris 和飞书配置。Doris 表名必须通过配置注入，不在代码中固定：

```text
DORIS_DATABASE=<database>
DORIS_TARGET_TABLE=<weekly-target-table>
DORIS_SOURCE_TABLE=<raw-source-table>
```

服务器上统一使用：

```text
LARK_CLI_BIN=/usr/local/bin/lark-cli
LARKSUITE_CLI_DATA_DIR=<server lark-cli data directory>
```

## 运行

安全演练只写本地 `summary.json` 和 `run-report.md`，不执行子流程：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --dry-run
```

`--dry-run` 必须显式提供 `--date`。非 dry-run 生产运行会从 Doris 查询最新报告日期，不会从本地旧 `tool-results` 推断日期。

只读/本地产物 smoke test 可跳过同步，读取 Doris 结果并渲染 Markdown，不写飞书 Base：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --skip-sync
```

默认生产链路会先同步 Doris，再查询数据、渲染报告和写出运行摘要；不会写飞书 Base：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py
```

Base 写入需要显式审批文件，且 `report_date` 必须匹配本次运行日期：

```bash
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py \
  --date 2026-06-15 \
  --approval-file /secure/path/tt-bsr-approval.json \
  --write-history-base \
  --sync-independent-base \
  --yes
```

审批文件格式：

```json
{"approved": true, "report_date": "2026-06-15"}
```

根 wrapper 和 skill 内直接写入脚本都会执行同一审批门禁；`--yes` 只跳过交互确认，不能替代审批文件。

报告汇总表必须读取完整的 `summary_counts.json`。缺失或缺类目计数会失败退出，避免用默认值生成误导性报告。

## 调度

建议在 Asia/Shanghai 时区每周一 10:00 运行安全默认流程：

```text
FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0;BYSECOND=0
```

生产服务器部署目录建议：

```text
<REPORT_ROOT>/TaoTian-BSR-weekly-report
```

## 验证

```bash
python3 -m pytest -q
python3 -m compileall -q .agents tests
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py --date 2026-06-15 --dry-run
```

发布前需确认：

- `find . -type l` 无运行依赖软链接。
- `find . -type d -name .git` 只出现根仓库。
- 明文扫描未发现 `.env`、Base token、数据库密码、飞书 Base URL、业务日志或真实报告产物。
- GitHub 首次提交使用清理后的新根仓库历史。
