import streamlit as st
import os
import re
import pandas as pd
import numpy as np

st.set_page_config(page_title="NRR Cohort Analysis", layout="wide")
st.title("NRR Cohort Analysis")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()

GRANULARITY_OPTIONS = ["Quarterly", "Monthly", "Yearly"]
VIEW_OPTIONS = ["NRR", "Logo"]
BREAKDOWN_OPTIONS = ["None", "Segment", "Owner", "Industry", "Eng Size Group", "Geo"]


@st.cache_data(show_spinner=False)
def load_cohort_data():
    query = """
    SELECT
        d.SK_DEAL,
        d.SK_COMPANY,
        d.DEAL_NAME,
        d.DEAL_TOTAL_ARR,
        d.BASE_ARR,
        d.DEAL_CLOSED_DATE,
        d.IS_WON,
        d.DEAL_TYPE,
        d.DEAL_STAGE,
        d.PIPELINE,
        c.COMPANY_NAME,
        c.LIFECYCLE_STAGE,
        COALESCE(c.SEGMENT, 'None') AS SEGMENT,
        c.GEOGRAPHY AS GEO,
        c.INDUSTRY,
        CASE
            WHEN c.ENGINEERING_GROUP_SIZE <= 50 THEN '1-50'
            WHEN c.ENGINEERING_GROUP_SIZE <= 150 THEN '51-150'
            WHEN c.ENGINEERING_GROUP_SIZE <= 500 THEN '151-500'
            WHEN c.ENGINEERING_GROUP_SIZE <= 1000 THEN '501-1000'
            ELSE '1000+'
        END AS ENG_SIZE_GROUP,
        e.DISPLAY_NAME AS OWNER
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c
        ON d.SK_COMPANY = c.SK_COMPANY
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e
        ON d.SK_SALES_OWNER = e.SK_EMPLOYEE
    WHERE d.IS_CLOSED = TRUE
        AND d.ARCHIVED = FALSE
        AND d._DELETED_TIMESTAMP IS NULL
        AND d.DEAL_CLOSED_DATE >= '2024-01-01'
        AND (d.IS_WON = TRUE OR (d.PIPELINE = 'Renewals' AND d.DEAL_STAGE = 'Churn'))
    """
    return session.sql(query).to_pandas()


def trim_partner_name(name):
    if pd.isna(name):
        return name
    match = re.split(r'\s*[-]\s*|\s+(?=\d)', str(name), maxsplit=1)
    return match[0].strip() if match else str(name).strip()


@st.cache_data(show_spinner=False)
def prepare_base_data(_raw_df):
    df = _raw_df.copy()
    df["DEAL_CLOSED_DATE"] = pd.to_datetime(df["DEAL_CLOSED_DATE"])
    df["COHORT_ENTITY"] = df.apply(
        lambda row: row["SK_COMPANY"]
        if row["LIFECYCLE_STAGE"] == "Customer"
        else trim_partner_name(row["DEAL_NAME"]),
        axis=1,
    )
    df["DEAL_CATEGORY"] = df.apply(
        lambda row: "Churn" if row.get("DEAL_STAGE") == "Churn" else
        {"newbusiness": "New Business", "existingbusiness": "Renewal", "Expansion": "Expansion"}.get(row["DEAL_TYPE"], "Other"),
        axis=1,
    )
    df["NET_NEW_ARR"] = df["DEAL_TOTAL_ARR"] - df["BASE_ARR"].fillna(0)
    return df


if "data_loaded" not in st.session_state:
    st.session_state["data_loaded"] = False

st.sidebar.markdown("### Controls")
if st.sidebar.button("Load / Refresh Data", type="primary"):
    load_cohort_data.clear()
    prepare_base_data.clear()
    st.session_state["data_loaded"] = True

if not st.session_state["data_loaded"]:
    st.info("Click **Load / Refresh Data** in the sidebar to fetch data from Snowflake.")
    st.stop()

with st.spinner("Loading deal data..."):
    raw_df = load_cohort_data()

if raw_df.empty:
    st.warning("No closed-won deals found.")
    st.stop()

raw_df = prepare_base_data(raw_df)

col1, col2, col3 = st.columns(3)
with col1:
    granularity = st.selectbox("Granularity", GRANULARITY_OPTIONS)
with col2:
    view_type = st.selectbox("View", VIEW_OPTIONS)
with col3:
    breakdown = st.selectbox("Breakdown", BREAKDOWN_OPTIONS)

TRUNC_MAP = {"Monthly": "MONTH", "Quarterly": "QUARTER", "Yearly": "YEAR"}
trunc = TRUNC_MAP[granularity]

fcol1, fcol2, fcol3, fcol4 = st.columns(4)
with fcol1:
    segments = st.multiselect("Segment", sorted(raw_df["SEGMENT"].dropna().unique()))
with fcol2:
    owners = st.multiselect("Owner", sorted(raw_df["OWNER"].dropna().unique()))
with fcol3:
    industries = st.multiselect("Industry", sorted(raw_df["INDUSTRY"].dropna().unique()))
with fcol4:
    geos = st.multiselect("Geo", sorted(raw_df["GEO"].dropna().unique()))

st.markdown("---")

df = raw_df.copy()
if segments:
    df = df[df["SEGMENT"].isin(segments)]
if owners:
    df = df[df["OWNER"].isin(owners)]
if industries:
    df = df[df["INDUSTRY"].isin(industries)]
if geos:
    df = df[df["GEO"].isin(geos)]


def truncate_date(series, gran):
    if gran == "MONTH":
        return series.values.astype("datetime64[M]")
    elif gran == "QUARTER":
        dates = pd.to_datetime(series)
        return pd.PeriodIndex(dates, freq="Q").to_timestamp()
    else:
        return series.values.astype("datetime64[Y]")


df["PERIOD"] = pd.to_datetime(truncate_date(df["DEAL_CLOSED_DATE"], trunc))

cohort_first = df.groupby("COHORT_ENTITY")["PERIOD"].min().reset_index()
cohort_first.columns = ["COHORT_ENTITY", "COHORT"]
df = df.merge(cohort_first, on="COHORT_ENTITY", how="left")

if granularity == "Monthly":
    df["PERIODS_SINCE"] = (
        (df["PERIOD"].dt.year - df["COHORT"].dt.year) * 12
        + (df["PERIOD"].dt.month - df["COHORT"].dt.month)
    )
elif granularity == "Quarterly":
    df["PERIODS_SINCE"] = (
        (df["PERIOD"].dt.year - df["COHORT"].dt.year) * 4
        + (df["PERIOD"].dt.quarter - df["COHORT"].dt.quarter)
    )
else:
    df["PERIODS_SINCE"] = df["PERIOD"].dt.year - df["COHORT"].dt.year

current_period = pd.to_datetime(truncate_date(pd.Series([pd.Timestamp.now()]), trunc)[0])


def get_max_periods(cohort_ts):
    if granularity == "Monthly":
        return (current_period.year - cohort_ts.year) * 12 + (current_period.month - cohort_ts.month)
    elif granularity == "Quarterly":
        return (current_period.year - cohort_ts.year) * 4 + (current_period.quarter - cohort_ts.quarter)
    else:
        return current_period.year - cohort_ts.year


def format_cohort_label(ts):
    if granularity == "Monthly":
        return ts.strftime("%b %Y")
    elif granularity == "Quarterly":
        return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"
    else:
        return ts.strftime("%Y")


def fmt_arr(val):
    if abs(val) >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    elif abs(val) >= 1_000:
        return f"${val/1_000:.0f}K"
    else:
        return f"${val:,.0f}"


def compute_cohort_row(data, base_logos_override=None):
    cohort_col = "COHORT"
    period_col = "PERIODS_SINCE"
    entity_col = "COHORT_ENTITY"

    if data.empty:
        return None

    base_arr = data[data[period_col] == 0]["DEAL_TOTAL_ARR"].sum()
    base_logos = base_logos_override if base_logos_override is not None else data[data[period_col] == 0][entity_col].nunique()

    if base_arr == 0 and base_logos == 0:
        return None

    net_new_by_period = (
        data[data[period_col] > 0]
        .groupby(period_col)["NET_NEW_ARR"]
        .sum()
    )

    churn_entities_cumulative = set()
    all_entities = set(data[data[period_col] == 0][entity_col].unique())
    max_col = int(data[period_col].max()) if not data.empty else 0
    cohort_ts = data[cohort_col].iloc[0]
    max_p = get_max_periods(cohort_ts)

    churn_by_period = (
        data[data["DEAL_CATEGORY"] == "Churn"]
        .groupby(period_col)[entity_col]
        .apply(set)
    )

    pct_row = {}
    detail_row = {}
    change_map = set()

    running_arr = base_arr
    for p in range(0, max_col + 1):
        if p > max_p:
            pct_row[p] = None
            detail_row[p] = None
        elif p == 0:
            remaining_logos = base_logos
            pct_row[p] = 100.0
            detail_row[p] = {"arr": running_arr, "logos": remaining_logos}
            change_map.add(p)
        elif p in net_new_by_period.index:
            running_arr = running_arr + net_new_by_period[p]
            if p in churn_by_period.index:
                churn_entities_cumulative.update(churn_by_period[p])
            remaining_logos = len(all_entities - churn_entities_cumulative)
            pct_row[p] = round(running_arr / base_arr * 100, 1) if base_arr > 0 else None
            detail_row[p] = {"arr": running_arr, "logos": remaining_logos}
            change_map.add(p)
        else:
            if p in churn_by_period.index:
                churn_entities_cumulative.update(churn_by_period[p])
            remaining_logos = len(all_entities - churn_entities_cumulative)
            pct_row[p] = round(running_arr / base_arr * 100, 1) if base_arr > 0 else None
            detail_row[p] = {"arr": running_arr, "logos": remaining_logos}

    return {
        "base_arr": base_arr,
        "base_logos": base_logos,
        "pct_row": pct_row,
        "detail_row": detail_row,
        "change_map": change_map,
        "max_col": max_col,
    }


def get_period_label(cohort_ts, p, gran_label):
    if cohort_ts is None:
        return ""
    if gran_label == "Monthly":
        dt = cohort_ts + pd.DateOffset(months=p)
        return dt.strftime("%b '%y")
    elif gran_label == "Quarterly":
        dt = cohort_ts + pd.DateOffset(months=p * 3)
        q = (dt.month - 1) // 3 + 1
        return f"Q{q} '{dt.strftime('%y')}"
    else:
        dt = cohort_ts + pd.DateOffset(years=p)
        return dt.strftime("'%y")


def render_row_html(label, meta_text, pct_row, detail_row, change_map, period_cols, cohort_ts, gran_label, is_sub=False):
    row_html = "<tr>"
    td_cls = "cohort-header" if not is_sub else "cohort-sub-header"
    indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if is_sub else ""
    row_html += f'<td class="{td_cls}">{indent}{label}<br><span class="cohort-meta">{indent}{meta_text}</span></td>'

    for p in period_cols:
        val = pct_row.get(p)
        detail = detail_row.get(p) if detail_row else None
        if val is None:
            row_html += '<td class="cell-na"></td>'
        else:
            if val >= 120:
                cls = "cell-120plus"
            elif val >= 100:
                cls = "cell-100plus"
            elif val >= 90:
                cls = "cell-90"
            elif val >= 80:
                cls = "cell-80"
            else:
                cls = "cell-below80"
            period_lbl = get_period_label(cohort_ts, p, gran_label)
            period_html = f'<span class="cell-period">{period_lbl}</span>' if period_lbl else ""
            sub = ""
            if detail:
                sub = f'<span class="cell-sub">{fmt_arr(detail["arr"])} · {detail["logos"]}</span>'
            if p not in change_map and p != 0:
                row_html += f'<td class="{cls}" style="opacity:0.7;font-style:italic;">{period_html}{val:.0f}%{sub}</td>'
            else:
                row_html += f'<td class="{cls}">{period_html}{val:.0f}%{sub}</td>'

    row_html += "</tr>"
    return row_html


BREAKDOWN_COL_MAP = {
    "Segment": "SEGMENT",
    "Owner": "OWNER",
    "Industry": "INDUSTRY",
    "Eng Size Group": "ENG_SIZE_GROUP",
    "Geo": "GEO",
}

prefix = "Q+" if granularity == "Quarterly" else ("M+" if granularity == "Monthly" else "Y+")

cohorts_sorted = sorted(df["COHORT"].dropna().unique())

all_max_col = int(df["PERIODS_SINCE"].max()) if not df.empty else 0
period_cols = list(range(0, all_max_col + 1))

cohort_timestamps = {}
for c in cohorts_sorted:
    cohort_timestamps[format_cohort_label(c)] = c

html = """<style>
.cohort-table { border-collapse: collapse; width: 100%; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 12px; }
.cohort-table th { background: #1a1a2e; color: #fff; padding: 8px 10px; text-align: center; font-weight: 500; position: sticky; top: 0; z-index: 1; }
.cohort-table td { padding: 4px 6px; text-align: center; border: 1px solid #e0e0e0; font-weight: 600; vertical-align: middle; }
.cohort-table tr:hover td { opacity: 0.9; }
.cohort-header { text-align: left !important; background: #f5f5f5; color: #111; font-weight: 600; min-width: 140px; border-bottom: 2px solid #ddd; }
.cohort-sub-header { text-align: left !important; background: #fff; color: #444; font-weight: 500; min-width: 140px; font-size: 11px; }
.cohort-meta { font-size: 10px; color: #888; font-weight: 400; }
.cell-na { background: #fafafa; color: #ccc; }
.cell-100plus { background: #c8e6c9; color: #1b5e20; }
.cell-120plus { background: #81c784; color: #1b5e20; }
.cell-90 { background: #fff9c4; color: #f57f17; }
.cell-80 { background: #ffe0b2; color: #e65100; }
.cell-below80 { background: #ffcdd2; color: #b71c1c; }
.cell-sub { font-size: 9px; font-weight: 400; opacity: 0.7; display: block; margin-top: 1px; }
.cell-period { font-size: 9px; font-weight: 400; opacity: 0.5; display: block; margin-bottom: 1px; }
.legend { display: flex; gap: 12px; margin-bottom: 12px; font-size: 12px; align-items: center; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 4px; }
.legend-box { width: 16px; height: 16px; border-radius: 3px; }
</style>"""

html += """<div class="legend">
<span style="font-weight:600; margin-right:8px;">Legend:</span>
<span class="legend-item"><span class="legend-box" style="background:#81c784;"></span> &gt;120%</span>
<span class="legend-item"><span class="legend-box" style="background:#c8e6c9;"></span> 100-120%</span>
<span class="legend-item"><span class="legend-box" style="background:#fff9c4;"></span> 90-100%</span>
<span class="legend-item"><span class="legend-box" style="background:#ffe0b2;"></span> 80-90%</span>
<span class="legend-item"><span class="legend-box" style="background:#ffcdd2;"></span> &lt;80%</span>
<span class="legend-item"><span style="opacity:0.7;font-style:italic;">italic</span> = carried forward</span>
</div>"""

html += '<div style="overflow-x:auto;"><table class="cohort-table"><thead><tr>'
html += '<th class="cohort-header">Cohort</th>'
for p in period_cols:
    html += f'<th>{prefix}{p}</th>'
html += '</tr></thead><tbody>'

for cohort_ts in cohorts_sorted:
    cohort_label = format_cohort_label(cohort_ts)
    cohort_data = df[df["COHORT"] == cohort_ts]

    result = compute_cohort_row(cohort_data)
    if result is None:
        continue

    meta = f"{result['base_logos']} logos · {fmt_arr(result['base_arr'])}"
    html += render_row_html(
        cohort_label, meta,
        result["pct_row"], result["detail_row"], result["change_map"],
        period_cols, cohort_ts, granularity, is_sub=False,
    )

    if breakdown != "None":
        bd_col = BREAKDOWN_COL_MAP[breakdown]
        groups = sorted(cohort_data[bd_col].dropna().unique(), key=str)
        for group in groups:
            subset = cohort_data[cohort_data[bd_col] == group]
            sub_result = compute_cohort_row(subset)
            if sub_result is None:
                continue
            sub_meta = f"{sub_result['base_logos']} logos · {fmt_arr(sub_result['base_arr'])}"
            html += render_row_html(
                str(group), sub_meta,
                sub_result["pct_row"], sub_result["detail_row"], sub_result["change_map"],
                period_cols, cohort_ts, granularity, is_sub=True,
            )

html += '</tbody></table></div>'
st.html(html)

st.markdown("---")
st.markdown("**Drill into deals:**")

cohort_options = [format_cohort_label(c) for c in cohorts_sorted]
dc1, dc2 = st.columns(2)
with dc1:
    sel_cohort = st.selectbox(
        "Select Cohort",
        [""] + cohort_options,
        format_func=lambda x: "— Select cohort —" if x == "" else x,
    )
with dc2:
    period_options = ["All (entire cohort)"] + [f"{prefix}{p}" for p in period_cols]
    sel_period = st.selectbox("Select Period", period_options)

if sel_cohort:
    cohort_ts = cohort_timestamps.get(sel_cohort)
    if cohort_ts is not None:
        if sel_period == "All (entire cohort)":
            cell_deals = df[df["COHORT"] == cohort_ts]
            st.markdown(f"### All deals in cohort `{sel_cohort}` ({len(cell_deals)} deals)")
        else:
            p_val = int(sel_period.split("+")[1])
            cell_deals = df[
                (df["COHORT"] == cohort_ts) & (df["PERIODS_SINCE"] == p_val)
            ]
            if cell_deals.empty:
                st.info(f"No deal activity in cohort `{sel_cohort}` at period `{sel_period}` — value carried forward.")
                st.stop()
            st.markdown(f"### Deals in `{sel_cohort}` at `{sel_period}` ({len(cell_deals)} deals)")

        if not cell_deals.empty:
            display_cols = [
                "COMPANY_NAME", "DEAL_NAME", "DEAL_CATEGORY",
                "NET_NEW_ARR", "DEAL_CLOSED_DATE", "OWNER",
                "SEGMENT", "GEO", "PERIODS_SINCE",
            ]
            display_df = cell_deals[display_cols].sort_values("DEAL_CLOSED_DATE").reset_index(drop=True)
            display_df.columns = [
                "Company", "Deal", "Category",
                "Net New ARR", "Closed Date", "Owner", "Segment", "Geo", "Period",
            ]

            def color_net_arr(val):
                if pd.isna(val):
                    return ""
                if val > 0:
                    return "background-color: #d4edda; color: #155724;"
                elif val < 0:
                    return "background-color: #f8d7da; color: #721c24;"
                return ""

            def color_category(val):
                colors = {
                    "New Business": "background-color: #c8e6c9; color: #1b5e20;",
                    "Expansion": "background-color: #81c784; color: #1b5e20;",
                    "Renewal": "background-color: #fff9c4; color: #f57f17;",
                    "Churn": "background-color: #ffcdd2; color: #b71c1c;",
                    "Other": "",
                }
                return colors.get(val, "")

            styled = display_df.style.map(
                color_net_arr, subset=["Net New ARR"]
            ).map(
                color_category, subset=["Category"]
            ).format({"Net New ARR": "${:,.0f}"}, na_rep="—")

            st.dataframe(styled, use_container_width=True, hide_index=True)
