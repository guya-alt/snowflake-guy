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
        closed_deals.segment_ AS segment,
        fact_deals.deal_stage,
        CASE
            WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 1)::INT * 3600
                + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 2)::INT * 60
                + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 3)::INT > 86400
            THEN 'With POC'
            ELSE 'No POC'
        END AS poc_indication,
        fact_deals.deal_team_name,
        fact_deals.sk_sales_owner,
        dim_employee.display_name AS owner_name,
        DIM_COMPANY.GEOGRAPHY,
        fact_deals.mega_source AS deal_source,
        closed_deals.DEAL_STAGE_BEFORE_CLOSED,
        CASE
            WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 1)::INT * 3600
                + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 2)::INT * 60
                + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 3)::INT > 86400
            THEN closed_deals.DATE_ENTERED_FORMAL_PILOT_CLASSIC
        END AS DATE_ENTERED_FORMAL_PILOT_CLASSIC,
        fact_deals.deal_closed_date,
        fact_deals.qualified_date,
        fact_deals.deal_name,
        fact_deals.deal_total_arr,
        fact_deals.closed_lost_reason,

        -- stage times: NULL when < 1 day
        closed_deals.CUMULATIVE_TIME_IN_DEMO__PRESENTATION__CLASSIC AS CUMULATIVE_TIME_IN_DEMO_PRESENTATION_CLASSIC_HHMMSS,

        CASE WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC, ':', 1)::INT * 3600
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC, ':', 2)::INT * 60
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC, ':', 3)::INT > 86400
             THEN closed_deals.CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC
        END AS CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS,

        CASE WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 1)::INT * 3600
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 2)::INT * 60
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC, ':', 3)::INT > 86400
             THEN closed_deals.CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC
        END AS CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS,

        CASE WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC, ':', 1)::INT * 3600
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC, ':', 2)::INT * 60
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC, ':', 3)::INT > 86400
             THEN closed_deals.CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC
        END AS CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS,

        CASE WHEN SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC, ':', 1)::INT * 3600
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC, ':', 2)::INT * 60
                  + SPLIT_PART(closed_deals.CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC, ':', 3)::INT > 86400
             THEN closed_deals.CUMULATIVE_TIME_IN_NEGOTIATION__LEGAL_CLASSIC
        END AS CUMULATIVE_TIME_IN_NEGOTIATION_LEGAL_CLASSIC_HHMMSS

    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS AS fact_deals
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY AS dim_company
        ON dim_company.sk_company = fact_deals.sk_company
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE AS dim_employee
        ON dim_employee.sk_employee = fact_deals.sk_sales_owner
    LEFT JOIN PORT_ANALYTICS_DEV.SALES_ANALYTICS.NEWBIZ_CLASSIC_CLOSED_DEAL_BY_STAGE_2026Q2_FINAL AS closed_deals
        ON closed_deals.DEAL_ID = fact_deals.deal_crm_id
    WHERE fact_deals.pipeline ILIKE '%classic%'
        AND fact_deals.deal_type ILIKE '%new%business%'
        AND fact_deals.qualified_date >= '2025-01-01'
        AND fact_deals.deal_closed_date <= CURRENT_DATE()
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

def update_drill(key, value):
    if value:
        st.session_state.drill_filter[key] = value
    elif key in st.session_state.drill_filter:
        del st.session_state.drill_filter[key]

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

lost_metric = st.radio("Metric", ["Deals", "ARR"], horizontal=True, key="lost_metric")

if lost_metric == "Deals":
    st.caption("Quarterly count of lost deals (Classic, New Business)")
    y_field = "Lost Deals"
    y_title = "Lost Deals (count)"
    if breakdown_col:
        chart_data = lost_deals.groupby(["CLOSED_Q", breakdown_col])["DEAL_NAME"].nunique().reset_index().rename(columns={"DEAL_NAME": y_field}).sort_values("CLOSED_Q")
    else:
        chart_data = lost_deals.groupby("CLOSED_Q")["DEAL_NAME"].nunique().reset_index().rename(columns={"DEAL_NAME": y_field}).sort_values("CLOSED_Q")
else:
    st.caption("Quarterly total ARR lost (Classic, New Business)")
    y_field = "Lost ARR"
    y_title = "Lost ARR ($)"
    if breakdown_col:
        chart_data = lost_deals.groupby(["CLOSED_Q", breakdown_col])["DEAL_TOTAL_ARR"].sum().reset_index().rename(columns={"DEAL_TOTAL_ARR": y_field}).sort_values("CLOSED_Q")
    else:
        chart_data = lost_deals.groupby("CLOSED_Q")["DEAL_TOTAL_ARR"].sum().reset_index().rename(columns={"DEAL_TOTAL_ARR": y_field}).sort_values("CLOSED_Q")

if breakdown_col:
    c = alt.Chart(chart_data).mark_bar().encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(chart_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y(f"{y_field}:Q", title=y_title),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, f"{y_field}"],
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
        tooltip=["CLOSED_Q", f"{y_field}"],
    ).properties(height=350)
    event = st.altair_chart(make_selectable(c), use_container_width=True, on_select="rerun", key="lost_over_time_no_bd")
    if event and event.selection and event.selection.get("param_1"):
        pts = event.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

st.subheader("Closed-Lost Share Over Time")
st.caption("100% stacked — proportion of lost deals by breakdown")

share_metric = st.radio("Share Metric", ["Deals", "ARR"], horizontal=True, key="share_metric")

if breakdown_col:
    if share_metric == "Deals":
        share_val_field = "Lost Deals"
        share_data = lost_deals.groupby(["CLOSED_Q", breakdown_col])["DEAL_NAME"].nunique().reset_index().rename(columns={"DEAL_NAME": "Lost Deals"}).sort_values("CLOSED_Q")
    else:
        share_val_field = "Lost ARR"
        share_data = lost_deals.groupby(["CLOSED_Q", breakdown_col])["DEAL_TOTAL_ARR"].sum().reset_index().rename(columns={"DEAL_TOTAL_ARR": "Lost ARR"}).sort_values("CLOSED_Q")

    pct_data = share_data.copy()
    totals = pct_data.groupby("CLOSED_Q")[share_val_field].transform("sum")
    pct_data["Pct"] = (pct_data[share_val_field] / totals * 100).round(2)
    c2 = alt.Chart(pct_data).mark_bar().encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(pct_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Pct:Q", stack="normalize", title=f"% of {share_val_field}"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Pct:Q", format=".1f")],
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

closed_deals = filtered[
    filtered["DEAL_STAGE"].str.lower().str.contains("closed lost|closed won", na=False, regex=True)
]

def calc_loss_rate(g):
    lost = g[g["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_NAME"].nunique()
    total = g["DEAL_NAME"].nunique()
    return round(lost / max(total, 1) * 100, 2)

if breakdown_col:
    rate_data = (
        closed_deals.groupby(["CLOSED_Q", breakdown_col])
        .apply(calc_loss_rate)
        .reset_index(name="Loss Rate %")
        .sort_values("CLOSED_Q")
    )
    c3 = alt.Chart(rate_data).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(rate_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Loss Rate %:Q", title="Loss Rate %"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, "Loss Rate %"],
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
        .apply(calc_loss_rate)
        .reset_index(name="Loss Rate %")
        .sort_values("CLOSED_Q")
    )
    c3 = alt.Chart(rate_data).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(rate_data["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("Loss Rate %:Q", title="Loss Rate %"),
        tooltip=["CLOSED_Q", "Loss Rate %"],
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

poc_lost = lost_deals.groupby(["CLOSED_Q", "POC_INDICATION"])["DEAL_NAME"].nunique().reset_index(name="Count")

if breakdown_col:
    lost_no_poc_bd = lost_deals[lost_deals["POC_INDICATION"] == "No POC"].groupby(["CLOSED_Q", breakdown_col])["DEAL_NAME"].nunique().reset_index(name="Lost Deals").sort_values("CLOSED_Q")
    lost_with_poc_bd = lost_deals[lost_deals["POC_INDICATION"] != "No POC"].groupby(["CLOSED_Q", breakdown_col])["DEAL_NAME"].nunique().reset_index(name="Lost Deals").sort_values("CLOSED_Q")
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Closed-Lost — No POC**")
        c_np = alt.Chart(lost_no_poc_bd).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_no_poc_bd["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Lost Deals:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, "Lost Deals"],
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
            y=alt.Y("Lost Deals:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, "Lost Deals"],
        ).properties(height=250)
        ev_wp = st.altair_chart(make_selectable(c_wp), use_container_width=True, on_select="rerun", key="poc_yes")
        if ev_wp and ev_wp.selection and ev_wp.selection.get("param_1"):
            pts = ev_wp.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")
else:
    lost_no_poc_data = poc_lost[poc_lost["POC_INDICATION"] == "No POC"].sort_values("CLOSED_Q")
    lost_with_poc_data = poc_lost[poc_lost["POC_INDICATION"] != "No POC"].groupby("CLOSED_Q")["Count"].sum().reset_index().rename(columns={"Count": "Lost Deals"}).sort_values("CLOSED_Q")
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Closed-Lost — No POC**")
        c_np = alt.Chart(lost_no_poc_data).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(lost_no_poc_data["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Count:Q", title="Lost Deals"),
            tooltip=["CLOSED_Q", "Count"],
        ).properties(height=250)
        c_np = add_labels(c_np, lost_no_poc_data, "CLOSED_Q", "Count", sorted(lost_no_poc_data["CLOSED_Q"].unique()))
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
            y=alt.Y("Lost Deals:Q"),
            tooltip=["CLOSED_Q", "Lost Deals"],
        ).properties(height=250)
        c_wp = add_labels(c_wp, lost_with_poc_data, "CLOSED_Q", "Lost Deals", sorted(lost_with_poc_data["CLOSED_Q"].unique()))
        ev_wp = st.altair_chart(make_selectable(c_wp), use_container_width=True, on_select="rerun", key="poc_yes_nb")
        if ev_wp and ev_wp.selection and ev_wp.selection.get("param_1"):
            pts = ev_wp.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")

st.divider()

st.subheader("Where Deals Are Lost")
st.caption("100% stacked — proportion of lost deals by stage before closed, per quarter.")

where_metric = st.radio("Metric", ["Deals", "ARR"], horizontal=True, key="where_metric")

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
    stage_lost_stacked = lost_deals.groupby(group_cols)["DEAL_NAME"].nunique().reset_index(name="Count")
    stage_totals_stacked = stage_lost_stacked.groupby("CLOSED_Q")["Count"].transform("sum")
    stage_lost_stacked["% of Lost Deals"] = (stage_lost_stacked["Count"] / stage_totals_stacked * 100).round(1)
    y_val = "Count:Q"
    y_title = "% of Lost Deals"
    pct_field = "% of Lost Deals"
else:
    group_cols = ["CLOSED_Q", "DEAL_STAGE_BEFORE_CLOSED"] + ([breakdown_col] if breakdown_col else [])
    stage_lost_stacked = lost_deals.groupby(group_cols)["DEAL_TOTAL_ARR"].sum().reset_index(name="Lost ARR")
    stage_totals_stacked = stage_lost_stacked.groupby("CLOSED_Q")["Lost ARR"].transform("sum")
    stage_lost_stacked["% of Lost ARR"] = (stage_lost_stacked["Lost ARR"] / stage_totals_stacked.replace(0, 1) * 100).round(1)
    y_val = "Lost ARR:Q"
    y_title = "% of Lost ARR"
    pct_field = "% of Lost ARR"

c_where = alt.Chart(stage_lost_stacked).mark_bar().encode(
    x=alt.X("CLOSED_Q:N", sort=sorted(stage_lost_stacked["CLOSED_Q"].unique()), title="Closed Quarter"),
    y=alt.Y(y_val, stack="normalize", title=y_title),
    color=alt.Color("DEAL_STAGE_BEFORE_CLOSED:N", sort=STAGE_ORDER, title="Stage Before Closed"),
    tooltip=["CLOSED_Q", "DEAL_STAGE_BEFORE_CLOSED", alt.Tooltip(f"{pct_field}:Q", format=".1f")],
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
    if stage_subset.empty:
        stage_subset = pd.DataFrame({"CLOSED_Q": [], pct_field: []})
    if breakdown_col and breakdown_col in stage_subset.columns:
        c_stage = alt.Chart(stage_subset).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(stage_lost_stacked["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{pct_field}:Q", title=pct_field),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip(f"{pct_field}:Q", format=".1f"), alt.Tooltip("Count:Q" if where_metric == "Deals" else "Lost ARR:Q", title="Deals" if where_metric == "Deals" else "Lost ARR")],
        ).properties(height=200)
    else:
        c_stage = alt.Chart(stage_subset).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(stage_lost_stacked["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y(f"{pct_field}:Q", title=pct_field),
            tooltip=["CLOSED_Q", alt.Tooltip(f"{pct_field}:Q", format=".1f"), alt.Tooltip("Count:Q" if where_metric == "Deals" else "Lost ARR:Q", title="Deals" if where_metric == "Deals" else "Lost ARR")],
        ).properties(height=200)
    with stage_grid_cols[idx % 2]:
        st.markdown(f"**{stage_name}**")
        ev_stg = st.altair_chart(make_selectable(c_stage), use_container_width=True, on_select="rerun", key=f"stage_before_{idx}")
        if ev_stg and ev_stg.selection and ev_stg.selection.get("param_1"):
            pts = ev_stg.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("DEAL_STAGE_BEFORE_CLOSED", stage_name)

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
with reason_col1:
    reason_metric = st.radio("Metric", ["Deals", "ARR"], horizontal=True, key="reason_metric")

reason_time_buckets = [0, 30, 60, 90, 9999]
reason_time_labels = ["<30d", "30-60d", "60-90d", "90d+"]
reason_stage_time_cols = {
    "Demo/Presentation": "CUMULATIVE_TIME_IN_DEMO_PRESENTATION_CLASSIC_HHMMSS",
    "Business Validation": "CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS",
    "Formal Pilot": "CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS",
    "Business Case Confirmation": "CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS",
    "Negotiation/Legal": "CUMULATIVE_TIME_IN_NEGOTIATION_LEGAL_CLASSIC_HHMMSS",
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
    "Product/Fit": ["Missing Feature", "Product", "On-prem", "Security", "No value"],
    "Commercial": ["Budget", "Price", "Freemium"],
    "Competition": ["Competition"],
    "Timing/Engagement": ["Bad timing", "Early stage", "Unable to connect", "no_show"],
    "Internal/Org": ["Champion left/ Company cuts", "Not right company/ persona", "Partnership"],
    "Legal": ["Legal"],
    "Other": ["Other", "UNQ"],
}
REASON_TO_CATEGORY = {}
for cat, reasons in REASON_CATEGORIES.items():
    for r in reasons:
        REASON_TO_CATEGORY[r] = cat

categorize_reasons = st.toggle("Categorize lost reasons", value=False, key="categorize_reasons")

if categorize_reasons:
    reason_exploded["REASON"] = reason_exploded["REASON"].map(REASON_TO_CATEGORY).fillna("Other")

if reason_metric == "Deals":
    reason_agg = reason_exploded.groupby(["CLOSED_Q", "REASON"]).agg(Deals=("DEAL_NAME", "nunique"), ARR=("DEAL_TOTAL_ARR", "sum")).reset_index()
    reason_agg["Value"] = reason_agg["Deals"]
    y_title = "% of Lost Deals"
    pct_label = "% of Deals"
else:
    reason_agg = reason_exploded.groupby(["CLOSED_Q", "REASON"]).agg(Deals=("DEAL_NAME", "nunique"), ARR=("DEAL_TOTAL_ARR", "sum")).reset_index()
    reason_agg["Value"] = reason_agg["ARR"]
    y_title = "% of Lost ARR"
    pct_label = "% of ARR"

reason_totals = reason_agg.groupby("CLOSED_Q")["Value"].transform("sum")
reason_agg[pct_label] = (reason_agg["Value"] / reason_totals.replace(0, 1) * 100).round(1)
reason_agg["ARR_Display"] = (reason_agg["ARR"] / 1_000_000).round(2).apply(lambda x: f"${x:.1f}M")

c_reason = alt.Chart(reason_agg).mark_bar().encode(
    x=alt.X("CLOSED_Q:N", sort=sorted(reason_agg["CLOSED_Q"].unique()), title="Closed Quarter"),
    y=alt.Y("Value:Q", stack="normalize", title=y_title),
    color=alt.Color("REASON:N", title="Lost Reason"),
    tooltip=["CLOSED_Q", "REASON", alt.Tooltip(f"{pct_label}:Q", format=".1f"), alt.Tooltip("ARR_Display:N", title="ARR"), alt.Tooltip("Deals:Q", title="Deals")],
).properties(height=350)
ev_reason = st.altair_chart(make_selectable(c_reason), use_container_width=True, on_select="rerun", key="lost_reason")
if ev_reason and ev_reason.selection and ev_reason.selection.get("param_1"):
    pts = ev_reason.selection["param_1"]
    if pts:
        update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))

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
    med_days = lost_with_dates.groupby(["CLOSED_Q", breakdown_col])["DAYS_TO_CLOSE"].median().round(2).reset_index().sort_values("CLOSED_Q")
    c5 = alt.Chart(med_days).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_days["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("DAYS_TO_CLOSE:Q", title="Median Days (Qualified → Closed)"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, "DAYS_TO_CLOSE"],
    ).properties(height=300)
    ev5 = st.altair_chart(make_selectable(c5), use_container_width=True, on_select="rerun", key="med_days_bd")
    if ev5 and ev5.selection and ev5.selection.get("param_1"):
        pts = ev5.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
            update_drill(breakdown_col, pts[0].get(breakdown_col))
else:
    med_days = lost_with_dates.groupby("CLOSED_Q")["DAYS_TO_CLOSE"].median().round(2).reset_index().sort_values("CLOSED_Q")
    c5 = alt.Chart(med_days).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_days["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("DAYS_TO_CLOSE:Q", title="Median Days (Qualified → Closed)"),
        tooltip=["CLOSED_Q", "DAYS_TO_CLOSE"],
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
    med_pilot = piloted_lost.groupby(["CLOSED_Q", breakdown_col]).agg(PILOT_TO_CLOSE_DAYS=("PILOT_TO_CLOSE_DAYS", "median"), Deal_Count=("DEAL_NAME", "nunique")).round(2).reset_index().sort_values("CLOSED_Q")
    c6 = alt.Chart(med_pilot).mark_line(point=True).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_pilot["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("PILOT_TO_CLOSE_DAYS:Q", title="Median Days (Pilot → Loss)"),
        color=alt.Color(f"{breakdown_col}:N"),
        tooltip=["CLOSED_Q", breakdown_col, "PILOT_TO_CLOSE_DAYS", "Deal_Count"],
    ).properties(height=300)
    ev6 = st.altair_chart(make_selectable(c6), use_container_width=True, on_select="rerun", key="med_pilot_bd")
    if ev6 and ev6.selection and ev6.selection.get("param_1"):
        pts = ev6.selection["param_1"]
        if pts:
            update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
            update_drill(breakdown_col, pts[0].get(breakdown_col))
else:
    med_pilot = piloted_lost.groupby("CLOSED_Q").agg(PILOT_TO_CLOSE_DAYS=("PILOT_TO_CLOSE_DAYS", "median"), Deal_Count=("DEAL_NAME", "nunique")).round(2).reset_index().sort_values("CLOSED_Q")
    c6 = alt.Chart(med_pilot).mark_area(line=True, point=True, opacity=0.3).encode(
        x=alt.X("CLOSED_Q:N", sort=sorted(med_pilot["CLOSED_Q"].unique()), title="Closed Quarter"),
        y=alt.Y("PILOT_TO_CLOSE_DAYS:Q", title="Median Days (Pilot → Loss)"),
        tooltip=["CLOSED_Q", "PILOT_TO_CLOSE_DAYS", "Deal_Count"],
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
        no_poc_rate = closed_no_poc.groupby(["CLOSED_Q", breakdown_col]).apply(calc_loss_rate).reset_index(name="Loss Rate %").sort_values("CLOSED_Q")
        c7a = alt.Chart(no_poc_rate).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(no_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, "Loss Rate %"],
        ).properties(height=250)
        ev7a = st.altair_chart(make_selectable(c7a), use_container_width=True, on_select="rerun", key="lr_no_poc")
        if ev7a and ev7a.selection and ev7a.selection.get("param_1"):
            pts = ev7a.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "No POC")
    else:
        no_poc_rate = closed_no_poc.groupby("CLOSED_Q").apply(calc_loss_rate).reset_index(name="Loss Rate %").sort_values("CLOSED_Q")
        c7a = alt.Chart(no_poc_rate).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(no_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            tooltip=["CLOSED_Q", "Loss Rate %"],
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
        with_poc_rate = closed_with_poc.groupby(["CLOSED_Q", breakdown_col]).apply(calc_loss_rate).reset_index(name="Loss Rate %").sort_values("CLOSED_Q")
        c7b = alt.Chart(with_poc_rate).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(with_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            color=alt.Color(f"{breakdown_col}:N"),
            tooltip=["CLOSED_Q", breakdown_col, "Loss Rate %"],
        ).properties(height=250)
        ev7b = st.altair_chart(make_selectable(c7b), use_container_width=True, on_select="rerun", key="lr_with_poc")
        if ev7b and ev7b.selection and ev7b.selection.get("param_1"):
            pts = ev7b.selection["param_1"]
            if pts:
                update_drill("CLOSED_Q", pts[0].get("CLOSED_Q"))
                update_drill("POC_INDICATION", "With POC")
    else:
        with_poc_rate = closed_with_poc.groupby("CLOSED_Q").apply(calc_loss_rate).reset_index(name="Loss Rate %").sort_values("CLOSED_Q")
        c7b = alt.Chart(with_poc_rate).mark_area(line=True, point=True, opacity=0.3).encode(
            x=alt.X("CLOSED_Q:N", sort=sorted(with_poc_rate["CLOSED_Q"].unique()), title="Closed Quarter"),
            y=alt.Y("Loss Rate %:Q"),
            tooltip=["CLOSED_Q", "Loss Rate %"],
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
    "Demo/Presentation": "CUMULATIVE_TIME_IN_DEMO_PRESENTATION_CLASSIC_HHMMSS",
    "Business Validation": "CUMULATIVE_TIME_IN_BUSINESS_VALIDATION_CLASSIC_HHMMSS",
    "Formal Pilot": "CUMULATIVE_TIME_IN_FORMAL_PILOT_CLASSIC_HHMMSS",
    "Business Case Confirmation": "CUMULATIVE_TIME_IN_BUSINESS_CASE_CONFIRMATION_CLASSIC_HHMMSS",
    "Negotiation/Legal": "CUMULATIVE_TIME_IN_NEGOTIATION_LEGAL_CLASSIC_HHMMSS",
}

time_buckets = [0, 30, 60, 90, 9999]
time_labels = ["<30d", "30-60d", "60-90d", "90d+"]

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
        temp["bucket"] = pd.cut(temp["days"], bins=time_buckets, labels=time_labels, right=False)
        for bucket in time_labels:
            bucket_df = temp[temp["bucket"] == bucket]
            total = bucket_df["DEAL_NAME"].nunique()
            lost = bucket_df[bucket_df["DEAL_STAGE"].str.lower().str.contains("closed lost", na=False)]["DEAL_NAME"].nunique()
            rate = round(lost / max(total, 1) * 100)
            heatmap_rows.append({"Stage": stage_name, "Dwell Time": bucket, "Loss Rate %": rate, "Total Deals": total})

if heatmap_rows:
    heatmap_df = pd.DataFrame(heatmap_rows)
    heatmap_df["Label"] = heatmap_df["Loss Rate %"].apply(lambda x: f"{x:.0f}%")
    stage_order = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
    heatmap_chart = alt.Chart(heatmap_df).mark_rect().encode(
        x=alt.X("Dwell Time:N", sort=time_labels, title="Dwell Time"),
        y=alt.Y("Stage:N", sort=stage_order, title="Stage"),
        color=alt.Color("Loss Rate %:Q", scale=alt.Scale(range=["#f7f7f7", "#fdd", "#fcb", "#f99", "#f77", "#e55", "#c33"], domain=[0, 100]), legend=alt.Legend(title="Loss Rate %")),
        tooltip=["Stage", "Dwell Time", alt.Tooltip("Loss Rate %:Q", format=".0f"), "Total Deals"],
    ).properties(height=350)
    text = alt.Chart(heatmap_df).mark_text(fontSize=12).encode(
        x=alt.X("Dwell Time:N", sort=time_labels),
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
        x=alt.X("Dwell Time:N", sort=time_labels, title="Dwell Time"),
        y=alt.Y("Stage:N", sort=arr_stage_order, title="Stage"),
        color=alt.Color("ARR Loss %:Q", scale=alt.Scale(range=["#f7f7f7", "#fdd", "#fcb", "#f99", "#f77", "#e55", "#c33"], domain=[0, 100]), legend=alt.Legend(title="ARR Loss %")),
        tooltip=["Stage", "Dwell Time", alt.Tooltip("ARR Loss %:Q", format=".0f"), "Lost ARR $:N", "Total ARR $:N", "Total Deals:Q", "Lost Deals:Q"],
    ).properties(height=350)
    arr_text = alt.Chart(arr_heatmap_df).mark_text(fontSize=12).encode(
        x=alt.X("Dwell Time:N", sort=time_labels),
        y=alt.Y("Stage:N", sort=arr_stage_order),
        text="Label:N",
        color=alt.condition(alt.datum["ARR Loss %"] > 50, alt.value("white"), alt.value("#333")),
    )
    st.altair_chart(arr_heatmap_chart + arr_text, use_container_width=True)
else:
    st.info("No ARR dwell time data available.")

st.divider()

st.subheader("Time in Stage — All Closed Deals")
st.caption("Median days in each stage by quarter. Stages below 1 day excluded.")

stage_grid_order = ["Demo/Presentation", "Business Validation", "Formal Pilot", "Business Case Confirmation", "Negotiation/Legal"]
stage_cols_grid = st.columns(2)

for i, stage_name in enumerate(stage_grid_order):
    col_name = stage_time_cols.get(stage_name)
    if not col_name or col_name not in closed_deals.columns:
        continue
    cols_needed = ["CLOSED_Q", col_name, "DEAL_NAME"]
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
            **{"Median Days": ("Days", "median"), "Deals": ("DEAL_NAME", "nunique")}
        ).round(1).reset_index().sort_values("CLOSED_Q")

        chart = alt.Chart(med).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", title="Closed Quarter", sort=sorted(med["CLOSED_Q"].unique())),
            y=alt.Y("Median Days:Q", title="Median Days"),
            color=alt.Color(f"{breakdown_col}:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["CLOSED_Q", breakdown_col, alt.Tooltip("Median Days:Q", format=".1f"), "Deals"],
        ).properties(height=250)
    else:
        med = temp.groupby("CLOSED_Q").agg(
            **{"Median Days": ("Days", "median"), "Deals": ("DEAL_NAME", "nunique")}
        ).round(1).reset_index().sort_values("CLOSED_Q")

        chart = alt.Chart(med).mark_line(point=True).encode(
            x=alt.X("CLOSED_Q:N", title="Closed Quarter", sort=sorted(med["CLOSED_Q"].unique())),
            y=alt.Y("Median Days:Q", title="Median Days"),
            tooltip=["CLOSED_Q", alt.Tooltip("Median Days:Q", format=".1f"), "Deals"],
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

display_cols = [c for c in ["DEAL_NAME", "DEAL_TOTAL_ARR", "segment_", "DEAL_STAGE", "DEAL_STAGE_BEFORE_CLOSED", "POC_INDICATION", "DEAL_TEAM_NAME", "GEOGRAPHY", "DEAL_SOURCE", "CLOSED_Q", "QUALIFIED_DATE", "DEAL_CLOSED_DATE"] if c in drill_data.columns]
st.dataframe(drill_data[display_cols].sort_values("DEAL_CLOSED_DATE", ascending=False), use_container_width=True, hide_index=True)