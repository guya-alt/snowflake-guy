# Plan: Closed Lost Notebook Refactor

## Changes

### 1. Live SQL via `run_query()` (no hardcoded data)

Cell 1 establishes connection:
```python
import snowflake.connector
conn = snowflake.connector.connect(connection_name="default")
cur = conn.cursor()
cur.execute("USE SCHEMA PORT_ANALYTICS_PROD.DWH")

def run_query(sql):
    cur.execute(sql)
    cols = [desc[0] for desc in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)
```

User authenticates via browser when they run the notebook. No workaround needed.

### 2. Global filter: `QUALIFIED_DATE IS NOT NULL`

All 8 existing queries + the new CVR query will add:
```sql
AND f.QUALIFIED_DATE IS NOT NULL
```

This narrows the analysis to deals that actually reached qualification before closing lost — removes early-stage noise.

### 3. ARR Shrinkage: ARR at loss / ARR at qualify

New logic for section 3:
```sql
-- Get the amount value closest to (but after) the qualified date
WITH amount_at_qualify AS (
    SELECT h.DEALID, h.VALUE AS amount_val,
           ROW_NUMBER() OVER (PARTITION BY h.DEALID ORDER BY h.TIMESTAMP ASC) AS rn
    FROM RAW_PORT_EXTERNAL.AB_HUBSPOT_HISTORY.DEALS_PROPERTY_HISTORY h
    INNER JOIN FACT_DEALS f ON h.DEALID = TRY_CAST(f.DEAL_CRM_ID AS NUMBER)
    WHERE h.PROPERTY = 'amount'
      AND h.TIMESTAMP >= f.QUALIFIED_DATE
      AND TRY_TO_DECIMAL(h.VALUE, 15, 2) IS NOT NULL
)
SELECT
    DATE_TRUNC('quarter', f.DEAL_CLOSED_DATE)::DATE AS close_quarter,
    COUNT(*) AS deals_with_both,
    AVG(f.DEAL_TOTAL_ARR) AS avg_arr_at_loss,
    AVG(TRY_TO_DECIMAL(aq.amount_val, 15, 2)) AS avg_arr_at_qualify,
    AVG(f.DEAL_TOTAL_ARR / NULLIF(TRY_TO_DECIMAL(aq.amount_val, 15, 2), 0)) AS avg_ratio
FROM FACT_DEALS f
INNER JOIN amount_at_qualify aq ON aq.DEALID = TRY_CAST(f.DEAL_CRM_ID AS NUMBER) AND aq.rn = 1
...
```

If property history coverage is too thin, fallback: just show avg deal size at close (DEAL_TOTAL_ARR) trend for qualified lost deals — still useful as a shrinkage proxy.

### 4. New Section: CVR (Win Rate) by Creation Quarter Cohort

**Overall:**
```sql
SELECT
    DATE_TRUNC('quarter', f.DEAL_CREATED_DATE)::DATE AS create_quarter,
    COUNT(*) AS deals_created,
    SUM(CASE WHEN f.IS_CLOSED AND f.IS_WON THEN 1 ELSE 0 END) AS deals_won,
    ROUND(100.0 * SUM(...) / COUNT(*), 1) AS win_rate_pct
FROM FACT_DEALS f
WHERE ... AND f.QUALIFIED_DATE IS NOT NULL
GROUP BY 1
```

**Breakdowns (one chart each):**
- By Team (`DEAL_TEAM_NAME`)
- By Mega Source (`MEGA_SOURCE`)
- By ARR Bucket (`CASE WHEN DEAL_TOTAL_ARR < 10000 THEN '<$10K' ...`)

Each breakdown: stacked/grouped line chart showing win rate % per quarter per group.

### 5. Notebook Structure (18 cells total)

| # | Type | Content |
|---|------|---------|
| 0 | md | Title + description |
| 1 | code | Imports + connection + `run_query()` |
| 2 | md | Section 1 header |
| 3 | code | Region/Team query + plot |
| 4 | md | Section 2 header |
| 5 | code | Dwell time by segment + plot |
| 6 | md | Section 3 header |
| 7 | code | ARR shrinkage (loss/qualify ratio) + plot |
| 8 | md | Section 4 header |
| 9 | code | Owner changes + plot |
| 10 | md | Section 5 header |
| 11 | code | Competitive losses + plot |
| 12 | md | Section 6 header |
| 13 | code | Mega source mix + plot |
| 14 | md | Section 7 header |
| 15 | code | Qualification bar + plot |
| 16 | md | Section 8 header |
| 17 | code | Stage before close + plot |
| 18 | md | Section 9 (CVR) header |
| 19 | code | CVR overall + by Team + by Mega Source + by ARR bucket (4 subplots) |
