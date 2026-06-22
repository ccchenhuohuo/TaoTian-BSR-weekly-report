---
name: TT-bsr-ranking-report
description: 淘天BSR榜单监测快报。每周手动执行，查询最新数据周期内九个类目组合的BSR榜单异动快报，支持新上榜、排名上升、排名下降等异动分析，可自动同步到飞书Base多维表格。
version: 1.0.0
author: chenyu
tags: [电商, BSR, 淘天, 飞书, 数据分析]
platforms:
  - Codex
---

# 淘天BSR榜单监测快报

## 环境要求

- Python 版本：Python 3.11+
- 依赖库：pymysql
- 飞书 CLI：建议 lark-cli 1.0.56+（服务器统一通过 `LARK_CLI_BIN=/usr/local/bin/lark-cli` 指定；独立 Base 侧边栏文件夹自动改名需 `base-block-*` 命令）

## 快速开始

```bash
# 服务器定时调度统一使用项目根 wrapper
python3 .agents/workflows/run_tt_bsr_weekly_workflow.py

# 检查数据同步状态
cd .agents/skills/TT-bsr-ranking-report
python3 scripts/sync_data.py --check-only
```

### 总控脚本使用方法

服务器定时调度统一使用项目根目录 `.agents/workflows/run_tt_bsr_weekly_workflow.py`，它负责隔离输出目录、写出 `summary.json` / `run-report.md`、统一审批门禁和调度器可观测性。

`scripts/run_weekly_bsr.py` 是 skill 内低层兼容入口。默认执行安全流程：Doris 同步、解析最新报告日期、查询报告数据、渲染 Markdown，并写出 `tool-results/<YYYYMMDD>/run_weekly_bsr_summary.json`。飞书流程总结和 Base 写入需要显式开启；`--send-summary` 需要 `--report-chat-id` 或 `LARK_REPORT_USER_ID`。飞书消息只发送任务流程总结，不发送报告明细数据。

总控脚本会记录 `lark-cli` 版本、检查关键 OAuth scope、聚合子流程摘要，并支持慢网络下恢复：

- `--resume`：读取已有 `run_weekly_bsr_summary.json`，跳过已成功步骤。
- `--from-step sync|query|render_report|history_base|independent_base|send_summary`：从指定步骤继续。
- 飞书 CLI 调用默认带重试和较长超时，适配跨境/VPS 出口造成的慢响应。

```bash
# 安全默认：同步 + 查询 + 渲染报告
python3 scripts/run_weekly_bsr.py

# 指定日期，跳过同步，仅重新生成报告
python3 scripts/run_weekly_bsr.py --date 2026-04-13 --skip-sync

# 任务完成后发送流程总结到指定聊天
python3 scripts/run_weekly_bsr.py --send-summary --report-chat-id "oc_xxx"

# 完整写入历史 Base 和独立 Base，适合确认配置后用于调度
python3 scripts/run_weekly_bsr.py \
  --send-summary \
  --write-history-base \
  --sync-independent-base \
  --template-base-token <上一期独立BaseToken> \
  --approval-file /secure/path/tt-bsr-approval.json \
  --yes
```

### 兼容主脚本使用方法

`scripts/main.py` 提供完整流程引导，支持多种数据输入方式：

```bash
# 完整流程（先执行同步，再自动查询当期数据文件）
python3 scripts/main.py --date 2026-04-13

# 仅检查同步状态
python3 scripts/main.py --date 2026-04-13 --check-sync

# 指定数据文件路径
python3 scripts/main.py --date 2026-04-13 \
    --new-file new_products.json \
    --up-file up_products.json \
    --down-file down_products.json
```

### 独立脚本使用方法

如果需要单独执行某个步骤：

```bash
# 直接从 Doris 查询生成三份报告数据
python3 scripts/query_report_data.py --date 2026-04-13

# 生成报告（支持直接指定数据文件）
python3 scripts/generate_report_v2.py --date 2026-04-13 \
    --new-file new_products.json \
    --up-file up_products.json \
    --down-file down_products.json

# 同步到飞书Base（支持直接指定数据文件）
python3 scripts/prepare_and_write_data_v2.py --date 2026-04-13 \
    --approval-file /secure/path/tt-bsr-approval.json \
    --new-file new_products.json \
    --up-file up_products.json \
    --down-file down_products.json

# 复制、写入并核验独立日期 Base
python3 scripts/sync_independent_base.py --date 2026-04-13 \
    --template-base-token <上一期独立BaseToken> \
    --approval-file /secure/path/tt-bsr-approval.json \
    --yes
```

## 概述

分析 <DORIS_DATABASE>.<DORIS_TARGET_TABLE> 表中九个类目组合的排名异动产品，找到最新数据周期内升幅大、降幅大、新上榜的商品。

## 数据库连接

- 数据库：<DORIS_DATABASE>
- 源表：<DORIS_SOURCE_TABLE>
- 目标表：<DORIS_TARGET_TABLE>

### sync_data.py（用于数据同步）

`sync_data.py` 查询公网 MySQL 端口获取源数据，通过 subprocess 调用 `stream-load` skill 的 `stream_load.py` 执行 Stream Load 推送。JSON 数据通过 stdin 传给 `stream_load.py`，不落盘，也不使用 `--data` 大参数；调用时强制 `--chunk-size 0`，禁止大批量自动切片落盘。

| 配置项 | 值 |
|-------|---|
| Host | `<DORIS_HOST>` |
| MySQL Port | 30930 |
| Stream Load Port | 33060 |
| Username | `<DORIS_USER>` |
| Password | `<DORIS_PASSWORD>` |

> 内网地址和旧端口已废弃，不再配置或降级尝试；如需限制 Stream Load 目标，在 `.env` 中配置 `DORIS_ALLOWED_STREAM_LOAD_HOST` / `DORIS_ALLOWED_STREAM_LOAD_PORT`。

## 飞书 Base

飞书 Base 配置见 `references/schema.md` 中的「飞书 Base」章节。

## 类目组合

类目组合详见 `references/schema.md`（**后续只需修改 schema.md**）

## 执行流程

### Step 0: 数据同步检查与同步（每次执行必须先执行）

**重要：每次执行 skill 时，必须先检查源表是否有新数据需要同步，如有则立即执行同步。**

#### 0.1 检查同步状态

执行 `python scripts/sync_data.py --check-only` 查看源表和目标表的最新业务日期：

```
python scripts/sync_data.py --check-only 执行结果：
- 源表最新日期: 2026-03-23
- 目标表最新日期: 2026-03-16
→ 需要同步（差异7天）

- 源表最新日期: 2026-03-23
- 目标表最新日期: 2026-03-23
→ 无需同步，数据已是最新
```

#### 0.2 执行同步（如需要）

- **如有差异**（源表日期 > 目标表日期）：执行 `python scripts/sync_data.py` 进行同步
- **如无需同步**（源表日期 = 目标表日期）：直接进入 Step 1

> ⚠️ `main.py` 会直接调用 `sync_data.py` 做实际同步，不再只做 `--check-only`。`sync_data.py` 同步完成后会按源表行数读回目标表确认；Stream Load 未正常收尾时会先做源表解析结果与目标表双向核验，只有确认目标日期为空时才执行同库 `INSERT INTO ... SELECT ...` 兜底。

> 新版 `sync_data.py` 已支持 Stream Load 超时/未正常收尾后的安全恢复：先核验源表解析结果与目标表是否已一致；若目标日期为空，再用同库 `INSERT INTO ... SELECT ...` 兜底；最后输出双向差异核验摘要。目标日期已有部分数据但不一致时仍会停止，避免重复写入。

**⚠️ 注意：禁止删除目标表最新周期的数据，否则会导致同步状态失配。**

### Step 1: 获取最新数据周期（动态）

```sql
-- 使用 MySQL MCP 执行
SELECT MAX(business_date) AS latest_week FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
```

**⚠️ 重要：将查询结果中的 latest_week 日期值（如 '2026-03-30'）代入后续所有SQL的日期占位符。**

### Step 2: 数据查询（汇总 + 异动）

使用 Doris MCP 依次执行查询，SQL 模板已适配 Doris 语法。

**重要提示**：
- 使用 `mcp__doris__exec_query` 工具执行查询
- SQL 中不要使用末尾分号 `;`
- 数值排序使用 `search_rank + 0` 语法
- 日期占位符 `:latest_week` 替换为实际日期（如 `'2026-04-13'`）

**自动化脚本**：优先运行 `python3 scripts/query_report_data.py --date <latest_week>`，脚本会直接查询 Doris 并生成：

- `tool-results/<YYYYMMDD>/new_products.json`
- `tool-results/<YYYYMMDD>/up_products.json`
- `tool-results/<YYYYMMDD>/down_products.json`
- `tool-results/<YYYYMMDD>/summary_counts.json`

**SQL 模板位置**：`references/query_ranking_change_doris.md`（仅在脚本失败时作为人工兜底参考）

**查询顺序**：
1. 模板四：各组合数据统计（汇总）
2. 模板一：新上榜产品 (ranking_change_value = 9999)
3. 模板二：升幅较大产品 (ranking_change_value > 0 AND != 9999)
4. 模板三：降幅较大产品 (ranking_change_value < 0)

### Step 3: 用户满意度确认

**在进入 Step 4 飞书同步之前，必须主动询问用户对当前数据的满意度。**

Step 2（汇总统计 + 异动明细）查询完成后，**运行 `generate_report_v2.py` 脚本渲染报告**，然后以机器人身份向用户发送 MD 格式的报告文档，暂停等待反馈。

#### 3.1 渲染报告

运行以下命令生成报告：
```bash
python3 scripts/generate_report_v2.py --date 2026-04-06
```

渲染格式见 `references/report_render.md`，由 Step 2 查询结果填充。脚本默认读取 `tool-results/<YYYYMMDD>/` 的标准文件，不再从根目录猜测 `call_*.json`；会校验 JSON 内 `business_date` 与报告日期一致。生成的报告将自动保存到 `report_collection` 文件夹中，文件名为 `bsr_ranking_report_YYYYMMDD.md`。

#### 3.2 任务完成后发送流程总结

不要把报告样例数据或完整 Markdown 明细直接刷到飞书消息里。任务完成后，由总控脚本发送流程总结、评价和建议，消息中只包含报告路径、数据计数、步骤状态和后续建议：
```bash
python3 scripts/run_weekly_bsr.py --send-summary --report-chat-id "oc_xxx"
```

#### 3.3 用户反馈处理

- 用户选择「满意，继续同步到飞书多维表格」→ 进入 Step 4
- 用户选择「不满意，请提出修改需求」→ 等待用户补充说明理由，根据反馈调整 SQL 条件或参数后，重新执行 Step 2，再次进入 Step 3.1

**循环退出机制**：
- 同一原因连续 2 次不满意 → 提示用户「数据以 Doris 中现有数据为准，如需补充请先确认数据源头」，由用户决定是否继续同步或终止

### Step 4: 同步到飞书 Base

检查 `LARK_BASE_TOKEN` 对应历史全量 Base 中是否存在最新业务日期的表。日期表不存在是新周期首次运行的正常状态，脚本必须自动复制最近一个日期表的结构并命名为最新业务日期，然后继续写入和核验。

#### 4.1 检查目标表是否存在

```bash
lark-cli base +table-list \
  --base-token <历史BaseToken> \
  --offset 0 \
  --limit 50
```

判断逻辑：在返回的 `tables` 数组中查找 `name` 等于 latest_week（如 `2026-04-06`）的表。

- **若不存在**：使用 `lark_base_helper.create_table_by_copying_latest()` 自动复制最近一个日期表结构，创建同名日期表（见 4.2）
- **若存在**：进入 4.3 校验与裁剪

#### 4.2 自动创建表（表不存在时）

新周期首次运行时，历史全量 Base 中通常还没有当前报告日期表。这是正常情况，不应作为异常上报。

`prepare_and_write_data_v2.py` 会自动：

1. 查找历史全量 Base 中最近一个 `YYYY-MM-DD` 日期表。
2. 读取该表字段定义并创建当前报告日期表。
3. 使用新表字段顺序准备本期数据。
4. 写入后分页读回，按完整业务 key 核验记录。

只有自动建表失败、已有表数据不一致、读回失败或重复记录时，才返回非零并在流程总结中标记异常。

#### 4.3 校验与裁剪

目标表如存在，读取全部记录并与本期预期数据做完整比对：

**校验逻辑**：
1. 读取目标表全部记录（`+record-list`，`--limit 200`，翻页直到 `has_more = false`）
2. 空表：按本期数据写入
3. 非空表：按「报告周期 + 二级类目 + 三级类目 + 异动类型 + 商品链接归一化 key」与本期预期数据比对
4. 完全一致：跳过写入
5. 不一致、日期不符、重复或读回失败：直接返回非零，停止任务，避免重复追加

校验与裁剪完成后，**运行 `prepare_and_write_data_v2.py` 脚本准备和写入数据**：

```bash
python3 scripts/prepare_and_write_data_v2.py --date 2026-04-06 \
  --approval-file /secure/path/tt-bsr-approval.json
```

该脚本会智能判断是否需要写入数据：
- 如果是新创建的表 → 写入所有数据
- 如果是已存在的表且与本期预期数据完全一致 → 跳过写入数据步骤
- 如果是已存在的表但与本期预期数据不一致 → 停止任务，不自动补写或追加

> ⚠️ 历史全量 Base 不做“失败后补写”兜底；任何不一致都需要人工核验后再处理。

#### 4.4 插入数据

从 Step 2 查询到的数据中，按以下规则提取并写入目标表：

字段映射、写入规则、异动类型判断见 `references/schema.md`「飞书 Base」章节。

**批量写入**：`+record-batch-create`，单次最多 200 行，超出分批写入。

### Step 5: 复制独立日期 Base 并修正侧边栏日期文件夹

每期报告还需要一个独立日期 Base，命名为 `<YYMMDD>淘天BSR榜单异动数据统计`。优先选择最近一个已完成的独立日期报告 Base 作为模板，只复制结构，不复制内容；不要使用旧版字段较少的模板。

#### 5.1 复制结构

优先使用脚本：

```bash
python3 scripts/sync_independent_base.py --date 2026-05-25 \
  --template-base-token <上一期独立BaseToken> \
  --approval-file /secure/path/tt-bsr-approval.json \
  --yes
```

脚本会：

1. 复制上一期形如 `YYMMDD淘天BSR榜单异动数据统计` 的 Base。
2. 命名为当前业务日期对应名称，例如业务日期 `2026-05-25` 对应 `260525淘天BSR榜单异动数据统计`。
3. 复制时只保留结构和仪表盘，不复制记录内容。
4. 尝试使用 Base block API 将左侧日期文件夹重命名为当前业务日期。
5. 按视图名识别 `1` 到 `9` 九张表对应类目，写入数据并回读核验。

#### 5.2 自动修正日期文件夹（API 优先，Computer Use 兜底）

飞书复制 Base 后会保留左侧侧边栏里的模板日期文件夹名称，例如从上一期复制后仍显示 `2026-05-18`。该名称影响仪表盘分组可读性。

默认使用 `sync_independent_base.py` 内置的 Base block CLI 自动重命名。脚本会先通过 `base +base-block-list --type folder` 找到 folder block，再用 `base +base-block-rename` 将日期文件夹改为当前业务日期。只有 CLI 缺能力、缺权限或接口不可恢复失败时，才使用 Computer Use/UI 兜底。

若返回 `needs_auth_scope` 或 `needs_ui_fallback`，通常是缺少 `base:block:read` / `base:block:update` 或 block rename 相关权限，先补权限：

```bash
lark-cli auth login --scope "base:block:read base:block:update" --no-wait --json
```

补权限后重跑 `sync_independent_base.py` 或总控 `run_weekly_bsr.py --resume --from-step independent_base`。新版脚本不会因为文件夹未改名而掩盖已经成功的数据写入；该项会进入 `manual_actions`，并在飞书流程消息中提示。只有数据不一致、写入失败、重复记录等问题会作为阻断项。

Computer Use/UI 兜底操作步骤：

1. 在 Chrome 或飞书客户端打开新复制的独立 Base。
2. 用 Computer Use 读取页面，确认左侧导航包含 `全量数据`、模板日期文件夹、`1` 到 `9` 九张类目表。
3. 点击模板日期文件夹的更多菜单或直接进入重命名态，将名称改为 `latest_week` 的完整日期，例如 `2026-05-25`。
4. 若可访问性 `set_value` 变成追加文本，不要继续追加；改用系统键盘全选替换（Command+A 后输入正确日期并回车），再用 Computer Use 读回页面。
5. 只有当 Computer Use 读回左侧日期文件夹显示为当前业务日期，且页面提示已保存到云端后，才进入 5.3 写入数据。

#### 5.3 写入和核验

将 Step 2 同一批报告数据按历史拆分方式写入新 Base：

1. `1` 到 `9` 九张类目表分别写入对应类目记录。
2. `全量数据` 写入九张类目表合计的全部记录。
3. 写入后逐表分页读回，核验记录数、全量表异动类型计数、字段顺序、视图可见字段顺序。
4. 对十张表检查重复记录；重复键至少包含报告周期、二级类目、三级类目、异动类型、商品链接归一化 key。

模板字段/视图顺序校验已与核心写入解耦：记录数、重复、全量表异动类型计数属于阻断级校验；视图可见字段顺序接口超时会记录为 `deferred_validations`，不会让已完成写入误报失败。若权限允许，脚本会尝试用 `view-set-visible-fields` 自动修复视图可见字段顺序。

## 脚本文件

| 文件 | 用途 | 执行方式 |
|-----|------|---------|
| `scripts/run_weekly_bsr.py` | 周度总控入口，串联同步、查询、报告、可选飞书发送和 Base 写入 | Python 直接运行 |
| `scripts/sync_data.py` | 数据同步 | Python 直接运行 |
| `scripts/query_report_data.py` | 从 Doris 查询并生成报告输入 JSON | Python 直接运行 |
| `scripts/generate_report_v2.py` | 生成报告（增强版） | Python 直接运行 |
| `scripts/lark_base_helper.py` | 飞书Base操作辅助函数库 | 被其他脚本导入使用 |
| `scripts/prepare_and_write_data_v2.py` | 准备和写入数据到飞书Base（增强版） | Python 直接运行 |
| `scripts/sync_independent_base.py` | 复制、写入并核验独立日期 Base | Python 直接运行 |

### sync_data.py 使用方法

```bash
# 检查同步状态
python3 scripts/sync_data.py --check-only

# 自动同步（自动检测需要同步的日期，同步后自动确认）
python3 scripts/sync_data.py

# 指定日期同步
python3 scripts/sync_data.py --date 2026-03-30
```

### generate_report_v2.py 使用方法（增强版）

### query_report_data.py 使用方法

```bash
# 使用 <DORIS_TARGET_TABLE> 最新业务日期
python3 scripts/query_report_data.py

# 指定业务日期
python3 scripts/query_report_data.py --date 2026-04-06

# 指定输出目录
python3 scripts/query_report_data.py --date 2026-04-06 \
  --output-dir tool-results/20260406
```

输出文件格式与 `generate_report_v2.py`、`prepare_and_write_data_v2.py` 兼容，并额外输出 `summary_counts.json` 用于报告汇总表显示真实最新周数据量。

### generate_report_v2.py 使用方法（增强版）

```bash
# 生成报告（使用当前查询结果）
python3 scripts/generate_report_v2.py --date 2026-04-06

# 仅预览数据，不保存文件
python3 scripts/generate_report_v2.py --date 2026-04-06 --preview
```

生成的报告将自动保存到 `report_collection` 文件夹中，文件名为 `bsr_ranking_report_YYYYMMDD.md`。

### prepare_and_write_data_v2.py 使用方法（增强版）

```bash
# 仅预览数据，不写入
python3 scripts/prepare_and_write_data_v2.py --date 2026-04-06 --preview-only

# 完整流程（含预览和确认）
python3 scripts/prepare_and_write_data_v2.py --date 2026-04-06 \
  --approval-file /secure/path/tt-bsr-approval.json

# 跳过确认直接写入
python3 scripts/prepare_and_write_data_v2.py --date 2026-04-06 \
  --approval-file /secure/path/tt-bsr-approval.json \
  --yes
```

### sync_independent_base.py 使用方法

```bash
# 复制模板 Base，写入十张表并核验
python3 scripts/sync_independent_base.py --date 2026-04-06 \
  --template-base-token <上一期独立BaseToken> \
  --approval-file /secure/path/tt-bsr-approval.json \
  --yes

# 如果已经手动复制了新 Base，可直接写入该 Base
python3 scripts/sync_independent_base.py --date 2026-04-06 \
  --template-base-token <上一期独立BaseToken> \
  --new-base-token <新BaseToken> \
  --approval-file /secure/path/tt-bsr-approval.json \
  --yes
```

## 飞书 Base 操作指南

### lark-cli 兼容注意

本 workflow 当前按 `lark-cli 1.0.56` 维护：

- `+record-batch-delete` 已不可用，删除记录使用 `+record-delete --record-id ... --yes`。
- `+record-list --format json` 返回 `fields`、`data` 二维数组和 `record_id_list`，脚本需先映射成 `{"record_id": ..., "fields": {...}}` 结构后再分组、去重或删除。
- 部分命令不接受 `--json` 作为输出格式参数，读操作统一用 `--format json`；写操作的请求体参数仍使用命令定义里的 `--json '{...}'`。
- 独立 Base 复制后，`field-list` 返回的字段元数据顺序可能与模板不一致；最终以视图可见字段顺序和写入时读取到的当前表字段顺序为准。
- `+base-block-list` / `+base-block-rename` 已作为独立 Base 侧边栏日期文件夹改名主路径，需 `base:block:read` 和 `base:block:update` scope。
- `+view-get-visible-fields` / `+view-set-visible-fields` 用于模板视图可见字段顺序校验和自动修复；慢网络下该校验可延后。
- `+data-query` 用于历史全量 Base 服务端聚合校验；失败时降级为分页读回核验，不作为写入阻断。

### 字段创建

使用 `--json` 参数传递完整字段属性：

```bash
# 创建文本字段
lark-cli base +field-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{"name":"报告周期","type":"text"}'

# 创建 Select 字段（带选项）
lark-cli base +field-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{
    "name":"二级类目",
    "type":"select",
    "options":[
      {"name":"直播/摄影配件","hue":"Blue","lightness":"Lighter"},
      {"name":"手机配件","hue":"Orange","lightness":"Lighter"},
      {"name":"摄像机配件","hue":"Wathet","lightness":"Lighter"}
    ]
  }'
```

### 批量写入记录

**必须使用 `--json` 参数，格式为 `{"fields": [...], "rows": [...]}`**

```bash
# 步骤 1：先获取字段顺序（重要！）
lark-cli base +field-list \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop

# 步骤 2：按返回的字段顺序组织数据
# 假设返回的字段顺序是：["附图", "报告周期", "二级类目", ...]

# 步骤 3：批量写入（每批最多 200 条）
lark-cli base +record-batch-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{
    "fields": ["附图", "报告周期", "二级类目", "商品名称", "三级类目", "异动类型", "店铺名称", "异动值", "商品链接", "商品图片URL", "当周排名"],
    "rows": [
      [[], "2026-04-13", ["直播/摄影配件"], "商品名称", ["闪光灯 > 相机闪光灯"], ["新上榜"], "店铺名", 9999, "https://...", "https://...", 42],
      ...
    ]
  }'
```

### Select 选项值注意事项

⚠️ **重要**：选项值使用原始符号，不要使用 HTML 实体

| 错误写法 ❌ | 正确写法 ✅ |
|------------|------------|
| `闪光灯 &gt; 相机闪光灯` | `闪光灯 > 相机闪光灯` |
| `影棚设备 &gt; 影室灯` | `影棚设备 > 影室灯` |

参考脚本：`scripts/lark_base_helper.py`

### 发送流程总结到飞书

推荐通过总控脚本发送任务流程总结、评价和建议，不直接发送报告明细数据：

```bash
# 使用 bot 身份发送流程总结（指定用户）
python3 scripts/run_weekly_bsr.py --send-summary --report-user-id "<LARK_REPORT_USER_ID>"

# 使用 bot 身份发送流程总结（指定聊天）
python3 scripts/run_weekly_bsr.py --send-summary --report-chat-id "oc_xxx"
```

**注意**：飞书消息只用于告知流程质量和下一步建议；业务明细以报告文件和 Base 为准。

## 飞书 Base 操作指南

### 字段创建

使用 `--json` 参数传递完整字段属性：

```bash
# 创建文本字段
lark-cli base +field-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{"name":"报告周期","type":"text"}'

# 创建 Select 字段（带选项）
lark-cli base +field-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{
    "name":"二级类目",
    "type":"select",
    "options":[
      {"name":"直播/摄影配件","hue":"Blue","lightness":"Lighter"},
      {"name":"手机配件","hue":"Orange","lightness":"Lighter"},
      {"name":"摄像机配件","hue":"Wathet","lightness":"Lighter"}
    ]
  }'
```

### 批量写入记录

**必须使用 `--json` 参数，格式为 `{"fields": [...], "rows": [...]}`**

```bash
# 步骤 1：先获取字段顺序（重要！）
lark-cli base +field-list \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop

# 步骤 2：按返回的字段顺序组织数据
# 假设返回的字段顺序是：["附图", "报告周期", "二级类目", ...]

# 步骤 3：批量写入（每批最多 200 条）
lark-cli base +record-batch-create \
  --base-token <历史BaseToken> \
  --table-id tbliyGCiOIFjSSop \
  --json '{
    "fields": ["附图", "报告周期", "二级类目", "商品名称", "三级类目", "异动类型", "店铺名称", "异动值", "商品链接", "商品图片URL", "当周排名"],
    "rows": [
      [[], "2026-04-13", ["直播/摄影配件"], "商品名称", ["闪光灯 > 相机闪光灯"], ["新上榜"], "店铺名", 9999, "https://...", "https://...", 42],
      ...
    ]
  }'
```

### Select 选项值注意事项

⚠️ **重要**：选项值使用原始符号，不要使用 HTML 实体

| 错误写法 ❌ | 正确写法 ✅ |
|------------|------------|
| `闪光灯 &gt; 相机闪光灯` | `闪光灯 > 相机闪光灯` |
| `影棚设备 &gt; 影室灯` | `影棚设备 > 影室灯` |

参考脚本：`scripts/lark_base_helper.py`

### 发送流程总结到飞书

推荐通过总控脚本发送任务流程总结、评价和建议，不直接发送报告明细数据：

```bash
# 使用 bot 身份发送流程总结（指定用户）
python3 scripts/run_weekly_bsr.py --send-summary --report-user-id "<LARK_REPORT_USER_ID>"

# 使用 bot 身份发送流程总结（指定聊天）
python3 scripts/run_weekly_bsr.py --send-summary --report-chat-id "oc_xxx"
```

**注意**：飞书消息只用于告知流程质量和下一步建议；业务明细以报告文件和 Base 为准。

**同步流程**：查询源表数据 → 生成 JSON → 调用 stream-load skill 的 stream_load.py 执行 HTTP 推送。

## 参考文件

- `references/schema.md` - 表结构和类目组合的详细说明
- `references/query_ranking_change_doris.md` - BSR 排名异动查询 SQL 模板（配合 Doris MCP 使用）
- `references/report_render.md` - Step 3 报告渲染格式与确认选项
- `references/lark_report_doc_template.md` - 飞书云文档周对比分析报告模板（正文）
