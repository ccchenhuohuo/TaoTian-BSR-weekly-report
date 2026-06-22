# BSR 榜单异动数据配置

## 数据库连接

- 数据库：<DORIS_DATABASE>
- 源表：<DORIS_SOURCE_TABLE>
- 目标表：<DORIS_TARGET_TABLE>

## 九个类目组合

| # | 二级类目 | 三级类目 | 备注 |
|---|---------|---------|------|
| 1 | 直播/摄影配件 | 闪光灯 > 相机闪光灯 | 灯光类 |
| 2 | 直播/摄影配件 | 影棚设备 > 影室灯 | 灯光类 |
| 3 | 直播/摄影配件 | 影棚设备 > 外拍灯 | 灯光类 |
| 4 | 手机配件 | 手机直播配件 > 手机直播补光灯 | 灯光类 |
| 5 | 手机配件 | 手机支架/手机座 | 脚架类 |
| 6 | 手机配件 | 手机直播配件 > 直播专用支架 | 脚架类 |
| 7 | 直播/摄影配件 | 脚架/云台 > 脚架 | 脚架类 |
| 8 | 摄像机配件 | ''（空字符串）或 '摄像机配件' | 脚架类 |
| 9 | 手机配件 | 手机拍照配件 > 自拍杆/架 | 脚架类 |

## <DORIS_TARGET_TABLE> 表结构

| 字段名 | 数据类型 | 说明 |
|--------|----------|------|
| business_date | DATETIME | 业务日期(周) |
| commodity_id | VARCHAR(255) | 商品ID |
| primary_industry | VARCHAR(255) | 一级行业 |
| secondary_category | VARCHAR(255) | 二级类目 |
| tertiary_category | VARCHAR(255) | 三级类目 |
| shop_name | VARCHAR(255) | 店铺名称 |
| commodity_name | VARCHAR(512) | 商品名称 |
| commodity_picture | VARCHAR(512) | 商品图片URL（36x36 → 600x600） |
| commodity_link | VARCHAR(512) | 商品链接 |
| search_rank | VARCHAR(255) | 搜索排名 |
| ranking_change_value | INT | 排名变化值 |
| gather_time | DATETIME | 采集时间 |

## 源表关键字段

| 字段名 | 说明 |
|--------|------|
| primary_industry | 一级行业 |
| secondary_category | 二级类目 |
| tertiary_category | 三级类目 |
| shop_name | 店铺名称 |
| commodity_id | 商品ID |
| commodity_name | 商品名称 |
| commodity_picture | 商品图片URL（将URL中的 `_36x36.jpg` 替换为 `_600x600.jpg`） |
| commodity_link | 商品链接 |
| search_rank | 搜索排名 |
| business_date | 业务日期 |
| ranking_changes | 排名变化字符串（解析规则：9999=新上榜，>0=升，<0=降，0=持平） |

## ranking_change_value 含义

| 值 | 含义 |
|----|------|
| 9999 | 新上榜 |
| > 0 | 升XX名 |
| < 0 | 降XX名 |
| 0 | 持平 |

**数据类型说明**：该字段在数据库中通常为 INT 类型。若存储为 VARCHAR/字符串类型，SQL 排序时应使用 `ORDER BY ranking_change_value + 0` 或 `ORDER BY CAST(ranking_change_value AS SIGNED)` 以确保按数值正确排序。

## 飞书 Base

### 目标 Base

| 配置项 | 值 |
|-------|---|
| Base Token | `<LARK_BASE_TOKEN>` |
| URL | `<FEISHU_BASE_URL>` |
| 表名命名规则 | `YYYY-MM-DD`（业务日期） |

### 目标表字段（字段映射）

| 目标字段 | 数据来源 | 类型 |
|---------|---------|------|
| 报告周期 | latest_week（如 `2026-04-06`） | text |
| 二级类目 | `secondary_category` | select |
| 三级类目 | `tertiary_category` | select |
| 商品名称 | `commodity_name` | text |
| 店铺名称 | `shop_name` | text |
| 当周排名 | `search_rank` | number |
| 异动值 | `ranking_change_value` | number |
| 异动类型 | 根据 ranking_change_value 判断 | select |
| 商品链接 | `commodity_link` | text（url） |
| 商品图片URL | `commodity_picture`（36x36 → 600x600） | text |
| 附图 | — | attachment（保持为空，用户手动填写） |

### 写入规则

| 异动类型 | 规则 |
|---------|------|
| 新上榜 | 全部写入 |
| 升幅 | 按异动值降序，写入 TOP 15 |
| 降幅 | 按异动值升序（降幅大的排前），写入 TOP 10 |

### 异动类型判断

```python
if ranking_change_value == 9999:
    异动类型 = "新上榜"
elif ranking_change_value > 0:
    异动类型 = "升幅"
elif ranking_change_value < 0:
    异动类型 = "降幅"
else:
    # ranking_change_value == 0，持平，不写入飞书 Base
    跳过
```
