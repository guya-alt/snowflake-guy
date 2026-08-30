# Updated closed deals table reference to CLOSED_DEALS_NEWBIZ_100826
# Co-authored with CoCo
import os
import streamlit as st
import altair as alt
import pandas as pd

st.set_page_config(page_title="Classic NewBiz Lost Deals", layout="wide")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

st.title("Classic NewBiz Lost Deals")


@st.cache_data
def load_data():
    query = """
    SELECT
        TO_VARCHAR(YEAR(DATE_TRUNC('quarter', fact_deals.deal_closed_date))) || '-Q' || TO_VARCHAR(QUARTER(DATE_TRUNC('quarter', fact_deals.deal_closed_date))) AS closed_q,
        CASE WHEN DEAL_TEAM_NAME ILIKE '%Ent%' THEN 'Enterprise' WHEN DEAL_TEAM_NAME ILIKE '%MM%' THEN 'Mid-Market' ELSE COALESCE(closed_deals.SEGMENT_, 'Unknown') END AS segment,
        fact_deals.deal_stage,
        COALESCE(closed_deals.POC_INDICATION, 'No POC') AS poc_indication,
        fact_deals.deal_team_name,
        fact_deals.sk_sales_owner,
        dim_employee.display_name AS owner_name,
        DIM_COMPANY.GEOGRAPHY,
        DIM_COMPANY.COMPANY_NAME,
        fact_deals.mega_source AS deal_source,
        closed_deals.DEAL_STAGE_BEFORE_CLOSED,
        CASE
            WHEN closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS IS NOT NULL
            THEN closed_deals.DATE_ENTERED_FORMAL_PILOT_CLASSIC
        END AS DATE_ENTERED_FORMAL_PILOT_CLASSIC,
        fact_deals.deal_closed_date,
        fact_deals.qualified_date,
        fact_deals.deal_name,
        fact_deals.deal_total_arr,
        fact_deals.closed_lost_reason,

        closed_deals.CUMULATIVE_TIME_IN_DEMO__PRESENTATION__CLASSIC_HHMMSS,
        closed_deals.CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS,
        closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS,
        closed_deals.CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS,
        closed_deals.CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC_HHMMSS

    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS AS fact_deals
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY AS dim_company
        ON dim_company.sk_company = fact_deals.sk_company
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE AS dim_employee
        ON dim_employee.sk_employee = fact_deals.sk_sales_owner
    LEFT JOIN PORT_ANALYTICS_DEV.SALES_ANALYTICS.CLOSED_DEALS_NEWBIZ_100826 AS closed_deals
        ON closed_deals.RECORD_ID = fact_deals.deal_crm_id
    WHERE fact_deals.pipeline ILIKE '%classic%'
        AND fact_deals.deal_type ILIKE '%newbusiness%'
        AND fact_deals.qualified_date >= '2025-01-01'
        AND fact_deals.deal_closed_date <= CURRENT_DATE()
        AND COALESCE(COMPANY_NAME, '') NOT ILIKE '%test%'
        AND COALESCE(COMPANY_NAME, '') != 'Port'
    """
    return conn.query(query)


with st.spinner("Loading context lake :)"):
    df = load_data()

with st.sidebar:
    st.header("Filters")

    segment_s = sorted(df["SEGMENT"].dropna().unique().tolist())
    selected_segment_s = st.multiselect("Segment", segment_s, default=segment_s)

    poc_options = sorted(df["POC_INDICATION"].dropna().unique().tolist())
    selected_poc = st.multiselect("POC Indication", poc_options, default=poc_options)

    stages = sorted(df["DEAL_STAGE"].dropna().unique().tolist())
    default_stages = [s for s in stages if s.lower() in ("closed lost", "closed won")]
    if not default_stages:
        default_stages = stages
    selected_stages = st.multiselect("Deal Stage", stages, default=default_stages)

    stages_before_lost = sorted(df["DEAL_STAGE_BEFORE_CLOSED"].dropna().unique().tolist())
    selected_stages_before_lost = st.multiselect("Stage Before Lost", stages_before_lost, default=stages_before_lost)

    arr_min = float(df["DEAL_TOTAL_ARR"].min()) if df["DEAL_TOTAL_ARR"].notna().any() else 0.0
    arr_max = float(df["DEAL_TOTAL_ARR"].max()) if df["DEAL_TOTAL_ARR"].notna().any() else 1.0
    selected_arr = st.slider("Total ARR", min_value=arr_min, max_value=arr_max, value=(arr_min, arr_max))

    arr_pct_range = st.slider("ARR Percentile Range", min_value=0, max_value=100, value=(0, 100), help="Filter deals by ARR percentile (e.g. 90-100 = top 10% highest ARR)")

    qualify_min = df["QUALIFIED_DATE"].min()
    qualify_max = df["QUALIFIED_DATE"].max()
    selected_qualify_date = st.date_input("Qualify Date Range", value=(qualify_min, qualify_max), min_value=qualify_min, max_value=qualify_max)

    closed_quarters = sorted(df["CLOSED_Q"].dropna().unique().tolist())
    selected_closed_quarters = st.multiselect("Closed Quarter", closed_quarters, default=closed_quarters)

    owner_names = sorted(df["OWNER_NAME"].dropna().unique().tolist())
    selected_owners = st.multiselect("Owner Name", owner_names, default=[])

    deal_teams = sorted(df["DEAL_TEAM_NAME"].dropna().unique().tolist())
    selected_deal_teams = st.multiselect("Deal Team", deal_teams, default=[])

    st.divider()
    st.header("Breakdown")
    breakdown_options = {
        "None": None,
        "Segment": "SEGMENT",
        "Deal Team": "DEAL_TEAM_NAME",
        "Sales Owner": "OWNER_NAME",
        "Geography": "GEOGRAPHY",
        "Deal Source": "DEAL_SOURCE",
        "POC Indication": "POC_INDICATION",
        "Stage Before Closed": "DEAL_STAGE_BEFORE_CLOSED",
    }
    breakdown_label = st.selectbox("Breakdown by", list(breakdown_options.keys()))
    breakdown_col = breakdown_options[breakdown_label]

    st.divider()
    if st.button("Refresh data"):
        load_data.clear()
        st.rerun()

filtered = df[
    (df["SEGMENT"].isin(selected_segment_s))
    & (df["POC_INDICATION"].isin(selected_poc))
    & (df["DEAL_STAGE"].isin(selected_stages))
    & (df["DEAL_STAGE_BEFORE_CLOSED"].isin(selected_stages_before_lost) | df["DEAL_STAGE_BEFORE_CLOSED"].isna())
    & (df["DEAL_TOTAL_ARR"].between(selected_arr[0], selected_arr[1]) | df["DEAL_TOTAL_ARR"].isna())
    & (df["OWNER_NAME"].isin(selected_owners) if selected_owners else True)
    & (df["DEAL_TEAM_NAME"].isin(selected_deal_teams) if selected_deal_teams else True)
    & (
        df["DEAL_TOTAL_ARR"].between(
            df["DEAL_TOTAL_ARR"].quantile(arr_pct_range[0] / 100),
            df["DEAL_TOTAL_ARR"].quantile(arr_pct_range[1] / 100),
        ) | df["DEAL_TOTAL_ARR"].isna()
    )
    & (df["CLOSED_Q"].isin(selected_closed_quarters))
]
if len(selected_qualify_date) == 2:
    filtered = filtered[
        (pd.to_datetime(filtered["QUALIFIED_DATE"]).dt.date >= selected_qualify_date[0])
        & (pd.to_datetime(filtered["QUALIFIED_DATE"]).dt.date <= selected_qualify_date[1])
    ]

if "drill_filter" not in st.session_state:
    st.session_state.drill_filter = {}

_drill_set_this_run = False

def update_drill(key, value):
    global _drill_set_this_run
    if not _drill_set_this_run:
        st.session_state.drill_filter = {}
        _drill_set_this_run = True
    if value:
        st.session_state.drill_filter[key] = value

def make_selectable(chart):
    sel = alt.selection_point()
    return chart.add_params(sel)

def add_labels(chart, data, x_field, y_field, x_sort, is_pct=False, color="#4c78a8"):
    fmt = ".0f" if is_pct else ".1f"
    label = alt.Chart(data).mark_text(dy=-12, fontSize=11, color=color).encode(
        x=alt.X(f"{x_field}:N", sort=x_sort),
        y=alt.Y(f"{y_field}:Q"),
        text=alt.Text(f"{y_field}:Q", format=fmt),
    )
    if is_pct:
        data = data.copy()
        data["_label"] = data[y_field].apply(lambda v: f"{v:.0f}%")
        label = alt.Chart(data).mark_text(dy=-12, fontSize=11, color=color).encode(
            x=alt.X(f"{x_field}:N", sort=x_sort),
            y=alt.Y(f"{y_field}:Q"),
            text="_label:N",
        )
    return chart + label

st.subheader("Closed-Lost Deals Over Time")

lost_deals = filtered[filtered["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]

lost_metric = st.radio("Metric", ["ARR", "Deals"], horizontal=True, key="lost_metric")

if lost_metric == "Deals":
    st.caption("Quarterly count of lost deals (Classic, New Business)")
    y_field = "Lost Deals"
    y_title = "Lost Deals (count)"
    if breakdown_col:
        chart_data = lost_deals.groupby(["CLOSED_Q", breakdown_col]).agg(**{"Lost Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index().sort_values("CLOSED_Q")
    else:
        chart_data = lost_deals.groupby("CLOSED_Q").agg(**{"Lost Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index().sort_values("CLOSED_Q")
else:
    st.caption("Quarterly total ARR lost (Classic, New Business)")
    y_field = "Lost ARR"
    y_title = "Lost ARR ($)"
    if breakdown_col:
        chart_data = lost_deals.groupby(["CLOSED_Q", breakdown_col]).agg(**{"Lost Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index().sort_values("CLOSED_Q")
    else:
        chart_data = lost_deals.groupby("CLOSED_Q").agg(**{"Lost Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index().sort_values("CLOSED_Q")

if breakdown_col:
    c = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(chart_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y(f"{y_field}:Q", title=y_title),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
    ).properties(height=350)
    event = st.altair_chart(make_selectable(c), use_container_width=True, on_select="rerun", key="lost_over_time")
    if event and event.selection and event.selection.get("param_1"):
        pts = event.selection["param_1"]
        if pts:
            p = pts[0]
            update_drill("CLOSED_Q", p.get("CLOSED_Q"))
            update_drill(breakdown_col, p.get(breakdown_col))
else:
    c = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(chart_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y(f"{y_field}:Q", title=y_title),
        tooltip=["CLOSED_Q", alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
    ).properties(height=350)
    event = st.altair_chart(make_selectable(c), use_container_width=True, on_select="rerun", key="lost_over_time_no_bd")
    if event and event.selection and event.selection.get("param_1"):
        pts = event.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.subheader("Closed-Lost Share Over Time")
st.caption("100% stacked — proportion of lost deals by breakdown")

share_metric = st.radio("Share Metric", ["ARR", "Deals"], horizontal=True, key="share_metric")

if breakdown_col:
    if share_metric == "Deals":
        share_val_field = "Lost Deals"
    else:
        share_val_field = "Lost ARR"
    share_data = lost_deals.groupby(["CLOSED_Q", breakdown_col]).agg(**{"Lost Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index().sort_values("CLOSED_Q")

    pct_data = share_data.copy()
    totals = pct_data.groupby("CLOSED_Q")[share_val_field].transform("sum")
    pct_data["Pct"] = (pct_data[share_val_field] / totals * 100).round(2)
    c2 = alt.Chart(pct_data).mark_bar().encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(pct_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Pct:Q", stack="normalize", title=f"% of {share_val_field}"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Pct:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
    ).properties(height=350)
    event2 = st.altair_chart(make_selectable(c2), use_container_width=True, on_select="rerun", key="lost_share")
    if event2 and event2.selection and event2.selection.get("param_1"):
        pts = event2.selection["param_1"]
        if pts:
            p = pts[0]
            update_drill("CLOSED_Q", p.get("CLOSED_Q"))
            update_drill(breakdown_col, p.get(breakdown_col))
else:
    st.info("Select a breakdown dimension to see the 100% stacked view.")

st.divider()

st.subheader("Loss Rate by Quarter")
st.caption("Lost deals as % of all closed deals — normalizes for volume changes")

loss_rate_metric = st.radio("Loss Rate Metric", ["ARR", "Deals"], horizontal=True, key="loss_rate_metric")

closed_deals = filtered[
    filtered["DEAL_STAGE"].str.lower().str.contains("closed lost|closed won", na=False, regex=True)
]

def calc_loss_rate(g):
    lost_deals_count = g[g["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_NAME"].nunique()
    total_deals_count = g["DEAL_NAME"].nunique()
    lost_arr = g[g["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_TOTAL_ARR"].sum()
    total_arr = g["DEAL_TOTAL_ARR"].sum()
    if loss_rate_metric == "Deals":
        rate = round(lost_deals_count / max(total_deals_count, 1) * 100, 2)
    else:
        rate = round(lost_arr / max(total_arr, 1) * 100, 2)
    return pd.Series({"Loss Rate %": rate, "Lost Deals": lost_deals_count, "Lost ARR": round(lost_arr, 0)})

if breakdown_col:
    rate_data = (
        closed_deals.groupby(["CLOSED_Q", breakdown_col])
        .apply(calc_loss_rate, include_groups=False)
        .reset_index()
        .sort_values("CLOSED_Q")
    )
    c3 = alt.Chart(rate_data).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(rate_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Loss Rate %:Q", title="Loss Rate %"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
    ).properties(height=300)
    event3 = st.altair_chart(make_selectable(c3), use_container_width=True, on_select="rerun", key="loss_rate_q")
    if event3 and event3.selection and event3.selection.get("param_1"):
        pts = event3.selection["param_1"]
        if pts:
            p = pts[0]
            update_drill("CLOSED_Q", p.get("CLOSED_Q"))
            update_drill(breakdown_col, p.get(breakdown_col))
else:
    rate_data = (
        closed_deals.groupby("CLOSED_Q")
        .apply(calc_loss_rate, include_groups=False)
        .reset_index()
        .sort_values("CLOSED_Q")
    )
    c3 = alt.Chart(rate_data).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(rate_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Loss Rate %:Q", title="Loss Rate %"),
        tooltip=["CLOSED_Q", alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
    ).properties(height=300)
    c3 = add_labels(c3, rate_data, "CLOSED_Q", "Loss Rate %", sorted(rate_data["CLOSED_Q"].unique()), is_pct=True)
    event3 = st.altair_chart(make_selectable(c3), use_container_width=True, on_select="rerun", key="loss_rate_q_no_bd")
    if event3 and event3.selection and event3.selection.get("param_1"):
        pts = event3.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.divider()

st.subheader("Closed-Lost by POC Outcome")
st.caption("Did deals run a formal pilot before losing? A shift toward 'No POC' or failed-POC losses points to qualification/product fit.")

poc_metric = st.radio("POC Metric", ["ARR", "Deals"], horizontal=True, key="poc_metric")
poc_val_field = "Lost Deals" if poc_metric == "Deals" else "Lost ARR"

if breakdown_col:
    def _poc_agg(g):
        deals = g["DEAL_NAME"].nunique()
        arr = g["DEAL_TOTAL_ARR"].sum()
        return pd.Series({"Lost Deals": deals, "Lost ARR": round(arr, 0)})

    lost_no_poc_bd = lost_deals[lost_deals["POC_INDICATION"] == "No POC"].groupby(["CLOSED_Q", breakdown_col]).apply(_poc_agg, include_groups=False).reset_index().sort_values("CLOSED_Q")
    lost_with_poc_bd = lost_deals[lost_deals["POC_INDICATION"] != "No POC"].groupby(["CLOSED_Q", breakdown_col]).apply(_poc_agg, include_groups=False).reset_index().sort_values("CLOSED_Q")
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Closed-Lost — No POC**")
        c_np = alt.Chart(lost_no_poc_bd).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_no_poc_bd["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{poc_val_field}:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        ev_np = st.altair_chart(make_selectable(c_np), use_container_width=True, on_select="rerun", key="poc_no")
        if ev_np and ev_np.selection and ev_np.selection.get("param_1"):
            pts = ev_np.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "No POC")
    with col_right:
        st.markdown("**Closed-Lost — With POC**")
        c_wp = alt.Chart(lost_with_poc_bd).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_with_poc_bd["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{poc_val_field}:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        ev_wp = st.altair_chart(make_selectable(c_wp), use_container_width=True, on_select="rerun", key="poc_yes")
        if ev_wp and ev_wp.selection and ev_wp.selection.get("param_1"):
            pts = ev_wp.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")
else:
    def _poc_agg_nobd(g):
        deals = g["DEAL_NAME"].nunique()
        arr = g["DEAL_TOTAL_ARR"].sum()
        return pd.Series({"Lost Deals": deals, "Lost ARR": round(arr, 0)})

    lost_no_poc_data = lost_deals[lost_deals["POC_INDICATION"] == "No POC"].groupby("CLOSED_Q").apply(_poc_agg_nobd, include_groups=False).reset_index().sort_values("CLOSED_Q")
    lost_with_poc_data = lost_deals[lost_deals["POC_INDICATION"] != "No POC"].groupby("CLOSED_Q").apply(_poc_agg_nobd, include_groups=False).reset_index().sort_values("CLOSED_Q")
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Closed-Lost — No POC**")
        c_np = alt.Chart(lost_no_poc_data).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_no_poc_data["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{poc_val_field}:Q"),
            tooltip=["CLOSED_Q", alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        c_np = add_labels(c_np, lost_no_poc_data, "CLOSED_Q", poc_val_field, sorted(lost_no_poc_data["CLOSED_Q"].unique()))
        ev_np = st.altair_chart(make_selectable(c_np), use_container_width=True, on_select="rerun", key="poc_no_nb")
        if ev_np and ev_np.selection and ev_np.selection.get("param_1"):
            pts = ev_np.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "No POC")
    with col_right:
        st.markdown("**Closed-Lost — With POC**")
        c_wp = alt.Chart(lost_with_poc_data).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_with_poc_data["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{poc_val_field}:Q"),
            tooltip=["CLOSED_Q", alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        c_wp = add_labels(c_wp, lost_with_poc_data, "CLOSED_Q", poc_val_field, sorted(lost_with_poc_data["CLOSED_Q"].unique()))
        ev_wp = st.altair_chart(make_selectable(c_wp), use_container_width=True, on_select="rerun", key="poc_yes_nb")
        if ev_wp and ev_wp.selection and ev_wp.selection.get("param_1"):
            pts = ev_wp.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")

st.divider()

st.subheader("Where Deals Are Lost")
st.caption("100% stacked — proportion of lost deals by stage before closed, per quarter.")

where_metric = st.radio("Metric", ["ARR", "Deals"], horizontal=True, key="where_metric")

STAGE_ORDER = [
    "SDR / Omitted OPP",
    "Demo / Presentation",
    "Pilot Prep",
    "Formal Pilot",
    "Business case confirmation",
    "Negotiation / Legal",
]

if where_metric == "Deals":
    group_cols = ["CLOSED_Q", "DEAL_STAGE_BEFORE_CLOSED"] + ([breakdown_col] if breakdown_col else [])
    stage_lost_stacked = lost_deals.groupby(group_cols).agg(Count=("DEAL_NAME", "nunique"), **{"Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index()
    stage_totals_stacked = stage_lost_stacked.groupby("CLOSED_Q")["Count"].transform("sum")
    stage_lost_stacked["% of Lost Deals"] = (stage_lost_stacked["Count"] / stage_totals_stacked * 100).round(1)
    y_val = "Count:Q"
    y_title = "% of Lost Deals"
    pct_field = "% of Lost Deals"
else:
    group_cols = ["CLOSED_Q", "DEAL_STAGE_BEFORE_CLOSED"] + ([breakdown_col] if breakdown_col else [])
    stage_lost_stacked = lost_deals.groupby(group_cols).agg(Count=("DEAL_NAME", "nunique"), **{"Lost ARR": ("DEAL_TOTAL_ARR", "sum")}).reset_index()
    stage_totals_stacked = stage_lost_stacked.groupby("CLOSED_Q")["Lost ARR"].transform("sum")
    stage_lost_stacked["% of Lost ARR"] = (stage_lost_stacked["Lost ARR"] / stage_totals_stacked.replace(0, 1) * 100).round(1)
    y_val = "Lost ARR:Q"
    y_title = "% of Lost ARR"
    pct_field = "% of Lost ARR"

c_where = alt.Chart(stage_lost_stacked).mark_bar().encode(
    x=alt.X("CLOSED_Q:N", sort=sorted(stage_lost_stacked["CLOSED_Q"].unique()), title="Closed Quarter"),
    y=alt.Y(y_val, stack="normalize", title=y_title),
    color=alt.Color("DEAL_STAGE_BEFORE_CLOSED:N", sort=STAGE_ORDER, title="Stage Before Closed"),
    tooltip=["CLOSED_Q", "DEAL_STAGE_BEFORE_CLOSED", alt.Tooltip(f"{pct_field}:Q", format=".1f"), alt.Tooltip("Count:Q", title="Deals", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
).properties(height=350)
ev_where = st.altair_chart(make_selectable(c_where), use_container_width=True, on_select="rerun", key="where_lost")
if ev_where and ev_where.selection and ev_where.selection.get("param_1"):
    pts = ev_where.selection["param_1"]
    if pts:
        p = pts[0]
        update_drill("CLOSED_Q", p.get("CLOSED_Q"))
        update_drill("DEAL_STAGE_BEFORE_CLOSED", p.get("DEAL_STAGE_BEFORE_CLOSED"))

st.divider()

st.subheader("Stage Before Closed")
st.caption("% of lost deals by last stage before closing — each panel shows one stage's trend over time.")

stage_grid_cols = st.columns(2)
STAGE_BEFORE_CLOSED_ORDER = [
    "Demo / Presentation",
    "Pilot Prep",
    "Formal Pilot",
    "Business case confirmation",
    "Negotiation / Legal",
]
for idx, stage_name in enumerate(STAGE_BEFORE_CLOSED_ORDER):
    stage_subset = stage_lost_stacked[stage_lost_stacked["DEAL_STAGE_BEFORE_CLOSED"] == stage_name].sort_values("CLOSED_Q")
    all_quarters = sorted(stage_lost_stacked["CLOSED_Q"].unique())
    if breakdown_col and breakdown_col in stage_lost_stacked.columns:
        all_breakdowns = stage_lost_stacked[breakdown_col].unique()
        full_index = pd.MultiIndex.from_product([all_quarters, all_breakdowns], names=["CLOSED_Q", breakdown_col])
        stage_subset = stage_subset.set_index(["CLOSED_Q", breakdown_col]).reindex(full_index, fill_value=0).reset_index()
        stage_subset[pct_field] = stage_subset[pct_field].fillna(0)
        c_stage = alt.Chart(stage_subset).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=all_quarters, title="Closed Quarter"),
            y=alt.Y(f"{pct_field}:Q", title=pct_field),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip(f"{pct_field}:Q", format=".1f"), alt.Tooltip("Count:Q", title="Deals", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=200)
    else:
        full_index = pd.DataFrame({"CLOSED_Q": all_quarters})
        stage_subset = full_index.merge(stage_subset, on="CLOSED_Q", how="left").fillna(0)
        c_stage = alt.Chart(stage_subset).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=all_quarters, title="Closed Quarter"),
            y=alt.Y(f"{pct_field}:Q", title=pct_field),
            tooltip=["CLOSED_Q", alt.Tooltip(f"{pct_field}:Q", format=".1f"), alt.Tooltip("Count:Q", title="Deals", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=200)
    with stage_grid_cols[idx % 2]:
        st.markdown(f"**{stage_name}**")
        ev_stg = st.altair_chart(make_selectable(c_stage), use_container_width=True, on_select="rerun", key=f"stage_before_{idx}")
        if ev_stg and ev_stg.selection and ev_stg.selection.get("param_1"):
            pts = ev_stg.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("DEAL_STAGE_BEFORE_CLOSED", stage_name)

with st.expander("Raw Data — Where Deals Are Lost"):
    where_filter_cols = st.columns(3)
    with where_filter_cols[0]:
        where_stages = sorted(lost_deals["DEAL_STAGE_BEFORE_CLOSED"].dropna().unique().tolist())
        where_selected_stages = st.multiselect("Stage Before Closed", where_stages, default=where_stages, key="where_raw_stages")
    with where_filter_cols[1]:
        where_quarters = sorted(lost_deals["CLOSED_Q"].dropna().unique().tolist())
        where_selected_quarters = st.multiselect("Quarter", where_quarters, default=where_quarters, key="where_raw_quarters")
    with where_filter_cols[2]:
        where_teams = sorted(lost_deals["DEAL_TEAM_NAME"].dropna().unique().tolist())
        where_selected_teams = st.multiselect("Deal Team", where_teams, default=[], key="where_raw_teams")
    where_raw = lost_deals[["DEAL_NAME", "COMPANY_NAME", "OWNER_NAME", "DEAL_TOTAL_ARR", "DEAL_STAGE_BEFORE_CLOSED", "CLOSED_Q", "CLOSED_LOST_REASON", "DEAL_TEAM_NAME", "POC_INDICATION", "DEAL_CLOSED_DATE"]].copy()
    where_raw = where_raw[where_raw["DEAL_STAGE_BEFORE_CLOSED"].isin(where_selected_stages)]
    where_raw = where_raw[where_raw["CLOSED_Q"].isin(where_selected_quarters)]
    if where_selected_teams:
        where_raw = where_raw[where_raw["DEAL_TEAM_NAME"].isin(where_selected_teams)]
    where_raw = where_raw.sort_values("DEAL_TOTAL_ARR", ascending=False)
    st.caption(f"{len(where_raw)} deals")
    st.dataframe(where_raw, use_container_width=True, hide_index=True)

st.divider()

st.subheader("Closed-Lost Reasons Over Time")
st.caption("100% stacked — each reason's share per quarter (multi-select values are split).")

def hhmmss_to_days_reason(series):
    def parse_val(v):
        if pd.isna(v) or v == "" or v is None:
            return None
        parts = str(v).split(":")
        if len(parts) != 3:
            return None
        try:
            return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) / 86400
        except (ValueError, TypeError):
            return None
    return series.apply(parse_val)

reason_col1, reason_col2 = st.columns([1, 3])

reason_time_buckets = [0, 30, 60, 90, 9999]
reason_time_labels = ["<30d", "30-60d", "60-90d", "90d+"]
reason_stage_time_cols = {
    "Demo/Presentation": "CUMULATIVE_TIME_IN_DEMO__PRESENTATION__CLASSIC_HHMMSS",
    "Business Validation": "CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS",
    "Formal Pilot": "CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS",
    "Business Case Confirmation": "CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS",
    "Negotiation/Legal": "CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC_HHMMSS",
}
reason_stage_options = list(reason_stage_time_cols.keys())
reason_dwell_stages = st.multiselect("Filter by dwell time in stage", reason_stage_options, key="reason_dwell_stages")
reason_dwell_buckets = []
if reason_dwell_stages:
    reason_dwell_buckets = st.multiselect("Dwell time buckets", reason_time_labels, default=reason_time_labels, key="reason_dwell_buckets")

reason_data = lost_deals[["CLOSED_Q", "CLOSED_LOST_REASON", "DEAL_NAME", "DEAL_TOTAL_ARR"] + [c for c in reason_stage_time_cols.values() if c in lost_deals.columns]].dropna(subset=["CLOSED_LOST_REASON"])

if reason_dwell_stages and reason_dwell_buckets:
    bucket_ranges = {"<30d": (0, 30), "30-60d": (30, 60), "60-90d": (60, 90), "90d+": (90, 9999)}
    mask = pd.Series(False, index=reason_data.index)
    for stage_name in reason_dwell_stages:
        dwell_col = reason_stage_time_cols[stage_name]
        if dwell_col in reason_data.columns:
            days = hhmmss_to_days_reason(reason_data[dwell_col])
            for b in reason_dwell_buckets:
                if b in bucket_ranges:
                    lo, hi = bucket_ranges[b]
                    mask = mask | ((days >= lo) & (days < hi))
    reason_data = reason_data[mask]
reason_data = reason_data[reason_data["CLOSED_LOST_REASON"].str.strip() != ""]
reason_exploded = reason_data.assign(REASON=reason_data["CLOSED_LOST_REASON"].str.split(";")).explode("REASON")
reason_exploded["REASON"] = reason_exploded["REASON"].str.strip()
reason_exploded = reason_exploded[reason_exploded["REASON"] != ""]

REASON_CATEGORIES = {
    "Competitive": ["Competition", "Internal Build", "Freemium"],
    "Product Gap": ["Product", "Missing Feature", "On-prem", "Security"],
    "Commercial": ["Price", "Budget", "Legal"],
    "Timing / Fit": ["Bad timing", "Early stage", "Not right company/ persona", "Champion left/ Company cuts"],
    "Engagement": ["Unable to connect", "No-show", "No value"],
    "Other": ["Other", "UNQ", "Partnership"],
}
REASON_TO_CATEGORY = {}
for cat, reasons in REASON_CATEGORIES.items():
    for r in reasons:
        REASON_TO_CATEGORY[r] = cat

categorize_reasons = st.toggle("Categorize lost reasons", value=True, key="categorize_reasons")

if categorize_reasons:
    reason_exploded["REASON"] = reason_exploded["REASON"].map(REASON_TO_CATEGORY).fillna("Other")
    num_categories_per_deal = reason_exploded.groupby("DEAL_NAME")["REASON"].nunique().rename("NUM_CATEGORIES")
    reason_exploded = reason_exploded.merge(num_categories_per_deal, on="DEAL_NAME", how="left")
    reason_exploded["ALLOCATED_ARR"] = reason_exploded["DEAL_TOTAL_ARR"] / reason_exploded["NUM_CATEGORIES"]
    reason_exploded = reason_exploded.drop_duplicates(subset=["DEAL_NAME", "REASON", "CLOSED_Q"])
else:
    num_reasons_per_deal = reason_exploded.groupby("DEAL_NAME")["REASON"].nunique().rename("NUM_REASONS")
    reason_exploded = reason_exploded.merge(num_reasons_per_deal, on="DEAL_NAME", how="left")
    reason_exploded["ALLOCATED_ARR"] = reason_exploded["DEAL_TOTAL_ARR"] / reason_exploded["NUM_REASONS"]

reason_agg = reason_exploded.groupby(["CLOSED_Q", "REASON"]).agg(Deals=("DEAL_NAME", "nunique"), ARR=("ALLOCATED_ARR", "sum")).reset_index()
reason_agg["Value"] = reason_agg["ARR"]
y_title = "% of Lost ARR"
pct_label = "% of ARR"

reason_totals = reason_agg.groupby("CLOSED_Q")["Value"].transform("sum")
reason_agg[pct_label] = (reason_agg["Value"] / reason_totals.replace(0, 1) * 100).round(1)
reason_agg["ARR_Display"] = (reason_agg["ARR"] / 1_000_000).round(2).apply(lambda x: f"${x:.1f}M")

c_reason = alt.Chart(reason_agg).mark_bar().encode(
    x=alt.X("CLOSED_Q:N", sort=sorted(reason_agg["CLOSED_Q"].unique()), title="Closed Quarter"),
    y=alt.Y("Value:Q", stack="normalize", title=y_title),
    color=alt.Color("REASON:N", title="Lost Reason" if not categorize_reasons else "Lost Reason Category"),
    tooltip=["CLOSED_Q", "REASON", alt.Tooltip(f"{pct_label}:Q", format=".1f"), alt.Tooltip("ARR_Display:N", title="ARR"), alt.Tooltip("Deals:Q", title="Deals")],
).properties(height=350)
ev_reason = st.altair_chart(make_selectable(c_reason), use_container_width=True, on_select="rerun", key="lost_reason")
if ev_reason and ev_reason.selection and ev_reason.selection.get("param_1"):
    pts = ev_reason.selection["param_1"]
    if pts:
        p = pts[0]
        if p.get("CLOSED_Q"):
            update_drill("CLOSED_Q", p.get("CLOSED_Q"))

if categorize_reasons:
    cat_table = pd.DataFrame([(cat, ", ".join(reasons)) for cat, reasons in REASON_CATEGORIES.items()], columns=["Category", "Reasons"])
    with st.expander("Category mapping"):
        st.dataframe(cat_table, use_container_width=True, hide_index=True)

st.divider()

st.subheader("Median Days to Close — Lost Deals")
st.caption("Qualified date → closed date. Lengthening cycles before a loss suggest stalled/disengaged deals.")

lost_with_dates = lost_deals.dropna(subset=["QUALIFIED_DATE", "DEAL_CLOSED_DATE"]).copy()
lost_with_dates["DAYS_TO_CLOSE"] = (pd.to_datetime(lost_with_dates["DEAL_CLOSED_DATE"]) - pd.to_datetime(lost_with_dates["QUALIFIED_DATE"])).dt.days

if breakdown_col:
    med_days = lost_with_dates.groupby(["CLOSED_Q", breakdown_col]).agg(DAYS_TO_CLOSE=("DAYS_TO_CLOSE", "median"), Deal_Count=("DEAL_NAME", "nunique"), Lost_ARR=("DEAL_TOTAL_ARR", "sum")).round(2).reset_index().sort_values("CLOSED_Q")
    c5 = alt.Chart(med_days).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_days["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("DAYS_TO_CLOSE:Q", title="Median Days (Qualified → Closed)"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("DAYS_TO_CLOSE:Q", title="Median Days", format=".1f"), alt.Tooltip("Deal_Count:Q", title="Deals", format=","), alt.Tooltip("Lost_ARR:Q", title="Lost ARR", format=",.0f")],
    ).properties(height=300)
    ev5 = st.altair_chart(make_selectable(c5), use_container_width=True, on_select="rerun", key="med_days_bd")
    if ev5 and ev5.selection and ev5.selection.get("param_1"):
        pts = ev5.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
            update_drill(breakdown_col, pts[0].get(breakdown_col))
else:
    med_days = lost_with_dates.groupby("CLOSED_Q").agg(DAYS_TO_CLOSE=("DAYS_TO_CLOSE", "median"), Deal_Count=("DEAL_NAME", "nunique"), Lost_ARR=("DEAL_TOTAL_ARR", "sum")).round(2).reset_index().sort_values("CLOSED_Q")
    c5 = alt.Chart(med_days).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_days["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("DAYS_TO_CLOSE:Q", title="Median Days (Qualified → Closed)"),
        tooltip=["CLOSED_Q", alt.Tooltip("DAYS_TO_CLOSE:Q", title="Median Days", format=".1f"), alt.Tooltip("Deal_Count:Q", title="Deals", format=","), alt.Tooltip("Lost_ARR:Q", title="Lost ARR", format=",.0f")],
    ).properties(height=300)
    c5 = add_labels(c5, med_days, "CLOSED_Q", "DAYS_TO_CLOSE", sorted(med_days["CLOSED_Q"].unique()))
    ev5 = st.altair_chart(make_selectable(c5), use_container_width=True, on_select="rerun", key="med_days_nb")
    if ev5 and ev5.selection and ev5.selection.get("param_1"):
        pts = ev5.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.divider()

st.subheader("Median Pilot-to-Loss Duration")
st.caption("Formal pilot entry → loss. Isolates whether pilots that fail are dragging or dying fast.")

piloted_lost = lost_deals.dropna(subset=["DATE_ENTERED_FORMAL_PILOT_CLASSIC", "DEAL_CLOSED_DATE"]).copy()
piloted_lost["PILOT_TO_CLOSE_DAYS"] = (pd.to_datetime(piloted_lost["DEAL_CLOSED_DATE"]) - pd.to_datetime(piloted_lost["DATE_ENTERED_FORMAL_PILOT_CLASSIC"])).dt.days
piloted_lost = piloted_lost[piloted_lost["PILOT_TO_CLOSE_DAYS"] > 0]

if breakdown_col:
    med_pilot = piloted_lost.groupby(["CLOSED_Q", breakdown_col]).agg(PILOT_TO_CLOSE_DAYS=("PILOT_TO_CLOSE_DAYS", "median"), Deal_Count=("DEAL_NAME", "nunique"), Lost_ARR=("DEAL_TOTAL_ARR", "sum")).round(2).reset_index().sort_values("CLOSED_Q")
    c6 = alt.Chart(med_pilot).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_pilot["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("PILOT_TO_CLOSE_DAYS:Q", title="Median Days (Pilot → Loss)"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("PILOT_TO_CLOSE_DAYS:Q", title="Median Days", format=".1f"), alt.Tooltip("Deal_Count:Q", title="Deals", format=","), alt.Tooltip("Lost_ARR:Q", title="Lost ARR", format=",.0f")],
    ).properties(height=300)
    ev6 = st.altair_chart(make_selectable(c6), use_container_width=True, on_select="rerun", key="med_pilot_bd")
    if ev6 and ev6.selection and ev6.selection.get("param_1"):
        pts = ev6.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
            update_drill(breakdown_col, pts[0].get(breakdown_col))
else:
    med_pilot = piloted_lost.groupby("CLOSED_Q").agg(PILOT_TO_CLOSE_DAYS=("PILOT_TO_CLOSE_DAYS", "median"), Deal_Count=("DEAL_NAME", "nunique"), Lost_ARR=("DEAL_TOTAL_ARR", "sum")).round(2).reset_index().sort_values("CLOSED_Q")
    c6 = alt.Chart(med_pilot).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_pilot["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("PILOT_TO_CLOSE_DAYS:Q", title="Median Days (Pilot → Loss)"),
        tooltip=["CLOSED_Q", alt.Tooltip("PILOT_TO_CLOSE_DAYS:Q", title="Median Days", format=".1f"), alt.Tooltip("Deal_Count:Q", title="Deals", format=","), alt.Tooltip("Lost_ARR:Q", title="Lost ARR", format=",.0f")],
    ).properties(height=300)
    c6 = add_labels(c6, med_pilot, "CLOSED_Q", "PILOT_TO_CLOSE_DAYS", sorted(med_pilot["CLOSED_Q"].unique()))
    ev6 = st.altair_chart(make_selectable(c6), use_container_width=True, on_select="rerun", key="med_pilot_nb")
    if ev6 and ev6.selection and ev6.selection.get("param_1"):
        pts = ev6.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.divider()
st.header("Win / Loss Analysis")

st.subheader("Loss Rate — Piloted vs Non-Piloted")
st.caption("% lost within each POC indication group — tells you whether running a pilot improves win odds, and whether that's changing.")

closed_no_poc = closed_deals[closed_deals["POC_INDICATION"] == "No POC"]
closed_with_poc = closed_deals[closed_deals["POC_INDICATION"] != "No POC"]

col_left, col_right = st.columns(2)
with col_left:
    st.markdown("**No POC**")
    if breakdown_col:
        no_poc_rate = closed_no_poc.groupby(["CLOSED_Q", breakdown_col]).apply(calc_loss_rate, include_groups=False).reset_index().sort_values("CLOSED_Q")
        c7a = alt.Chart(no_poc_rate).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(no_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        ev7a = st.altair_chart(make_selectable(c7a), use_container_width=True, on_select="rerun", key="lr_no_poc")
        if ev7a and ev7a.selection and ev7a.selection.get("param_1"):
            pts = ev7a.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "No POC")
    else:
        no_poc_rate = closed_no_poc.groupby("CLOSED_Q").apply(calc_loss_rate, include_groups=False).reset_index().sort_values("CLOSED_Q")
        c7a = alt.Chart(no_poc_rate).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(no_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            tooltip=["CLOSED_Q", alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        c7a = add_labels(c7a, no_poc_rate, "CLOSED_Q", "Loss Rate %", sorted(no_poc_rate["CLOSED_Q"].unique()), is_pct=True)
        ev7a = st.altair_chart(make_selectable(c7a), use_container_width=True, on_select="rerun", key="lr_no_poc_nb")
        if ev7a and ev7a.selection and ev7a.selection.get("param_1"):
            pts = ev7a.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "No POC")
with col_right:
    st.markdown("**With POC**")
    if breakdown_col:
        with_poc_rate = closed_with_poc.groupby(["CLOSED_Q", breakdown_col]).apply(calc_loss_rate, include_groups=False).reset_index().sort_values("CLOSED_Q")
        c7b = alt.Chart(with_poc_rate).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(with_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        ev7b = st.altair_chart(make_selectable(c7b), use_container_width=True, on_select="rerun", key="lr_with_poc")
        if ev7b and ev7b.selection and ev7b.selection.get("param_1"):
            pts = ev7b.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")
    else:
        with_poc_rate = closed_with_poc.groupby("CLOSED_Q").apply(calc_loss_rate, include_groups=False).reset_index().sort_values("CLOSED_Q")
        c7b = alt.Chart(with_poc_rate).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(with_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            tooltip=["CLOSED_Q", alt.Tooltip("Loss Rate %:Q", format=".1f"), alt.Tooltip("Lost Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
        c7b = add_labels(c7b, with_poc_rate, "CLOSED_Q", "Loss Rate %", sorted(with_poc_rate["CLOSED_Q"].unique()), is_pct=True)
        ev7b = st.altair_chart(make_selectable(c7b), use_container_width=True, on_select="rerun", key="lr_with_poc_nb")
        if ev7b and ev7b.selection and ev7b.selection.get("param_1"):
            pts = ev7b.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")

st.divider()

st.subheader("Loss Rate by Stage and Dwell Time")
st.caption("How loss risk rises with time, per stage. Shows which stage is most 'dangerous' the longer a deal sits.")

def hhmmss_to_days(series):
    def parse_val(v):
        if pd.isna(v) or v == "" or v is None:
            return None
        parts = str(v).split(":")
        if len(parts) != 3:
            return None
        try:
            return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) / 86400
        except (ValueError, TypeError):
            return None
    return series.apply(parse_val)

stage_time_cols = {
    "Demo/Presentation": "CUMULATIVE_TIME_IN_DEMO__PRESENTATION__CLASSIC_HHMMSS",
    "Business Validation": "CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS",
    "Formal Pilot": "CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS",
    "Business Case Confirmation": "CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS",
    "Negotiation/Legal": "CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC_HHMMSS",
}

time_buckets = [0, 30, 60, 90, 9999]
time_labels = ["<30d", "30-60d", "60-90d", "90d+"]
cumulative_thresholds = [0, 30, 60, 90]
cumulative_labels = ["≥0d", "≥30d", "≥60d", "≥90d"]

dwell_cumulative = st.toggle("Cumulative mode", value=True, key="dwell_cumulative",
    help="Exclusive: deals bucketed by exact dwell time range. Cumulative: each bucket includes all deals that reached at least that threshold.")
if dwell_cumulative:
    st.caption("💡 *Among deals that spent **at least** N days in this stage, what % was lost?* — useful for setting intervention triggers.")
else:
    st.caption("💡 *Among deals that spent **exactly** this time range in this stage, what % was lost?* — useful for spotting the danger-zone duration.")

heatmap_rows = []
for stage_name, col_name in stage_time_cols.items():
    if col_name in closed_deals.columns:
        temp = closed_deals[[col_name, "DEAL_STAGE", "DEAL_NAME"]].copy()
        temp["days"] = hhmmss_to_days(temp[col_name])
        if stage_name == "Demo/Presentation":
            temp = temp.dropna(subset=["days"])
        else:
            temp = temp.dropna(subset=["days"])
            temp = temp[temp["days"] >= 1]
        if dwell_cumulative:
            for threshold, label in zip(cumulative_thresholds, cumulative_labels):
                bucket_df = temp[temp["days"] >= threshold]
                total = bucket_df["DEAL_NAME"].nunique()
                lost = bucket_df[bucket_df["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_NAME"].nunique()
                rate = round(lost / max(total, 1) * 100)
                heatmap_rows.append({"Stage": stage_name, "Dwell Time": label, "Loss Rate %": rate, "Total Deals": total})
        else:
            temp["bucket"] = pd.cut(temp["days"], bins=time_buckets, labels=time_labels, right=False)
            for bucket in time_labels:
                bucket_df = temp[temp["bucket"] == bucket]
                total = bucket_df["DEAL_NAME"].nunique()
                lost = bucket_df[bucket_df["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_NAME"].nunique()
                rate = round(lost / max(total, 1) * 100)
                heatmap_rows.append({"Stage": stage_name, "Dwell Time": bucket, "Loss Rate %": rate, "Total Deals": total})

active_time_labels = cumulative_labels if dwell_cumulative else time_labels

if heatmap_rows:
    heatmap_df = pd.DataFrame(heatmap_rows)
    heatmap_df["Label"] = heatmap_df["Loss Rate %"].apply(lambda x: f"{x:.0f}%")
    stage_order = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
    heatmap_chart = alt.Chart(heatmap_df).mark_rect().encode(
        x=alt.X("Dwell Time:N", sort=active_time_labels, title="Dwell Time"),
        y=alt.Y("Stage:N", sort=stage_order, title="Stage"),
        color=alt.Color("Loss Rate %:Q", scale=alt.Scale(range=["#f7f7f7", "#fdd", "#fcb", "#f99", "#f77", "#e55", "#c33"], domain=[0, 100]), legend=alt.Legend(title="Loss Rate %")),
        tooltip=["Stage", "Dwell Time", alt.Tooltip("Loss Rate %:Q", format=".0f"), "Total Deals"],
    ).properties(height=350)
    text = alt.Chart(heatmap_df).mark_text(fontSize=12).encode(
        x=alt.X("Dwell Time:N", sort=active_time_labels),
        y=alt.Y("Stage:N", sort=stage_order),
        text="Label:N",
        color=alt.condition(alt.datum["Loss Rate %"] > 50, alt.value("white"), alt.value("#333")),
    )
    st.altair_chart(heatmap_chart + text, use_container_width=True)
else:
    st.info("No dwell time data available.")

st.divider()

st.subheader("ARR Loss Rate by Stage and Dwell Time")
st.caption("Lost ARR as % of total ARR per stage/dwell bucket — shows where the biggest revenue leakage happens.")

arr_heatmap_rows = []
for stage_name, col_name in stage_time_cols.items():
    if col_name in closed_deals.columns:
        temp = closed_deals[[col_name, "DEAL_STAGE", "DEAL_NAME", "DEAL_TOTAL_ARR"]].copy()
        temp["days"] = hhmmss_to_days(temp[col_name])
        if stage_name == "Demo/Presentation":
            temp = temp.dropna(subset=["days"])
        else:
            temp = temp.dropna(subset=["days"])
            temp = temp[temp["days"] >= 1]
        if dwell_cumulative:
            for threshold, label in zip(cumulative_thresholds, cumulative_labels):
                bucket_df = temp[temp["days"] >= threshold]
                total_arr = bucket_df["DEAL_TOTAL_ARR"].sum()
                lost_bucket = bucket_df[bucket_df["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]
                lost_arr = lost_bucket["DEAL_TOTAL_ARR"].sum()
                total_deals = bucket_df["DEAL_NAME"].nunique()
                lost_deals_count = lost_bucket["DEAL_NAME"].nunique()
                rate = round(lost_arr / max(total_arr, 1) * 100)
                arr_heatmap_rows.append({"Stage": stage_name, "Dwell Time": label, "ARR Loss %": rate, "Total ARR": round(total_arr), "Lost ARR": round(lost_arr), "Total Deals": total_deals, "Lost Deals": lost_deals_count})
        else:
            temp["bucket"] = pd.cut(temp["days"], bins=time_buckets, labels=time_labels, right=False)
            for bucket in time_labels:
                bucket_df = temp[temp["bucket"] == bucket]
                total_arr = bucket_df["DEAL_TOTAL_ARR"].sum()
                lost_bucket = bucket_df[bucket_df["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]
                lost_arr = lost_bucket["DEAL_TOTAL_ARR"].sum()
                total_deals = bucket_df["DEAL_NAME"].nunique()
                lost_deals_count = lost_bucket["DEAL_NAME"].nunique()
                rate = round(lost_arr / max(total_arr, 1) * 100)
                arr_heatmap_rows.append({"Stage": stage_name, "Dwell Time": bucket, "ARR Loss %": rate, "Total ARR": round(total_arr), "Lost ARR": round(lost_arr), "Total Deals": total_deals, "Lost Deals": lost_deals_count})

if arr_heatmap_rows:
    arr_heatmap_df = pd.DataFrame(arr_heatmap_rows)
    arr_heatmap_df["Label"] = arr_heatmap_df["ARR Loss %"].apply(lambda x: f"{x:.0f}%")
    def fmt_arr(v):
        if v >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        elif v >= 1_000:
            return f"${v/1_000:.0f}K"
        return f"${v:.0f}"
    arr_heatmap_df["Lost ARR $"] = arr_heatmap_df["Lost ARR"].apply(fmt_arr)
    arr_heatmap_df["Total ARR $"] = arr_heatmap_df["Total ARR"].apply(fmt_arr)
    arr_stage_order = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
    arr_heatmap_chart = alt.Chart(arr_heatmap_df).mark_rect().encode(
        x=alt.X("Dwell Time:N", sort=active_time_labels, title="Dwell Time"),
        y=alt.Y("Stage:N", sort=arr_stage_order, title="Stage"),
        color=alt.Color("ARR Loss %:Q", scale=alt.Scale(range=["#f7f7f7", "#fdd", "#fcb", "#f99", "#f77", "#e55", "#c33"], domain=[0, 100]), legend=alt.Legend(title="ARR Loss %")),
        tooltip=["Stage", "Dwell Time", alt.Tooltip("ARR Loss %:Q", format=".0f"), "Lost ARR $:N", "Total ARR $:N", "Total Deals:Q", "Lost Deals:Q"],
    ).properties(height=350)
    arr_text = alt.Chart(arr_heatmap_df).mark_text(fontSize=12).encode(
        x=alt.X("Dwell Time:N", sort=active_time_labels),
        y=alt.Y("Stage:N", sort=arr_stage_order),
        text="Label:N",
        color=alt.condition(alt.datum["ARR Loss %"] > 50, alt.value("white"), alt.value("#333")),
    )
    st.altair_chart(arr_heatmap_chart + arr_text, use_container_width=True)
else:
    st.info("No ARR dwell time data available.")

if dwell_cumulative:
    with st.expander("How to read"):
        st.markdown("""Each column includes all deals that spent **at least** that long. ≥90d is a subset of ≥60d, which is a subset of ≥30d.

- **Rate increases** (e.g., 51% → 83% → 100%): Lingering is dangerous — set intervention triggers.
- **Rate decreases** (e.g., 10% → 0%): Losses happen fast — surviving past N days is a good signal.""")
else:
    with st.expander("How to read"):
        st.markdown("""Each deal appears in **exactly one** bucket based on its total dwell time. Buckets are mutually exclusive.

- **One bucket spikes** (e.g., 60-90d = 85%): That duration is the danger zone for this stage.
- **All buckets similar** (e.g., 65%, 68%, 70%): Dwell time isn't a strong predictor here.""")

if arr_heatmap_rows:
    st.markdown("---")
    st.markdown("**Recommended Max Dwell Time per Stage**")
    stage_order_workflow = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
    workflow_items = []
    for stage_name in stage_order_workflow:
        col_name = stage_time_cols.get(stage_name)
        if not col_name or col_name not in closed_deals.columns:
            continue
        temp = closed_deals[[col_name, "DEAL_STAGE"]].copy()
        temp["days"] = hhmmss_to_days(temp[col_name])
        temp = temp.dropna(subset=["days"])
        if stage_name != "Demo/Presentation":
            temp = temp[temp["days"] >= 1]
        won_days = temp[temp["DEAL_STAGE"].str.lower().str.contains("closed won", na=False)]["days"]
        if won_days.empty:
            continue
        p75 = int(won_days.quantile(0.75))
        workflow_items.append(f"- **{stage_name}**: {p75} days")
    if workflow_items:
        st.markdown("\n".join(workflow_items))
        st.caption("75th percentile of won deals — most winners close faster than this.")

st.divider()

st.subheader("Time in Stage — All Closed Deals")
st.caption("Median days in each stage by quarter. Stages below 1 day excluded.")

stage_grid_order = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
stage_cols_grid = st.columns(2)

for i, stage_name in enumerate(stage_grid_order):
    col_name = stage_time_cols.get(stage_name)
    if not col_name or col_name not in closed_deals.columns:
        continue
    cols_needed = ["CLOSED_Q", col_name, "DEAL_NAME", "DEAL_TOTAL_ARR"]
    if breakdown_col and breakdown_col in closed_deals.columns:
        cols_needed.append(breakdown_col)
    temp = closed_deals[cols_needed].copy()
    temp["Days"] = hhmmss_to_days(temp[col_name])
    if stage_name == "Demo/Presentation":
        temp = temp.dropna(subset=["Days"])
    else:
        temp = temp.dropna(subset=["Days"])
        temp = temp[temp["Days"] >= 1]
    if temp.empty:
        continue

    if breakdown_col and breakdown_col in temp.columns:
        med = temp.groupby(["CLOSED_Q", breakdown_col]).agg(
            **{"Median Days": ("Days", "median"), "Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}
        ).round(1).reset_index().sort_values("CLOSED_Q")

        chart = alt.Chart(med).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", title="Closed Quarter", sort=sorted(med["CLOSED_Q"].unique())),
            y=alt.Y("Median Days:Q", title="Median Days"),
            color=alt.Color(f"{breakdown_col}:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Median Days:Q", format=".1f"), alt.Tooltip("Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)
    else:
        med = temp.groupby("CLOSED_Q").agg(
            **{"Median Days": ("Days", "median"), "Deals": ("DEAL_NAME", "nunique"), "Lost ARR": ("DEAL_TOTAL_ARR", "sum")}
        ).round(1).reset_index().sort_values("CLOSED_Q")

        chart = alt.Chart(med).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", title="Closed Quarter", sort=sorted(med["CLOSED_Q"].unique())),
            y=alt.Y("Median Days:Q", title="Median Days"),
            tooltip=["CLOSED_Q", alt.Tooltip("Median Days:Q", format=".1f"), alt.Tooltip("Deals:Q", format=","), alt.Tooltip("Lost ARR:Q", format=",.0f")],
        ).properties(height=250)

    with stage_cols_grid[i % 2]:
        st.markdown(f"**{stage_name}**")
        ev_stage = st.altair_chart(make_selectable(chart), use_container_width=True, on_select="rerun", key=f"stage_time_{i}")
        if ev_stage and ev_stage.selection and ev_stage.selection.get("param_1"):
            pts = ev_stage.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.divider()

st.subheader("Raw Deals")
st.caption("Click any chart element above to filter this table. Use the button to clear selection.")

drill_col1, drill_col2 = st.columns([1, 5])
with drill_col1:
    if st.button("Clear selection"):
        st.session_state.drill_filter = {}
        st.rerun()

if st.session_state.drill_filter:
    st.markdown(f"**Active filters:** {st.session_state.drill_filter}")

drill_data = filtered.copy()
for col, val in st.session_state.drill_filter.items():
    if col in drill_data.columns and val is not None:
        drill_data = drill_data[drill_data[col] == val]

if drill_data.empty and st.session_state.drill_filter:
    st.warning(f"No deals match the current drill filter. Try clearing the selection.")

display_cols = [c for c in ["DEAL_NAME", "COMPANY_NAME", "DEAL_TOTAL_ARR", "CLOSED_LOST_REASON", "SEGMENT", "DEAL_STAGE", "DEAL_STAGE_BEFORE_CLOSED", "POC_INDICATION", "DEAL_TEAM_NAME", "GEOGRAPHY", "DEAL_SOURCE", "CLOSED_Q", "QUALIFIED_DATE", "DEAL_CLOSED_DATE"] if c in drill_data.columns]
st.dataframe(drill_data[display_cols].sort_values("DEAL_CLOSED_DATE", ascending=False) if not drill_data.empty else drill_data, use_container_width=True, hide_index=True)