# Plan: Wire Sidebar Filters Into All Charts

## Approach

Create a **SQL WHERE clause builder** that converts all active sidebar filter values into SQL conditions, then inject it into every chart query. This is more efficient than pandas filtering (pushes work to Snowflake, reduces data transfer) and ensures consistency.

## Helper Function Design

```python
def build_global_filters_sql():
    """Build SQL WHERE clauses from active sidebar filters."""
    clauses = []
    if f_teams:
        vals = ",".join(f"'{v}'" for v in f_teams)
        clauses.append(f"fd.deal_team_name IN ({vals})")
    if f_owners:
        vals = ",".join(f"'{v}'" for v in f_owners)
        clauses.append(f"de.display_name IN ({vals})")  # requires DIM_EMPLOYEE join
    if f_segments:
        vals = ",".join(f"'{v}'" for v in f_segments)
        clauses.append(f"dc.segment IN ({vals})")
    if f_deal_types:
        vals = ",".join(f"'{v}'" for v in f_deal_types)
        clauses.append(f"fd.deal_type IN ({vals})")
    if f_stages:
        vals = ",".join(f"'{v}'" for v in f_stages)
        clauses.append(f"fd.deal_stage IN ({vals})")
    if f_nna != (int(min_nna), int(max_nna)):
        clauses.append(f"fd.deal_net_new_arr BETWEEN {f_nna[0]} AND {f_nna[1]}")
    if f_qualified == "Yes":
        clauses.append("fd.qualified_date IS NOT NULL")
    elif f_qualified == "No":
        clauses.append("fd.qualified_date IS NULL")
    if f_closed == "Yes":
        clauses.append("fd.is_closed = TRUE")
    elif f_closed == "No":
        clauses.append("fd.is_closed = FALSE")
    if f_closed_quarters:
        vals = ",".join(f"'{v}'" for v in f_closed_quarters)
        clauses.append(f"TO_VARCHAR(DATE_TRUNC('QUARTER', fd.deal_closed_date), 'YYYY') || '-Q' || QUARTER(fd.deal_closed_date) IN ({vals})")  # or simpler format
    if f_qualify_start:
        clauses.append(f"fd.qualified_date >= '{f_qualify_start}'")
    if f_qualify_end:
        clauses.append(f"fd.qualified_date <= '{f_qualify_end}'")
    return ("\nAND " + "\nAND ".join(clauses)) if clauses else ""
```

## Injection Points

1. **Pacing** — append `{_global_filters}` after `{extra_where}` in both pacing_cutoff_sql and pacing_detail_sql
2. **Cohort** — append to base_sql and outcome_sql WHERE clauses in `load_cohort_data()` (pass filters as function args for caching)
3. **Sales Velocity** — append to velocity_sql and vel_detail_sql
4. **SDR Pipeline Health** — append to pipeline_health_sql and ph_detail_sql

## Notes

- Queries that don't join `DIM_EMPLOYEE` (velocity main, pipeline health main) need an additional join added for the owner filter, OR we handle owner filtering in pandas post-query for those. Since velocity and pipeline health already join DIM_EMPLOYEE in their detail queries, I'll add the join to the main queries too for consistency.
- The `f_closed_quarters` filter needs quarter label computation in SQL — will use the same pattern already in the codebase.
- The cohort `load_cohort_data()` is wrapped in `@st.cache_data` — the filter string must be passed as a parameter so cache invalidates on filter change.
