# BSR 排名异动查询 SQL 模板 (Doris 版本)

> 配合 Doris MCP (`mcp__doris__exec_query`) 使用。
> **⚠️ 使用前必须将 `:latest_week` 占位符替换为 Step 1 查询到的实际日期**，例如 `WHERE business_date = '2026-03-30'`
> **⚠️ 重要提示**：
> - SQL 中不要使用末尾分号 `;`
> - 数值排序使用 `search_rank + 0` 语法
> - 日期占位符替换为实际日期（如 `'2026-04-13'`）

## 九个类目组合

| # | 二级类目 | 三级类目 |
|---|---------|---------|
| 1 | 直播/摄影配件 | 闪光灯 > 相机闪光灯 |
| 2 | 直播/摄影配件 | 影棚设备 > 影室灯 |
| 3 | 直播/摄影配件 | 影棚设备 > 外拍灯 |
| 4 | 手机配件 | 手机直播配件 > 手机直播补光灯 |
| 5 | 手机配件 | 手机支架/手机座 |
| 6 | 手机配件 | 手机直播配件 > 直播专用支架 |
| 7 | 直播/摄影配件 | 脚架/云台 > 脚架 |
| 8 | 摄像机配件 | ''（空字符串）或 '摄像机配件' |
| 9 | 手机配件 | 手机拍照配件 > 自拍杆/架 |

---

## SQL 模板

### 模板四：各组合数据统计（汇总）

```sql
SELECT
    secondary_category, tertiary_category, COUNT(*) AS cnt
FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
WHERE business_date = :latest_week
AND (
    (secondary_category = '直播/摄影配件' AND tertiary_category = '闪光灯 > 相机闪光灯')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '影棚设备 > 影室灯')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '影棚设备 > 外拍灯')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机直播配件 > 手机直播补光灯')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机支架/手机座')
    OR (secondary_category = '手机配件' AND tertiary_category = '手机直播配件 > 直播专用支架')
    OR (secondary_category = '直播/摄影配件' AND tertiary_category = '脚架/云台 > 脚架')
    OR (secondary_category = '摄像机配件' AND (tertiary_category = '摄像机配件' OR tertiary_category IS NULL OR tertiary_category = ''))
    OR (secondary_category = '手机配件' AND tertiary_category = '手机拍照配件 > 自拍杆/架')
)
GROUP BY secondary_category, tertiary_category
ORDER BY secondary_category, tertiary_category
```

### 模板一：新上榜产品 (ranking_change_value = 9999)

```sql
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '闪光灯 > 相机闪光灯'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 影室灯'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 外拍灯'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 手机直播补光灯'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机支架/手机座'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 直播专用支架'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '脚架/云台 > 脚架'
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '摄像机配件'
    AND (tertiary_category = '摄像机配件' OR tertiary_category IS NULL OR tertiary_category = '')
    ORDER BY search_rank + 0
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value,
           '新上榜' AS 异动描述
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value = 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机拍照配件 > 自拍杆/架'
    ORDER BY search_rank + 0
    LIMIT 100
)
```

### 模板二：升幅较大产品 (ranking_change_value > 0 AND != 9999)

```sql
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '闪光灯 > 相机闪光灯'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 影室灯'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 外拍灯'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 手机直播补光灯'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机支架/手机座'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 直播专用支架'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '脚架/云台 > 脚架'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '摄像机配件'
    AND (tertiary_category = '摄像机配件' OR tertiary_category IS NULL OR tertiary_category = '')
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value > 0 AND ranking_change_value != 9999
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机拍照配件 > 自拍杆/架'
    ORDER BY ranking_change_value DESC
    LIMIT 100
)
```

### 模板三：降幅较大产品 (ranking_change_value < 0)

```sql
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '闪光灯 > 相机闪光灯'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 影室灯'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '影棚设备 > 外拍灯'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 手机直播补光灯'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机支架/手机座'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机直播配件 > 直播专用支架'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '直播/摄影配件'
    AND tertiary_category = '脚架/云台 > 脚架'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '摄像机配件'
    AND (tertiary_category = '摄像机配件' OR tertiary_category IS NULL OR tertiary_category = '')
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
UNION ALL
(
    SELECT business_date, secondary_category, tertiary_category,
           commodity_id, commodity_name, commodity_picture, commodity_link, shop_name, search_rank, ranking_change_value
    FROM <DORIS_DATABASE>.<DORIS_TARGET_TABLE>
    WHERE business_date = :latest_week
    AND ranking_change_value < 0
    AND secondary_category = '手机配件'
    AND tertiary_category = '手机拍照配件 > 自拍杆/架'
    ORDER BY ranking_change_value ASC
    LIMIT 100
)
```
