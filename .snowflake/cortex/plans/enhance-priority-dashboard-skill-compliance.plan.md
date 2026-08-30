# Enhancement Plan: Priority Dashboard Skill Compliance

## Overview
Transform the Priority Dashboard to fully comply with the `/streamlit-in-snowflake` skill requirements by adding:
- Standard header with author link
- $/# toggles for revenue/count switching
- Relevant filters per chart
- Breakdown options
- Enhanced raw data sections with deal-level detail
- Filter descriptions

## Current State Analysis

**What's already working:**
- Main KPIs display (Customers, ARR, NewBiz ARR)
- 2x2 Priority Dashboard grid (Sales Velocity, Conversion, Pipeline Created, CRM Hygiene)
- Global filters in sidebar
- Charts use consistent height (350px)
- Data caching with TTL
- Dark theme in config

**What's missing (per skill requirements):**
1. ❌ Author link (Guy Amitai) in header
2. ❌ $/# toggles on charts showing ARR
3. ❌ Filter description captions under charts
4. ❌ Deal-level raw data (currently showing aggregated data in some places)
5. ❌ Breakdown selectors (segment, team, etc.) defaulting to "None"
6. ❌ Chart-specific filters (not everything needs global filters)

## Implementation Plan

### Task 1: Add Standard Header with Author Link
**Location:** Lines 22-25 (after title)

**Current code:**
```python
st.title("Weekly Sales Metrics")
st.caption(
    f"Last updated: {_today.strftime('%B %d, %Y') if hasattr(_today, 'strftime') else str(_today)}"
)
```

**New code:**
```python
st.title("Weekly Sales Metrics")
st.caption("Priority metrics for sales leadership: velocity, conversion, and pipeline health.")
st.markdown(
    f"_Updated: {_today.strftime('%B %d, %Y') if hasattr(_today, 'strftime') else str(_today)}_ · "
    f"Built by [Guy Amitai](https://getport.slack.com/team/U0B4FPPESSD)"
)
st.divider()
```

**Why:** Skill requirement #5 mandates this exact pattern for every app.

---

### Task 2: Add $/# Toggles to Relevant Charts
**Applies to:** Sales Velocity, Conversion (optional), Pipeline Created

**For Sales Velocity (pri_row1_col1):**
- Add toggle above chart: `st.radio("Show", ["$ (Velocity)", "# (Deals)"], horizontal=True, key="vel_metric")`
- If "$ (Velocity)" → show current velocity chart
- If "# (Deals)" → show won deals count per week chart

**For Pipeline Created (pri_row2_col1):**
- Add toggle above chart: `st.radio("Show", ["$ (ARR)", "# (Deals)"], horizontal=True, key="pc_metric")`
- Modify query to also compute deal_count
- Switch between ARR and deal_count based on toggle

**For Conversion (pri_row1_col2):**
- Already showing conversion rate %, but could add toggle for:
  - "% (Rate)" → current conversion rate
  - "# (Counts)" → show from_count and to_count side by side

**Implementation approach:**
- Add toggle widget before each chart
- Conditionally build different chart specs based on toggle value
- Keep SQL queries fetching both metrics to avoid re-querying

---

### Task 3: Add Filter Descriptions Under Each Chart
**Pattern:** One compact line showing active filters

**Helper function:**
```python
def build_filter_caption():
    """Build compact filter description from active global filters."""
    parts = []
    if f_segments:
        parts.append(" · ".join(f_segments))
    if f_geos:
        parts.append(" · ".join(f_geos))
    if f_teams:
        parts.append(" · ".join(f_teams))
    if f_deal_types:
        parts.append(" · ".join(f_deal_types))
    if f_qualified != "All":
        parts.append(f"Qualified: {f_qualified}")
    if f_closed != "All":
        parts.append(f"Closed: {f_closed}")
    if f_closed_quarters:
        parts.append("Q: " + ", ".join(f_closed_quarters))
    return " · ".join(parts) if parts else "All deals (no filters active)"
```

**Usage under each chart:**
```python
st.caption(f"🔍 Filters: {build_filter_caption()}")
```

---

### Task 4: Enhance Raw Data Sections
**Current state:** Raw data expanders exist but some show aggregated data

**Requirements per skill:**
- Must show **deal-level rows** (one row per deal)
- Not aggregated or summary tables
- Include: deal_name, deal_id, owner, stage, close_date, ARR, and any chart-relevant columns
- Filter with same conditions as the chart above

**For Sales Velocity raw data:**
- Currently filters by quarter/week → correct
- Query should return: deal_name, sk_deal, owner_name, deal_stage, deal_closed_date, deal_total_arr, days_to_close, company_name

**For Conversion raw data:**
- Query should return deals in the "from" stage within the period, showing which ones reached the "to" stage
- Columns: deal_name, sk_deal, company_name, deal_created_date (or qualified_date), conversion_status (Y/N), conversion_date

**For Pipeline Created raw data:**
- Currently exists and looks good
- Verify it's showing individual deals, not aggregated rows

---

### Task 5: Add Breakdown Selectors
**Pattern:** Above each chart, add `st.selectbox("Break down by", ["None", "Segment", "Deal Type", "Team", ...], key="...")`

**For Sales Velocity:**
- Breakdown options: None, Segment, Team, Deal Type
- If "None" → single line per quarter (current behavior)
- If breakdown selected → multiple lines per quarter colored by breakdown dimension

**For Pipeline Created:**
- Already has a breakdown selector! ✅
- Just need to verify it defaults to "None"

**For Conversion:**
- Breakdown options: None, Segment, Team
- If breakdown selected → show separate conversion rates per segment/team

**Implementation:**
- Move breakdown selector above the chart (currently it's below for Pipeline Created)
- Default to "None"
- Modify SQL to GROUP BY the breakdown dimension when selected

---

### Task 6: Add Chart-Specific Filters
**Goal:** Small, relevant filters per chart without duplicating global filters

**Sales Velocity chart-specific filters:**
- Quarter selector (already exists ✅) 
- Week selector for drill-down (already exists ✅)
- Could add: toggle for "Include expansion deals?" (currently newbusiness only)

**Conversion chart-specific filters:**
- From/To stage selectors (already exist ✅)
- Could add: Date range override (default to last 2 quarters, allow user to pick different range)

**Pipeline Created chart-specific filters:**
- Date range slider: "Last X quarters" (currently hardcoded to last 1 quarter in one query, last 3 in another)
- Already has breakdown selector ✅

**CRM Hygiene:**
- Placeholder only, no filters needed yet

**General approach:**
- Keep chart-specific filters **above** the chart
- Make them small and relevant (not a full copy of global filters)
- Use `st.columns()` to pack multiple small filters horizontally

---

### Task 7: Ensure Consistent Chart Height
**Current state:** Already using `height=350` in all charts ✅

**Action:** Verify in review pass, no changes expected

---

### Task 8: Verify Standard dim_company Join Pattern
**Requirement from skill:**
```sql
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc
    ON fd.company_id = dc.company_id
   AND COALESCE(dc.company_name, '') NOT ILIKE '%test%'
   AND COALESCE(dc.company_name, '') != 'Port'
   AND _is_deleted = FALSE
   AND archived = FALSE
```

**Current state in app:**
- Sales Velocity: Uses `ON fd.sk_company = dc.sk_company` and has guards ✅ (but join key is sk, not company_id)
- Conversion: Uses `ON fd.sk_company = dc.sk_company` with guards ✅
- Pipeline Created: Uses `ON fd.sk_company = dc.sk_company` with guards ✅

**Question:** Is `sk_company` the correct join key or should it be `company_id`?
- Looking at line 343: `LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc ON fd.sk_company = dc.sk_company`
- This appears to be the surrogat key pattern, which is valid
- The skill example might be using `company_id` for illustration, but `sk_company` is the surrogate key approach

**Action:** Keep current join keys (`sk_company`) but verify all joins include the guard conditions. Most already have them.

---

## Implementation Order

1. **Header & author link** (quick win, lines 22-25)
2. **Filter description helper function** (add after helpers section, ~line 300)
3. **Sales Velocity enhancements:**
   - Add $/# toggle
   - Add breakdown selector
   - Add filter description caption
   - Enhance raw data query to show deal-level
4. **Conversion enhancements:**
   - Add $/# or rate/count toggle
   - Add breakdown selector
   - Add filter description caption  
   - Add raw data section (currently missing)
5. **Pipeline Created enhancements:**
   - Add $/# toggle
   - Move breakdown selector above chart
   - Add filter description caption
   - Verify raw data is deal-level (already exists)
6. **CRM Hygiene:**
   - Add filter description even for placeholder
7. **Final review pass:**
   - Verify all charts at height=350
   - Verify all dim_company joins have guards
   - Test all toggles and breakdowns

---

## SQL Query Patterns

### Pattern for $/# Toggle Queries
Instead of running two separate queries, fetch both metrics in one query:

```sql
SELECT
    DATE_TRUNC('WEEK', fd.qualified_date) AS week,
    ROUND(SUM(fd.deal_net_new_arr), 0)::INT AS arr,
    COUNT(*) AS deal_count
FROM ...
GROUP BY 1
ORDER BY week
```

Then in Python:
```python
if toggle_value == "$ (ARR)":
    y_col = "ARR"
    y_title = "ARR ($)"
else:
    y_col = "DEAL_COUNT"  
    y_title = "# of Deals"

chart = alt.Chart(df).mark_line(...).encode(
    x=...,
    y=alt.Y(f"{y_col}:Q", title=y_title),
    ...
)
```

### Pattern for Breakdown Selector
```python
breakdown_choice = st.selectbox("Break down by", ["None", "Segment", "Team"], key="breakdown_vel")

if breakdown_choice == "None":
    sql = """
    SELECT week, SUM(arr) as arr
    FROM ... GROUP BY week
    """
    # Single-line chart
else:
    breakdown_col = "dc.segment" if breakdown_choice == "Segment" else "fd.deal_team_name"
    sql = f"""
    SELECT week, {breakdown_col} as breakdown, SUM(arr) as arr
    FROM ... GROUP BY week, breakdown
    """
    # Multi-line chart with color=breakdown
```

---

## Edge Cases & Considerations

1. **Empty data states:** All charts already handle `if df.empty` → show info message ✅
2. **Filter combinations:** The `build_deal_filter_sql()` helper already builds correct WHERE clauses
3. **Widget key collisions:** Need unique keys for all new widgets (vel_metric, vel_breakdown, pc_metric, conv_metric, etc.)
4. **Performance:** All new queries should be wrapped in `@st.cache_data(ttl=900)` via existing `run_query()` ✅
5. **Date formatting:** Skill requires dates not datetimes - verify all date displays use `.strftime('%Y-%m-%d')` or similar

---

## Testing Checklist

After implementation:
- [ ] Author link appears in header and navigates to Slack
- [ ] Each $/# toggle switches between correct metrics
- [ ] Filter description shows active filters compactly
- [ ] Raw data sections show deal-level rows with all relevant columns
- [ ] Breakdown selectors default to "None" and work when changed
- [ ] All charts maintain consistent 350px height
- [ ] No DuplicateElementKey errors
- [ ] App loads without errors in fresh session
- [ ] Dark theme renders correctly

---

## Files to Modify

1. **`streamlit_app.py`** - All changes happen here
   - Line ~25: Add author link
   - Line ~300: Add filter description helper
   - Line ~320-430: Enhance Sales Velocity section
   - Line ~437-510: Enhance Conversion section
   - Line ~520-565: Enhance Pipeline Created section
   - Line ~567-572: Update CRM Hygiene placeholder

2. **`.streamlit/config.toml`** - Verify exists with dark theme (already done ✅)

---

## Post-Implementation

After all enhancements:
1. Take full-page screenshot to document new layout
2. Test each toggle and breakdown combination
3. Verify raw data sections show correct deal-level data
4. Confirm filter descriptions update when filters change

