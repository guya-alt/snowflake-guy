import streamlit as st
import os
import pandas as pd
import altair as alt
from datetime import datetime

st.set_page_config(page_title="New Business Dashboard", layout="wide")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))
session = conn.session()

FIRST_TOUCH_QUERY = """
SELECT DISTINCT
    c.COMPANY_NAME,
    FIRST_VALUE(d.MEGA_SOURCE) OVER (PARTITION BY c.COMPANY_NAME ORDER BY d.DEAL_CREATED_DATE) AS FIRST_TOUCH_MEGA_SOURCE
FROM PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c
LEFT JOIN PORT_ANALYTICS_PROD.DWH.FACT_DEALS d USING (SK_COMPANY)
WHERE c.LIFECYCLE_STAGE = 'Customer'
"""

DEALS_QUERY = """
SELECT
    d.SK_DEAL,
    d.DEAL_NAME,
    d.DEAL_TOTAL_ARR,
    d.BASE_ARR,
    d.DEAL_TOTAL_ARR - COALESCE(d.BASE_ARR, 0) AS NET_NEW_ARR,
    d.DEAL_CLOSED_DATE,
    d.QUALIFIED_DATE,
    d.IS_WON,
    TO_VARCHAR(DATE_TRUNC('QUARTER', d.DEAL_CLOSED_DATE), 'YYYY') || '-Q' || QUARTER(d.DEAL_CLOSED_DATE) AS CLOSED_QUARTER,
    DATEDIFF('day', DATE_TRUNC('QUARTER', d.DEAL_CLOSED_DATE), d.DEAL_CLOSED_DATE) AS DAY_IN_QUARTER,
    TO_VARCHAR(DATE_TRUNC('QUARTER', d.QUALIFIED_DATE), 'YYYY') || '-Q' || QUARTER(d.QUALIFIED_DATE) AS QUALIFIED_QUARTER,
    DATEDIFF('day', DATE_TRUNC('QUARTER', d.QUALIFIED_DATE), d.QUALIFIED_DATE) AS DAY_IN_QUAL_QUARTER,
    c.COMPANY_NAME,
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
    e.DISPLAY_NAME AS OWNER,
    COALESCE(c.CUSTOMER_INTERNAL_TIER, 'None') AS CUSTOMER_INTERNAL_TIER,
    COALESCE(c.SUCCESS_PLAN, 'None') AS SUCCESS_PLAN,
    COALESCE(d.DEAL_TEAM_NAME, 'None') AS DEAL_TEAM_NAME,
    CASE
        WHEN e.ORIGINAL_START_DATE IS NULL THEN 'Unknown'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 6 THEN '0-6 months'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 12 THEN '6-12 months'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 24 THEN '1-2 years'
        ELSE '2+ years'
    END AS OWNER_TENURE
FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c ON d.SK_COMPANY = c.SK_COMPANY
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e ON d.SK_SALES_OWNER = e.SK_EMPLOYEE
WHERE d.DEAL_TYPE = 'newbusiness'
    AND d.QUALIFIED_DATE IS NOT NULL
    AND d.DEAL_TOTAL_ARR > 0
    AND d.IS_CLOSED = TRUE
    AND d.ARCHIVED = FALSE
    AND d._DELETED_TIMESTAMP IS NULL
    AND d.PIPELINE = 'Classic'
"""

PIPELINE_QUERY = """
SELECT
    d.SK_DEAL,
    d.QUALIFIED_DATE,
    TO_VARCHAR(DATE_TRUNC('QUARTER', d.QUALIFIED_DATE), 'YYYY') || '-Q' || QUARTER(d.QUALIFIED_DATE) AS QUALIFIED_QUARTER,
    DATEDIFF('day', DATE_TRUNC('QUARTER', d.QUALIFIED_DATE), d.QUALIFIED_DATE) AS DAY_IN_QUAL_QUARTER,
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
    e.DISPLAY_NAME AS OWNER,
    COALESCE(c.CUSTOMER_INTERNAL_TIER, 'None') AS CUSTOMER_INTERNAL_TIER,
    COALESCE(c.SUCCESS_PLAN, 'None') AS SUCCESS_PLAN,
    COALESCE(d.DEAL_TEAM_NAME, 'None') AS DEAL_TEAM_NAME,
    CASE
        WHEN e.ORIGINAL_START_DATE IS NULL THEN 'Unknown'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 6 THEN '0-6 months'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 12 THEN '6-12 months'
        WHEN DATEDIFF('month', e.ORIGINAL_START_DATE, CURRENT_DATE()) < 24 THEN '1-2 years'
        ELSE '2+ years'
    END AS OWNER_TENURE,
    c.COMPANY_NAME
FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c ON d.SK_COMPANY = c.SK_COMPANY
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e ON d.SK_SALES_OWNER = e.SK_EMPLOYEE
WHERE d.DEAL_TYPE = 'newbusiness'
    AND d.QUALIFIED_DATE IS NOT NULL
    AND d.DEAL_TOTAL_ARR > 0
    AND d.ARCHIVED = FALSE
    AND d._DELETED_TIMESTAMP IS NULL
    AND d.PIPELINE = 'Classic'
"""

if "data" not in st.session_state:
    st.session_state.data = None
    st.session_state.pipeline_data = None
    st.session_state.last_refresh = None

def refresh_data():
    first_touch_df = session.sql(FIRST_TOUCH_QUERY).to_pandas()
    df = session.sql(DEALS_QUERY).to_pandas()
    df["DEAL_CLOSED_DATE"] = pd.to_datetime(df["DEAL_CLOSED_DATE"])
    df["QUALIFIED_DATE"] = pd.to_datetime(df["QUALIFIED_DATE"])
    df = df.merge(first_touch_df, on="COMPANY_NAME", how="left")
    df["FIRST_TOUCH_MEGA_SOURCE"] = df["FIRST_TOUCH_MEGA_SOURCE"].fillna("Unknown")
    st.session_state.data = df
    pdf = session.sql(PIPELINE_QUERY).to_pandas()
    pdf["QUALIFIED_DATE"] = pd.to_datetime(pdf["QUALIFIED_DATE"])
    pdf = pdf.merge(first_touch_df, on="COMPANY_NAME", how="left")
    pdf["FIRST_TOUCH_MEGA_SOURCE"] = pdf["FIRST_TOUCH_MEGA_SOURCE"].fillna("Unknown")
    st.session_state.pipeline_data = pdf
    st.session_state.last_refresh = datetime.now()

if st.session_state.data is None:
    refresh_data()

col_title, col_refresh = st.columns([4, 1])
with col_title:
    st.title("New Business Dashboard")
with col_refresh:
    st.button("Refresh Data", on_click=refresh_data, use_container_width=True)
    if st.session_state.last_refresh:
        st.caption(f"Last refresh: {st.session_state.last_refresh.strftime('%Y-%m-%d %H:%M')}")

st.markdown("New business pipeline analysis — qualified deals with ARR > 0. Net New ARR = `DEAL_ARR - BASE_ARR`. Click chart points to filter the deal table.")

df = st.session_state.data
pipeline_df = st.session_state.pipeline_data
won_df = df[df["IS_WON"] == True].copy()
lost_df = df[df["IS_WON"] == False].copy()

st.sidebar.header("Filters")
segments = st.sidebar.multiselect("Segment", sorted(df["SEGMENT"].dropna().unique()))
eng_sizes = st.sidebar.multiselect("Eng Size Group", ["1-50", "51-150", "151-500", "501-1000", "1000+"])
owners = st.sidebar.multiselect("Owner", sorted(df["OWNER"].dropna().unique()))
geos = st.sidebar.multiselect("Geo", sorted(df["GEO"].dropna().unique()))
industries = st.sidebar.multiselect("Industry", sorted(df["INDUSTRY"].dropna().unique()))
customer_tiers = st.sidebar.multiselect("Customer Internal Tier", sorted(df["CUSTOMER_INTERNAL_TIER"].dropna().unique()))
success_plans = st.sidebar.multiselect("Success Plan", sorted(df["SUCCESS_PLAN"].dropna().unique()))
mega_sources = st.sidebar.multiselect("First Touch Mega Source", sorted(df["FIRST_TOUCH_MEGA_SOURCE"].dropna().unique()))
teams = st.sidebar.multiselect("HubSpot Team", sorted(df["DEAL_TEAM_NAME"].dropna().unique()))
tenures = st.sidebar.multiselect("Owner Tenure", ["0-6 months", "6-12 months", "1-2 years", "2+ years", "Unknown"])
arr_min = float(df["DEAL_TOTAL_ARR"].min())
arr_max = float(df["DEAL_TOTAL_ARR"].max())
arr_range = st.sidebar.slider("ARR Range", min_value=arr_min, max_value=arr_max, value=(arr_min, arr_max))
legend_col = st.sidebar.selectbox("Color by", ["No Segment", "SEGMENT", "ENG_SIZE_GROUP", "OWNER", "GEO", "INDUSTRY", "CUSTOMER_INTERNAL_TIER", "SUCCESS_PLAN", "FIRST_TOUCH_MEGA_SOURCE", "DEAL_TEAM_NAME", "OWNER_TENURE"])

def apply_filters(data):
    d = data.copy()
    if segments:
        d = d[d["SEGMENT"].isin(segments)]
    if eng_sizes:
        d = d[d["ENG_SIZE_GROUP"].isin(eng_sizes)]
    if owners:
        d = d[d["OWNER"].isin(owners)]
    if geos:
        d = d[d["GEO"].isin(geos)]
    if industries:
        d = d[d["INDUSTRY"].isin(industries)]
    if customer_tiers:
        d = d[d["CUSTOMER_INTERNAL_TIER"].isin(customer_tiers)]
    if success_plans:
        d = d[d["SUCCESS_PLAN"].isin(success_plans)]
    if mega_sources:
        d = d[d["FIRST_TOUCH_MEGA_SOURCE"].isin(mega_sources)]
    if teams:
        d = d[d["DEAL_TEAM_NAME"].isin(teams)]
    if tenures:
        d = d[d["OWNER_TENURE"].isin(tenures)]
    if "DEAL_TOTAL_ARR" in d.columns:
        d = d[(d["DEAL_TOTAL_ARR"] >= arr_range[0]) & (d["DEAL_TOTAL_ARR"] <= arr_range[1])]
    return d

filtered_won = apply_filters(won_df)
filtered_lost = apply_filters(lost_df)
filtered_all = apply_filters(df)
filtered_pipeline = apply_filters(pipeline_df)

if legend_col == "No Segment":
    filtered_won["_ALL"] = "All"
    filtered_lost["_ALL"] = "All"
    filtered_all["_ALL"] = "All"
    filtered_pipeline["_ALL"] = "All"
    color_col = "_ALL"
    show_values = True
else:
    color_col = legend_col
    show_values = False



today = pd.Timestamp.today()
current_quarter_start = pd.Timestamp(today.year, ((today.quarter - 1) * 3) + 1, 1)
days_into_quarter = (today - current_quarter_start).days

pacing_won = filtered_won[filtered_won["DAY_IN_QUARTER"] <= days_into_quarter]
pacing_lost = filtered_lost[filtered_lost["DAY_IN_QUARTER"] <= days_into_quarter]
pacing_all = filtered_all[filtered_all["DAY_IN_QUARTER"] <= days_into_quarter]

CHART_HEIGHT = 280
CHART_CONFIG = {"font": "Inter, sans-serif"}

def get_color_scale(data, color_field):
    PALETTE = ["#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b", "#eeca3b", "#b279a2", "#ff9da6", "#9d755d", "#bab0ac"]
    unique_vals = sorted(data[color_field].dropna().unique())
    domain = list(unique_vals)
    range_ = [PALETTE[i % len(PALETTE)] for i in range(len(domain))]
    return alt.Scale(domain=domain, range=range_)

if color_col == "_ALL":
    color_scale = alt.Scale(domain=["All"], range=["#4c78a8"])
else:
    color_scale = get_color_scale(df, color_col)

def fmt_dollar(val):
    if abs(val) >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    elif abs(val) >= 1_000:
        return f"${val/1_000:.0f}K"
    else:
        return f"${val:,.0f}"

def make_line_chart(data, x_field, y_field, y_title, y_format=None, color_field=None, show_text=False, color_scale=None):
    legend_cfg = alt.Legend(orient="bottom", columns=3) if color_field != "_ALL" else None
    is_dollar = y_format and "$" in y_format
    is_pct = y_format == "%"
    axis_fmt = "$~s" if is_dollar else (".0f" if is_pct else (y_format if y_format else None))

    base_encode = {
        "x": alt.X(f"{x_field}:N", title=None, sort=None, axis=alt.Axis(labelAngle=-45)),
        "color": alt.Color(f"{color_field}:N", title=color_field, legend=legend_cfg, scale=color_scale),
    }
    if axis_fmt:
        base_encode["y"] = alt.Y(f"{y_field}:Q", title=y_title, axis=alt.Axis(format=axis_fmt, grid=True, gridOpacity=0.1))
    else:
        base_encode["y"] = alt.Y(f"{y_field}:Q", title=y_title, axis=alt.Axis(grid=True, gridOpacity=0.1))

    sel = alt.selection_point(fields=[x_field, color_field])
    base_encode["opacity"] = alt.condition(sel, alt.value(1), alt.value(0.3))

    tooltip_format = "$,.0f" if is_dollar else (".1f" if is_pct else (y_format if y_format else ",.0f"))
    base_encode["tooltip"] = [
        alt.Tooltip(x_field, title="Quarter"),
        alt.Tooltip(f"{color_field}:N", title="Segment"),
        alt.Tooltip(f"{y_field}:Q", title=y_title + (" (%)" if is_pct else ""), format=tooltip_format),
    ]

    line_chart = (
        alt.Chart(data)
        .mark_line(point=alt.OverlayMarkDef(size=50))
        .encode(**base_encode)
        .add_params(sel)
        .properties(height=CHART_HEIGHT)
    )

    if show_text:
        if is_dollar:
            plot_data = data.copy()
            plot_data["_LABEL"] = plot_data[y_field].apply(fmt_dollar)
            text_layer = (
                alt.Chart(plot_data)
                .mark_text(align="center", dy=-12, fontSize=10)
                .encode(
                    x=alt.X(f"{x_field}:N", sort=None),
                    y=alt.Y(f"{y_field}:Q"),
                    text="_LABEL:N",
                    color=alt.Color(f"{color_field}:N", legend=None, scale=color_scale),
                )
            )
        elif is_pct:
            plot_data = data.copy()
            plot_data["_LABEL"] = plot_data[y_field].apply(lambda v: f"{v:.1f}%")
            text_layer = (
                alt.Chart(plot_data)
                .mark_text(align="center", dy=-12, fontSize=10)
                .encode(
                    x=alt.X(f"{x_field}:N", sort=None),
                    y=alt.Y(f"{y_field}:Q"),
                    text="_LABEL:N",
                    color=alt.Color(f"{color_field}:N", legend=None, scale=color_scale),
                )
            )
        else:
            text_fmt = y_format if y_format else ",.0f"
            text_layer = (
                alt.Chart(data)
                .mark_text(align="center", dy=-12, fontSize=10)
                .encode(
                    x=alt.X(f"{x_field}:N", sort=None),
                    y=alt.Y(f"{y_field}:Q"),
                    text=alt.Text(f"{y_field}:Q", format=text_fmt),
                    color=alt.Color(f"{color_field}:N", legend=None, scale=color_scale),
                )
            )
        return alt.layer(line_chart, text_layer).properties(height=CHART_HEIGHT)

    return line_chart

def render_pair(header, subtitle, left_data, right_data, x_field, y_field, y_title, y_format=None, left_key="total", right_key="pacing"):
    st.markdown(f"### {header}")
    st.caption(subtitle)
    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown(f"**Full Quarter**")
        event_l = st.altair_chart(
            make_line_chart(left_data, x_field, y_field, y_title, y_format, color_col, show_values, color_scale),
            use_container_width=True, on_select="rerun"
        )
    with col_r:
        st.markdown(f"**Pacing (Day {days_into_quarter})**")
        event_r = st.altair_chart(
            make_line_chart(right_data, x_field, y_field, y_title, y_format, color_col, show_values, color_scale),
            use_container_width=True, on_select="rerun"
        )
    return event_l, event_r

with st.container(border=True):
    st.subheader("Qualified Pipeline")
    qual_total = filtered_pipeline.groupby(["QUALIFIED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    qual_pacing = filtered_pipeline[filtered_pipeline["DAY_IN_QUAL_QUARTER"] <= days_into_quarter].groupby(["QUALIFIED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    eq1, eq2 = render_pair("Pipeline Created", "Qualified deals by qualification quarter (all deals)", qual_total, qual_pacing, "QUALIFIED_QUARTER", "DEALS", "Deals")

with st.container(border=True):
    st.subheader("Won")
    won_arr_total = filtered_won.groupby(["CLOSED_QUARTER", color_col], as_index=False)["NET_NEW_ARR"].sum()
    won_arr_pacing = pacing_won.groupby(["CLOSED_QUARTER", color_col], as_index=False)["NET_NEW_ARR"].sum()
    e1, e2 = render_pair("Won ARR", "Net new ARR from closed-won deals by close quarter", won_arr_total, won_arr_pacing, "CLOSED_QUARTER", "NET_NEW_ARR", "ARR", "$,.0f")

    st.divider()

    won_count_total = filtered_won.groupby(["CLOSED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    won_count_pacing = pacing_won.groupby(["CLOSED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    e3, e4 = render_pair("Won Deals", "Number of closed-won deals by close quarter", won_count_total, won_count_pacing, "CLOSED_QUARTER", "DEALS", "Deals")

with st.container(border=True):
    st.subheader("Lost")
    lost_arr_total = filtered_lost.groupby(["CLOSED_QUARTER", color_col], as_index=False)["NET_NEW_ARR"].sum()
    lost_arr_pacing = pacing_lost.groupby(["CLOSED_QUARTER", color_col], as_index=False)["NET_NEW_ARR"].sum()
    e5, e6 = render_pair("Lost ARR", "Net new ARR from closed-lost deals by close quarter", lost_arr_total, lost_arr_pacing, "CLOSED_QUARTER", "NET_NEW_ARR", "ARR", "$,.0f")

    st.divider()

    lost_count_total = filtered_lost.groupby(["CLOSED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    lost_count_pacing = pacing_lost.groupby(["CLOSED_QUARTER", color_col], as_index=False)["SK_DEAL"].count().rename(columns={"SK_DEAL": "DEALS"})
    e7, e8 = render_pair("Lost Deals", "Number of closed-lost deals by close quarter", lost_count_total, lost_count_pacing, "CLOSED_QUARTER", "DEALS", "Deals")

with st.container(border=True):
    st.subheader("Win Rate")
    def cvr_data(data):
        agg = data.groupby(["CLOSED_QUARTER", color_col], as_index=False).agg(TOTAL=("SK_DEAL", "count"), WON=("IS_WON", "sum"))
        agg["WIN_RATE"] = (agg["WON"] / agg["TOTAL"] * 100).round(1)
        return agg

    cvr_total = cvr_data(filtered_all)
    cvr_pacing_data = cvr_data(pacing_all)
    e9, e10 = render_pair("Win Rate", "Won / (Won + Lost) among all qualified closed deals", cvr_total, cvr_pacing_data, "CLOSED_QUARTER", "WIN_RATE", "Win Rate", "%")

detail_df = filtered_won.copy()
detail_source = "won"
selection_made = False

for event in [e1, e2, e3, e4]:
    if event and event.selection and "param_1" in event.selection:
        points = event.selection["param_1"]
        if points:
            selection_made = True
            detail_source = "won"
            q_filter = [p.get("CLOSED_QUARTER") for p in points if p.get("CLOSED_QUARTER")]
            if q_filter:
                detail_df = detail_df[detail_df["CLOSED_QUARTER"].isin(q_filter)]
            l_filter = [p.get(color_col) for p in points if p.get(color_col)]
            if l_filter and color_col != "_ALL":
                detail_df = detail_df[detail_df[color_col].isin(l_filter)]
            break

if not selection_made:
    for event in [e5, e6, e7, e8]:
        if event and event.selection and "param_1" in event.selection:
            points = event.selection["param_1"]
            if points:
                selection_made = True
                detail_source = "lost"
                detail_df = filtered_lost.copy()
                q_filter = [p.get("CLOSED_QUARTER") for p in points if p.get("CLOSED_QUARTER")]
                if q_filter:
                    detail_df = detail_df[detail_df["CLOSED_QUARTER"].isin(q_filter)]
                l_filter = [p.get(color_col) for p in points if p.get(color_col)]
                if l_filter and color_col != "_ALL":
                    detail_df = detail_df[detail_df[color_col].isin(l_filter)]
                break

header_suffix = f" ({detail_source.title()} - filtered)" if selection_made else ""
st.markdown(f"### Deal Details{header_suffix}")

display_cols = ["DEAL_NAME", "COMPANY_NAME", "OWNER", "NET_NEW_ARR", "DEAL_CLOSED_DATE", "QUALIFIED_DATE", "CLOSED_QUARTER", "SEGMENT", "GEO", "INDUSTRY", "ENG_SIZE_GROUP", "CUSTOMER_INTERNAL_TIER", "SUCCESS_PLAN", "FIRST_TOUCH_MEGA_SOURCE"]
st.dataframe(
    detail_df[display_cols].sort_values("DEAL_CLOSED_DATE", ascending=False),
    use_container_width=True,
    hide_index=True,
    column_config={
        "NET_NEW_ARR": st.column_config.NumberColumn("Net New ARR", format="$%,.0f"),
        "DEAL_CLOSED_DATE": st.column_config.DateColumn("Closed"),
        "QUALIFIED_DATE": st.column_config.DateColumn("Qualified"),
        "CLOSED_QUARTER": "Quarter",
        "ENG_SIZE_GROUP": "Eng Size",
    },
)
st.caption(f"{len(detail_df):,} deals")
