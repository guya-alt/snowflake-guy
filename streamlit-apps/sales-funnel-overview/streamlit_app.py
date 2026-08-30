import os
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Sales Funnel Overview", layout="wide")
st.title("Sales Funnel Overview")

conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

# --- Targets (hardcoded) ---
TARGETS = {
    "Grand Total": {"Q1": 1_744_391, "Q2": 4_746_438, "Q3": 6_289_116, "Q4": 8_098_981, "FY": 20_878_926},
}

FUNNEL_STAGE_ORDER = [
    "Discovery",
    "Qualification",
    "Technical Validation",
    "Negotiation",
    "Verbal Commit",
    "Closed Won",
]


@st.cache_data(ttl=600)
def load_deals():
    sql = """
    SELECT
        d.SK_DEAL,
        d.DEAL_NAME,
        d.DEAL_TYPE,
        d.DEAL_STAGE,
        d.DEAL_FUNNEL_STAGE,
        d.DEAL_TEAM_NAME,
        d.PIPELINE,
        d.DEAL_NET_NEW_ARR,
        d.DEAL_TOTAL_ARR,
        d.DEAL_CREATED_DATE,
        d.DEAL_CLOSED_DATE,
        d.QUALIFIED_DATE,
        d.IS_CLOSED,
        d.IS_WON,
        d.FORECAST_CATEGORY,
        e.DISPLAY_NAME AS REP_NAME,
        e.DIVISION AS GEO,
        e.TEAM AS REP_TEAM
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e
        ON d.SK_SALES_OWNER = e.SK_EMPLOYEE
    WHERE d._DELETED_TIMESTAMP IS NULL
      AND d.ARCHIVED = FALSE
    """
    return conn.query(sql)


with st.spinner("Loading deal data..."):
    df = load_deals()

df["DEAL_CLOSED_DATE"] = pd.to_datetime(df["DEAL_CLOSED_DATE"])
df["DEAL_CREATED_DATE"] = pd.to_datetime(df["DEAL_CREATED_DATE"])
df["QUALIFIED_DATE"] = pd.to_datetime(df["QUALIFIED_DATE"])

# --- Sidebar Filters ---
with st.sidebar:
    st.header("Filters")

    if st.button("Clear cache & reload"):
        load_deals.clear()
        st.rerun()

    all_teams = sorted(df["DEAL_TEAM_NAME"].dropna().unique())
    selected_teams = st.multiselect("Team", all_teams, default=all_teams)

    all_deal_types = sorted(df["DEAL_TYPE"].dropna().unique())
    selected_deal_types = st.multiselect("Deal Type", all_deal_types, default=all_deal_types)

    all_pipelines = sorted(df["PIPELINE"].dropna().unique())
    selected_pipelines = st.multiselect("Pipeline", all_pipelines, default=all_pipelines)

    all_geos = sorted(df["GEO"].dropna().unique())
    selected_geos = st.multiselect("Geo / Division", all_geos, default=all_geos)

    current_year = pd.Timestamp.now().year
    year_options = sorted(df["DEAL_CLOSED_DATE"].dt.year.dropna().unique().astype(int), reverse=True)
    selected_year = st.selectbox("Fiscal Year", year_options, index=0 if year_options else 0)

# Apply filters
mask = (
    df["DEAL_TEAM_NAME"].isin(selected_teams)
    & df["DEAL_TYPE"].isin(selected_deal_types)
    & df["PIPELINE"].isin(selected_pipelines)
    & df["GEO"].isin(selected_geos)
)
filtered = df[mask].copy()


def get_quarter(date):
    if pd.isna(date):
        return None
    m = date.month
    if m <= 3:
        return "Q1"
    elif m <= 6:
        return "Q2"
    elif m <= 9:
        return "Q3"
    return "Q4"


# --- 1. Revenue Trend Over Time ---
st.header("1. Revenue Trend Over Time")

closed_won = filtered[(filtered["IS_WON"] == True) & (filtered["DEAL_CLOSED_DATE"].dt.year == selected_year)].copy()
closed_won["QUARTER"] = closed_won["DEAL_CLOSED_DATE"].apply(get_quarter)
closed_won["MONTH"] = closed_won["DEAL_CLOSED_DATE"].dt.to_period("M").astype(str)

quarterly_rev = closed_won.groupby("QUARTER")["DEAL_NET_NEW_ARR"].sum().reindex(["Q1", "Q2", "Q3", "Q4"], fill_value=0)

target_values = TARGETS["Grand Total"]
target_df = pd.DataFrame({
    "Quarter": ["Q1", "Q2", "Q3", "Q4"],
    "Actual Revenue": [quarterly_rev.get("Q1", 0), quarterly_rev.get("Q2", 0), quarterly_rev.get("Q3", 0), quarterly_rev.get("Q4", 0)],
    "Target": [target_values["Q1"], target_values["Q2"], target_values["Q3"], target_values["Q4"]],
})
target_df["Cumulative Actual"] = target_df["Actual Revenue"].cumsum()
target_df["Cumulative Target"] = target_df["Target"].cumsum()

with st.container(horizontal=True):
    total_closed = quarterly_rev.sum()
    fy_target = target_values["FY"]
    pct_to_target = (total_closed / fy_target * 100) if fy_target else 0
    st.metric("FY Closed Revenue", f"${total_closed:,.0f}", border=True)
    st.metric("FY Target", f"${fy_target:,.0f}", border=True)
    st.metric("% to Target", f"{pct_to_target:.1f}%", border=True)

col1, col2 = st.columns(2)
with col1:
    with st.container(border=True):
        st.subheader("Quarterly Revenue vs Target")
        chart_data = target_df.set_index("Quarter")[["Actual Revenue", "Target"]]
        st.bar_chart(chart_data)

with col2:
    with st.container(border=True):
        st.subheader("Cumulative Progress to FY Target")
        cum_data = target_df.set_index("Quarter")[["Cumulative Actual", "Cumulative Target"]]
        st.line_chart(cum_data)

# --- 2. Sales Pipeline Funnel ---
st.header("2. Sales Pipeline Funnel")

open_deals = filtered[filtered["IS_CLOSED"] == False].copy()

col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.subheader("Pipeline Value by Stage ($)")
        stage_value = open_deals.groupby("DEAL_FUNNEL_STAGE")["DEAL_NET_NEW_ARR"].sum()
        stage_value = stage_value.reindex([s for s in FUNNEL_STAGE_ORDER if s in stage_value.index])
        if not stage_value.empty:
            funnel_df = pd.DataFrame({"Stage": stage_value.index, "ARR": stage_value.values})
            st.bar_chart(funnel_df, x="Stage", y="ARR", horizontal=True)
        else:
            st.info("No open deals match current filters.")

with col2:
    with st.container(border=True):
        st.subheader("Pipeline Deal Count by Stage")
        stage_count = open_deals.groupby("DEAL_FUNNEL_STAGE")["SK_DEAL"].count()
        stage_count = stage_count.reindex([s for s in FUNNEL_STAGE_ORDER if s in stage_count.index])
        if not stage_count.empty:
            count_df = pd.DataFrame({"Stage": stage_count.index, "Deals": stage_count.values})
            st.bar_chart(count_df, x="Stage", y="Deals", horizontal=True)
        else:
            st.info("No open deals match current filters.")

# --- 3. Rep Leaderboard ---
st.header("3. Rep Leaderboard (Closed Revenue This Quarter)")

current_quarter = get_quarter(pd.Timestamp.now())
closed_this_q = closed_won[closed_won["QUARTER"] == current_quarter]

with st.container(border=True):
    rep_revenue = (
        closed_this_q.groupby("REP_NAME")["DEAL_NET_NEW_ARR"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    )
    rep_revenue.columns = ["Rep", "Closed ARR"]
    if not rep_revenue.empty:
        st.bar_chart(rep_revenue, x="Rep", y="Closed ARR", horizontal=True)
    else:
        st.info(f"No closed-won deals in {current_quarter} {selected_year} for current filters.")

# --- 4. Win/Loss Ratio & Deal Velocity ---
st.header("4. Win/Loss Ratio & Deal Velocity")

year_deals = filtered[
    (filtered["IS_CLOSED"] == True) & (filtered["DEAL_CLOSED_DATE"].dt.year == selected_year)
].copy()
year_deals["QUARTER"] = year_deals["DEAL_CLOSED_DATE"].apply(get_quarter)

qualified_deals = year_deals[year_deals["QUALIFIED_DATE"].notna()].copy()
qualified_deals["DAYS_TO_CLOSE"] = (qualified_deals["DEAL_CLOSED_DATE"] - qualified_deals["QUALIFIED_DATE"]).dt.days

col1, col2 = st.columns(2)

with col1:
    with st.container(border=True):
        st.subheader("Win Rate by Quarter")
        win_loss = year_deals.groupby("QUARTER").agg(
            total=("SK_DEAL", "count"),
            wins=("IS_WON", "sum"),
        )
        win_loss["Win Rate %"] = (win_loss["wins"] / win_loss["total"] * 100).round(1)
        win_loss = win_loss.reindex(["Q1", "Q2", "Q3", "Q4"])
        if not win_loss.empty:
            st.line_chart(win_loss[["Win Rate %"]])
        else:
            st.info("No closed deals in selected year.")

with col2:
    with st.container(border=True):
        st.subheader("Avg Days to Close by Quarter")
        velocity = qualified_deals.groupby("QUARTER")["DAYS_TO_CLOSE"].mean().round(0)
        velocity = velocity.reindex(["Q1", "Q2", "Q3", "Q4"])
        if not velocity.empty:
            vel_df = pd.DataFrame({"Quarter": velocity.index, "Avg Days": velocity.values})
            st.bar_chart(vel_df, x="Quarter", y="Avg Days")
        else:
            st.info("No velocity data available.")

# --- 5. Average Deal Size Trend ---
st.header("5. Average Deal Size Trend")

with st.container(border=True):
    closed_all_years = filtered[(filtered["IS_WON"] == True) & filtered["DEAL_CLOSED_DATE"].notna()].copy()
    closed_all_years["YEAR_QUARTER"] = (
        closed_all_years["DEAL_CLOSED_DATE"].dt.year.astype(str)
        + "-"
        + closed_all_years["DEAL_CLOSED_DATE"].apply(get_quarter)
    )
    avg_deal = closed_all_years.groupby("YEAR_QUARTER")["DEAL_NET_NEW_ARR"].mean().reset_index()
    avg_deal.columns = ["Quarter", "Avg Deal Size"]
    avg_deal = avg_deal.sort_values("Quarter")
    if not avg_deal.empty:
        st.line_chart(avg_deal, x="Quarter", y="Avg Deal Size")
    else:
        st.info("No data for deal size trend.")

# --- Summary Table ---
st.header("Detailed Data")
with st.expander("Show filtered deals"):
    display_cols = [
        "DEAL_NAME", "DEAL_TYPE", "PIPELINE", "DEAL_TEAM_NAME", "GEO",
        "REP_NAME", "DEAL_FUNNEL_STAGE", "DEAL_STAGE", "DEAL_NET_NEW_ARR",
        "DEAL_CLOSED_DATE", "IS_WON",
    ]
    st.dataframe(filtered[display_cols], hide_index=True, use_container_width=True)
