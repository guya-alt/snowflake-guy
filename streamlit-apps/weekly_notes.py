# Weekly Team Review Dashboard
# Co-authored with CoCo
import streamlit as st
import altair as alt
import pandas as pd
import os
from datetime import date

st.set_page_config(page_title="Weekly Notes", layout="wide")

conn = st.connection("snowflake")


@st.cache_data(ttl=3600, show_spinner=False)
def _get_database():
    return conn.query("SELECT CURRENT_DATABASE()").iat[0, 0]


DATABASE = os.getenv("TARGET_DATABASE") or _get_database()
DWH = f"{DATABASE}.DWH"


@st.cache_data(ttl=60, show_spinner=False)
def get_snowflake_today():
    return conn.query("SELECT CURRENT_DATE() AS today").iloc[0]["TODAY"]


_today = get_snowflake_today()
SNAPSHOT_DATE_SQL = f"'{_today.strftime('%Y-%m-%d') if hasattr(_today, 'strftime') else str(_today)}'::DATE"
WEEK_CUTOFF_SQL = f"DATE_TRUNC('WEEK', {SNAPSHOT_DATE_SQL})"

# --- Quota Targets (per rep, per quarter) ---
# Format: {rep_display_name: {Q1: $, Q2: $, Q3: $, Q4: $}}
QUARTERLY_QUOTAS_BY_REP = {
    "Tom Skarzynski": {"Q1": 375_000, "Q2": 375_000, "Q3": 375_000, "Q4": 375_000},
    "Jeff Graham": {"Q1": 375_000, "Q2": 375_000, "Q3": 375_000, "Q4": 375_000},
    "Tali Cohen": {"Q1": 375_000, "Q2": 375_000, "Q3": 375_000, "Q4": 375_000},
    "Travis Dadoly": {"Q1": 375_000, "Q2": 375_000, "Q3": 375_000, "Q4": 375_000},
    "Evan Smith": {"Q1": 0, "Q2": 190_000, "Q3": 370_000, "Q4": 375_000},
    "Jenny Antic Lucas": {"Q1": 0, "Q2": 195_000, "Q3": 365_000, "Q4": 375_000},
    "Rick Walker": {"Q1": 0, "Q2": 195_000, "Q3": 365_000, "Q4": 375_000},
    "Ignacio De Loera": {"Q1": 0, "Q2": 250_000, "Q3": 375_000, "Q4": 375_000},
    "John Romano": {"Q1": 250_000, "Q2": 250_000, "Q3": 250_000, "Q4": 250_000},
    "Daniel Alper": {"Q1": 250_000, "Q2": 250_000, "Q3": 250_000, "Q4": 250_000},
    "Jill Countey": {"Q1": 250_000, "Q2": 250_000, "Q3": 250_000, "Q4": 250_000},
    "EJ Rauseo": {"Q1": 250_000, "Q2": 250_000, "Q3": 250_000, "Q4": 250_000},
    "Benjamin Duckworth": {"Q1": 325_000, "Q2": 325_000, "Q3": 325_000, "Q4": 325_000},
    "James Pritchard": {"Q1": 325_000, "Q2": 325_000, "Q3": 325_000, "Q4": 325_000},
    "John Barnes": {"Q1": 0, "Q2": 155_278, "Q3": 240_255, "Q4": 321_505},
    "Jamie Summers": {"Q1": 0, "Q2": 52_361, "Q3": 188_681, "Q4": 269_960},
    "Sharon Peretz": {"Q1": 250_000, "Q2": 250_000, "Q3": 250_000, "Q4": 250_000},
    "Matt Bilsland": {"Q1": 0, "Q2": 109_722, "Q3": 235_215, "Q4": 250_000},
    "James Butcher": {"Q1": 0, "Q2": 40_278, "Q3": 165_278, "Q4": 250_000},
    "Scott Dunion": {"Q1": 375_000, "Q2": 375_000, "Q3": 375_000, "Q4": 375_000},
}


def get_rep_quota(rep_name, period_label):
    """Get quota for a rep based on period selection (YTD or single quarter)."""
    rep_quotas = QUARTERLY_QUOTAS_BY_REP.get(rep_name)
    if not rep_quotas:
        return 250_000  # fallback for unknown reps
    if period_label.startswith("YTD"):
        return sum(rep_quotas.values())
    else:
        q_num = period_label.split()[0]  # e.g. "Q3"
        return rep_quotas.get(q_num, 250_000)


def get_team_quota(period_label):
    """Sum all rep quotas for the period."""
    return sum(get_rep_quota(rep, period_label) for rep in QUARTERLY_QUOTAS_BY_REP)

# --- Title ---
st.title("Weekly Notes")
st.caption("Manager-level view: team pacing, rep performance, pipeline health, and action items.")
st.markdown(
    f"_Updated: {_today.strftime('%B %d, %Y') if hasattr(_today, 'strftime') else str(_today)}_ · "
    f"Built by [Guy Amitai](https://getport.slack.com/team/U0B4FPPESSD)"
)
st.divider()

# --- Sidebar: Period Picker & Filters ---
st.sidebar.header("Settings")

today_ts = pd.Timestamp(_today)

# Build period options: YTD + recent quarters
period_options = [f"YTD {today_ts.year}"]
for i in range(6):
    d = today_ts - pd.Timedelta(days=i * 91)
    ql = f"Q{d.quarter} {d.year}"
    if ql not in period_options:
        period_options.append(ql)

selected_period = st.sidebar.selectbox("Period", period_options, index=0)

# Parse selected period into date range + quota multiplier
if selected_period.startswith("YTD"):
    _period_year = int(selected_period.split()[1])
    _period_start = pd.Timestamp(_period_year, 1, 1)
    _period_end = pd.Timestamp(_period_year, 12, 31) + pd.Timedelta(days=1)
    # Quota = quarterly quota x quarters elapsed (including current partial quarter)
    _quarters_in_period = today_ts.quarter
    _quota_multiplier = _quarters_in_period
    _period_label = selected_period
else:
    _sq_parts = selected_period.split()
    _sq_q = int(_sq_parts[0][1])
    _sq_y = int(_sq_parts[1])
    _period_start = pd.Timestamp(_sq_y, (_sq_q - 1) * 3 + 1, 1)
    _period_end = _period_start + pd.offsets.QuarterEnd(0) + pd.Timedelta(days=1)
    _quota_multiplier = 1
    _period_label = selected_period

Q_START_SQL = f"'{_period_start.strftime('%Y-%m-%d')}'::DATE"
Q_END_SQL = f"'{_period_end.strftime('%Y-%m-%d')}'::DATE"

# Compute quotas for selected period
TEAM_PERIOD_QUOTA = get_team_quota(_period_label)

# Filter options — scoped to recent relevant deals
@st.cache_data(ttl=3600, show_spinner=False)
def load_filter_options():
    recent = f"deal_created_date >= DATEADD('MONTH', -13, {SNAPSHOT_DATE_SQL})"
    base = f"pipeline = 'Classic' AND deal_type = 'newbusiness' AND {recent}"
    teams = conn.query(f"SELECT DISTINCT deal_team_name FROM {DWH}.FACT_DEALS WHERE deal_team_name IS NOT NULL AND {base}")
    owners = conn.query(f"""
        SELECT DISTINCT de.display_name
        FROM {DWH}.FACT_DEALS fd
        JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
        WHERE fd.{base}
    """)
    pipelines = conn.query(f"SELECT DISTINCT pipeline FROM {DWH}.FACT_DEALS WHERE pipeline IS NOT NULL AND {recent}")
    deal_types = conn.query(f"SELECT DISTINCT deal_type FROM {DWH}.FACT_DEALS WHERE deal_type IS NOT NULL AND {recent}")
    stages = conn.query(f"SELECT DISTINCT deal_stage FROM {DWH}.FACT_DEALS WHERE deal_stage IS NOT NULL AND {recent}")
    return (
        sorted(teams.iloc[:, 0].dropna().tolist()),
        sorted(owners.iloc[:, 0].dropna().tolist()),
        sorted(pipelines.iloc[:, 0].dropna().tolist()),
        sorted(deal_types.iloc[:, 0].dropna().tolist()),
        sorted(stages.iloc[:, 0].dropna().tolist()),
    )


teams_all, owners_all, pipelines_all, deal_types_all, stages_all = load_filter_options()

# Curated team list for filters
TEAM_OPTIONS = ["US Ent", "US MM", "EMEA Ent", "EMEA MM", "APJ", "LATAM"]

with st.sidebar.form("filters_form"):
    f_pipelines = st.multiselect("Pipeline", pipelines_all, default=["Classic"] if "Classic" in pipelines_all else [])
    f_deal_types = st.multiselect("Deal Type", deal_types_all, default=["newbusiness"] if "newbusiness" in deal_types_all else [])
    f_stages = st.multiselect("Deal Stage", stages_all, default=[])
    f_teams = st.multiselect("Team", TEAM_OPTIONS, default=[])
    f_owners = st.multiselect("Rep", owners_all, default=[])
    load_data = st.form_submit_button("Load Data", type="primary", use_container_width=True)

if load_data:
    st.session_state["review_loaded"] = True

if "review_loaded" not in st.session_state:
    st.info("Configure filters and click **Load Data** to query.")
    st.stop()


# --- Helper functions ---
@st.cache_data(ttl=900, show_spinner="Querying Snowflake...")
def run_query(sql):
    return conn.query(sql)


def run_llm(sql):
    """Run LLM queries without caching (on-demand, non-deterministic)."""
    return conn.query(sql)


def fmt_arr(value):
    if value is None:
        return "$0"
    value = float(value)
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.1f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.0f}K"
    return f"{sign}${abs_val:.0f}"


def fmt_arr_md(value):
    """Markdown-safe ARR format (escapes $ to avoid LaTeX rendering)."""
    return fmt_arr(value).replace("$", "\\$")


def build_filter_clauses():
    clauses = []
    if f_pipelines:
        vals = ",".join(f"'{v}'" for v in f_pipelines)
        clauses.append(f"fd.pipeline IN ({vals})")
    if f_deal_types:
        vals = ",".join(f"'{v}'" for v in f_deal_types)
        clauses.append(f"fd.deal_type IN ({vals})")
    if f_stages:
        vals = ",".join(f"'{v}'" for v in f_stages)
        clauses.append(f"fd.deal_stage IN ({vals})")
    if f_teams:
        vals = ",".join(f"'{v}'" for v in f_teams)
        clauses.append(f"fd.deal_team_name IN ({vals})")
    if f_owners:
        vals = ",".join(f"'{v}'" for v in f_owners)
        clauses.append(f"de.display_name IN ({vals})")
    return (" AND " + " AND ".join(clauses)) if clauses else ""


def filter_caption():
    parts = []
    if f_pipelines:
        parts.append(f"Pipeline: {', '.join(f_pipelines)}")
    if f_deal_types:
        parts.append(f"Type: {', '.join(f_deal_types)}")
    if f_stages:
        parts.append(f"Stage: {', '.join(f_stages)}")
    if f_teams:
        parts.append(f"Team: {', '.join(f_teams)}")
    if f_owners:
        parts.append(f"Rep: {', '.join(f_owners)}")
    parts.append(f"Period: {_period_label}")
    return " · ".join(parts)


# AE list — derived from quota table; anyone with a quota is an AE
AE_LIST = list(QUARTERLY_QUOTAS_BY_REP.keys())
AE_LIST_SQL = ", ".join(f"'{name}'" for name in AE_LIST)

# Excluded reps — hardcoded non-AEs or departed reps to always hide
EXCLUDED_REPS = ["Chris Newsome", "Chris Sweeney", "Travis Dadoly"]
EXCLUDED_REPS_SQL = ", ".join(f"'{name}'" for name in EXCLUDED_REPS)

# Active reps = AEs from quota table, minus excluded, minus archived
ACTIVE_REPS_SQL = f"""
    SELECT DISTINCT de.display_name
    FROM {DWH}.DIM_EMPLOYEE de
    WHERE de.display_name IN ({AE_LIST_SQL})
      AND de.display_name NOT IN ({EXCLUDED_REPS_SQL})
      AND de.hs_archived = FALSE
"""


# =============================================================================
# SECTION 1: TOP-LINE KPI CARDS + PACING BAR
# =============================================================================
st.header("Team Pacing")
st.caption("All teams combined. Only affected by Period filter.")

kpi_sql = f"""
SELECT
    COALESCE(SUM(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0) AS closed_won_arr,
    COALESCE(SUM(CASE WHEN fd.is_closed = FALSE AND fd.qualified_date IS NOT NULL AND fd.deal_net_new_arr > 0 THEN fd.deal_net_new_arr END), 0) AS open_pipeline_arr,
    COUNT(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN 1 END) AS won_deals,
    COUNT(CASE WHEN fd.is_closed = FALSE AND fd.qualified_date IS NOT NULL AND fd.deal_net_new_arr > 0 THEN 1 END) AS open_deal_count,
    ROUND(
        COALESCE(SUM(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0)::FLOAT
        / NULLIF(SUM(CASE WHEN fd.is_closed = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0) * 100
    , 1) AS win_rate_pct
FROM {DWH}.FACT_DEALS fd
LEFT JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
WHERE 1=1
  AND (
    (fd.is_closed = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL})
    OR (fd.is_closed = FALSE AND fd.qualified_date IS NOT NULL AND fd.deal_net_new_arr > 0)
  )
  AND fd.deal_team_name IN ('US Ent', 'US MM', 'EMEA Ent', 'EMEA MM', 'APJ', 'LATAM')
"""

# Separate query for CVR and ASP (scoped to created deals in period)
cvr_sql = f"""
SELECT
    ROUND(AVG(CASE WHEN fd.qualified_date IS NOT NULL AND fd.deal_net_new_arr > 0 THEN fd.deal_net_new_arr END), 0) AS asp_qualified,
    ROUND(COUNT(CASE WHEN fd.qualified_date IS NOT NULL THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) * 100, 1) AS cvr_created_to_qualified
FROM {DWH}.FACT_DEALS fd
LEFT JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
WHERE fd.deal_created_date >= {Q_START_SQL}
  AND fd.deal_created_date < {Q_END_SQL}
  AND fd.deal_team_name IN ('US Ent', 'US MM', 'EMEA Ent', 'EMEA MM', 'APJ', 'LATAM')
"""

df_kpi = run_query(kpi_sql)
df_cvr = run_query(cvr_sql)

if not df_kpi.empty:
    row = df_kpi.iloc[0]
    closed_won = float(row["CLOSED_WON_ARR"])
    open_pipe = float(row["OPEN_PIPELINE_ARR"])
    win_rate = float(row["WIN_RATE_PCT"] or 0)
    won_deals = int(row["WON_DEALS"])
    open_deal_count = int(row["OPEN_DEAL_COUNT"])

    cvr_row = df_cvr.iloc[0] if not df_cvr.empty else {}
    asp = float(cvr_row.get("ASP_QUALIFIED", 0) or 0)
    cvr_created_qual = float(cvr_row.get("CVR_CREATED_TO_QUALIFIED", 0) or 0)

    attainment_pct = round(closed_won / TEAM_PERIOD_QUOTA * 100, 1) if TEAM_PERIOD_QUOTA > 0 else 0
    gap_to_goal = max(0, TEAM_PERIOD_QUOTA - closed_won)
    pipe_coverage = round(open_pipe / gap_to_goal, 1) if gap_to_goal > 0 else float("inf")

    # Reverse-engineer what's needed to close the gap
    # Qualified ARR needed = gap / win_rate (how much qualified pipe we need)
    qualified_arr_needed = gap_to_goal / (win_rate / 100) if win_rate > 0 else gap_to_goal
    # Created deals needed = qualified_arr_needed / ASP / (cvr_created_qual / 100)
    created_deals_needed = int(qualified_arr_needed / asp / (cvr_created_qual / 100)) if asp > 0 and cvr_created_qual > 0 else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Attainment", f"{attainment_pct}%", delta=f"{won_deals} deals won")
    k2.metric("Gap to Goal", fmt_arr(gap_to_goal))
    k3.metric("Open Pipeline", fmt_arr(open_pipe))
    k4.metric("Pipe Coverage", f"{pipe_coverage:.1f}x" if pipe_coverage != float("inf") else "Goal met")
    k5.metric("Win Rate", f"{win_rate}%")

    # Second row: what's needed to close the gap
    k6, k7, k8, k9, k10 = st.columns(5)
    k6.metric("Open Deals", f"{open_deal_count:,}")
    k7.metric("Qualified ARR Needed", fmt_arr(qualified_arr_needed))
    k8.metric("ASP (Qualified)", fmt_arr(asp))
    k9.metric("CVR (Created → Qualified)", f"{cvr_created_qual}%")
    k10.metric("Created Deals Needed", f"{created_deals_needed:,}")

    # Progress bar — single stacked bar showing closed vs remaining
    bar_data = pd.DataFrame({
        "Category": ["Closed Won", "Gap Remaining"],
        "Amount": [closed_won, gap_to_goal],
        "Label": [fmt_arr(closed_won), fmt_arr(gap_to_goal)],
        "LabelColor": ["#2a2a3e", "#00CC96"],
    })
    bar_base = alt.Chart(bar_data).encode(
        x=alt.X("Amount:Q", stack="zero", title="", axis=None),
        color=alt.Color(
            "Category:N",
            scale=alt.Scale(domain=["Closed Won", "Gap Remaining"], range=["#00CC96", "#3a3a52"]),
            legend=alt.Legend(orient="bottom", title=None),
        ),
        order=alt.Order("order:Q"),
        tooltip=[alt.Tooltip("Category:N"), alt.Tooltip("Amount:Q", format="$,.0f")],
    ).transform_calculate(order="datum.Category === 'Closed Won' ? 0 : 1")

    bar_marks = bar_base.mark_bar(cornerRadius=4, height=36)
    bar_labels = (
        alt.Chart(bar_data)
        .mark_text(fontSize=13, fontWeight="bold")
        .encode(
            x=alt.X("mid:Q", axis=None),
            text="Label:N",
            color=alt.Color("LabelColor:N", scale=None),
        )
        .transform_window(
            cumulative="sum(Amount)",
            frame=[None, 0],
        )
        .transform_calculate(
            mid="datum.cumulative - datum.Amount / 2"
        )
    )

    st.altair_chart(
        (bar_marks + bar_labels).properties(height=56),
        use_container_width=True,
    )
    st.caption(f"Target: {fmt_arr(TEAM_PERIOD_QUOTA)} | Period: {_period_label}")

st.markdown("---")

# =============================================================================
# SECTION 2: VISUAL RISK & PERFORMANCE CHARTS
# =============================================================================
st.header("Risk & Performance")

chart_col1, chart_col2 = st.columns(2)

# --- Chart 2: Scatter (Win Rate vs ASP per Rep) ---
with chart_col1:
    st.subheader("Win Rate vs. ASP")
    st.caption("Circle = rep, Diamond = team average. Reps with <3 closed deals excluded.")

    scatter_sql = f"""
    SELECT
        de.display_name AS rep,
        fd.deal_team_name AS team,
        COUNT(CASE WHEN fd.is_won = TRUE THEN 1 END) AS won,
        COUNT(*) AS total_closed,
        ROUND(COUNT(CASE WHEN fd.is_won = TRUE THEN 1 END)::FLOAT / NULLIF(COUNT(*), 0) * 100, 1) AS win_rate_pct,
        ROUND(AVG(CASE WHEN fd.is_won = TRUE THEN fd.deal_net_new_arr END), 0) AS avg_deal_size
    FROM {DWH}.FACT_DEALS fd
    JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
    WHERE fd.is_closed = TRUE
      AND fd.deal_net_new_arr > 0
      AND fd.deal_closed_date >= DATEADD('MONTH', -12, {SNAPSHOT_DATE_SQL})
      AND fd.deal_closed_date < {WEEK_CUTOFF_SQL}
      AND de.hs_archived = FALSE
      AND de.display_name IN ({ACTIVE_REPS_SQL})
      AND de.display_name NOT IN ({EXCLUDED_REPS_SQL})
      AND fd.deal_team_name IN ('US Ent', 'US MM', 'EMEA Ent', 'EMEA MM', 'APJ', 'LATAM')
      {build_filter_clauses()}
    GROUP BY 1, 2
    HAVING COUNT(*) >= 3
    """

    df_scatter = run_query(scatter_sql)

    if not df_scatter.empty:
        for col in ["WIN_RATE_PCT", "AVG_DEAL_SIZE"]:
            df_scatter[col] = pd.to_numeric(df_scatter[col], errors="coerce").fillna(0)

        # Team averages
        team_avgs = df_scatter.groupby("TEAM", as_index=False).agg(
            WIN_RATE_PCT=("WIN_RATE_PCT", "mean"),
            AVG_DEAL_SIZE=("AVG_DEAL_SIZE", "mean"),
        ).round(1)
        team_avgs["REP"] = team_avgs["TEAM"].str.split().str[0] + " Avg"

        # Rep circles
        scatter = (
            alt.Chart(df_scatter)
            .mark_circle(size=140)
            .encode(
                x=alt.X("WIN_RATE_PCT:Q", title="Win Rate (%)", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(labelFontSize=12, titleFontSize=13)),
                y=alt.Y("AVG_DEAL_SIZE:Q", title="ASP ($)", axis=alt.Axis(format="$~s", labelFontSize=12, titleFontSize=13)),
                color=alt.Color("TEAM:N", title="Team"),
                tooltip=[
                    alt.Tooltip("REP:N", title="Rep"),
                    alt.Tooltip("TEAM:N", title="Team"),
                    alt.Tooltip("WIN_RATE_PCT:Q", title="Win Rate %", format=".1f"),
                    alt.Tooltip("AVG_DEAL_SIZE:Q", title="Avg Deal $", format="$,.0f"),
                    alt.Tooltip("WON:Q", title="Won Deals"),
                    alt.Tooltip("TOTAL_CLOSED:Q", title="Total Closed"),
                ],
            )
            .properties(height=350)
        )
        # Team avg diamonds (larger, no extra legend)
        diamonds = (
            alt.Chart(team_avgs)
            .mark_point(shape="diamond", size=300, filled=True, opacity=0.9)
            .encode(
                x="WIN_RATE_PCT:Q",
                y="AVG_DEAL_SIZE:Q",
                color=alt.Color("TEAM:N", legend=None),
                tooltip=[
                    alt.Tooltip("REP:N", title="Label"),
                    alt.Tooltip("TEAM:N", title="Team"),
                    alt.Tooltip("WIN_RATE_PCT:Q", title="Avg Win Rate %", format=".1f"),
                    alt.Tooltip("AVG_DEAL_SIZE:Q", title="Avg Deal $", format="$,.0f"),
                ],
            )
        )
        diamond_labels = (
            alt.Chart(team_avgs)
            .mark_text(dy=-14, fontSize=11, fontStyle="italic", fontWeight="bold")
            .encode(
                x="WIN_RATE_PCT:Q",
                y="AVG_DEAL_SIZE:Q",
                text="REP:N",
                color=alt.Color("TEAM:N", legend=None),
            )
        )
        # Rep name labels — removed to avoid overlapping
        st.altair_chart(
            (scatter + diamonds + diamond_labels).configure_legend(orient="bottom"),
            use_container_width=True,
        )
        st.caption(filter_caption())
        with st.expander("Show raw data"):
            scatter_detail_sql = f"""
            SELECT
                de.display_name AS rep,
                fd.deal_team_name AS team,
                fd.deal_name,
                dc.company_name,
                fd.deal_net_new_arr,
                fd.deal_closed_date::DATE AS close_date,
                fd.deal_stage,
                fd.is_won
            FROM {DWH}.FACT_DEALS fd
            JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
            LEFT JOIN {DWH}.DIM_COMPANY dc ON fd.sk_company = dc.sk_company
            WHERE fd.is_closed = TRUE
              AND fd.deal_net_new_arr > 0
              AND fd.deal_closed_date >= DATEADD('MONTH', -12, {SNAPSHOT_DATE_SQL})
              AND fd.deal_closed_date < {WEEK_CUTOFF_SQL}
              {build_filter_clauses()}
            ORDER BY fd.deal_closed_date DESC
            """
            _df_scatter_raw = run_query(scatter_detail_sql)
            if not _df_scatter_raw.empty:
                _sr_col1, _sr_col2 = st.columns(2)
                with _sr_col1:
                    _sr_reps = ["All"] + sorted(_df_scatter_raw["REP"].dropna().unique().tolist())
                    _sr_sel_rep = st.selectbox("Rep", _sr_reps, key="scatter_raw_rep")
                with _sr_col2:
                    _sr_teams = ["All"] + sorted(_df_scatter_raw["TEAM"].dropna().unique().tolist())
                    _sr_sel_team = st.selectbox("Team", _sr_teams, key="scatter_raw_team")
                if _sr_sel_rep != "All":
                    _df_scatter_raw = _df_scatter_raw[_df_scatter_raw["REP"] == _sr_sel_rep]
                if _sr_sel_team != "All":
                    _df_scatter_raw = _df_scatter_raw[_df_scatter_raw["TEAM"] == _sr_sel_team]
                st.dataframe(_df_scatter_raw, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found.")
    else:
        st.info("Not enough closed deals to render scatter plot.")

# --- Chart 3: Pipeline by Rep ---
with chart_col2:
    st.subheader("Open Pipeline by Rep")
    pipe_breakdown = st.radio("", ["Age", "Deal Stage"], horizontal=True, key="pipe_breakdown", label_visibility="collapsed")
    st.caption("Open pipeline $ per rep, colored by age bucket or current deal stage.")

    if pipe_breakdown == "Age":
        _color_expr = f"""CASE
            WHEN DATEDIFF('MONTH', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) <= 3 THEN '0-3 months'
            WHEN DATEDIFF('MONTH', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) <= 6 THEN '3-6 months'
            WHEN DATEDIFF('MONTH', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) <= 12 THEN '6-12 months'
            ELSE '>12 months'
        END"""
        _color_alias = "color_dim"
        _color_domain = ["0-3 months", "3-6 months", "6-12 months", ">12 months"]
        _color_range = ["#00CC96", "#FFA15A", "#EF553B", "#AB63FA"]
        _color_title = "Age"
    else:
        _color_expr = "fd.deal_stage"
        _color_alias = "color_dim"
        _color_domain = None
        _color_range = None
        _color_title = "Deal Stage"

    _stage_sort_col = ", MIN(fd.stage_sort_order) AS stage_sort" if pipe_breakdown == "Deal Stage" else ""

    aging_sql = f"""
    SELECT
        de.display_name AS rep,
        {_color_expr} AS {_color_alias},
        SUM(fd.deal_net_new_arr) AS bucket_arr,
        COUNT(*) AS deal_count
        {_stage_sort_col}
    FROM {DWH}.FACT_DEALS fd
    JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
    WHERE fd.is_closed = FALSE
      AND fd.deal_net_new_arr > 0
      AND de.display_name IN ({ACTIVE_REPS_SQL})
      {build_filter_clauses()}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """

    df_aging = run_query(aging_sql)

    if not df_aging.empty:
        df_aging["BUCKET_ARR"] = pd.to_numeric(df_aging["BUCKET_ARR"], errors="coerce").fillna(0)

        if _color_domain:
            color_enc = alt.Color(
                "COLOR_DIM:N",
                title=_color_title,
                scale=alt.Scale(domain=_color_domain, range=_color_range),
                sort=_color_domain,
            )
            order_enc = alt.Order("bucket_sort:Q")
            transform = lambda c: c.transform_calculate(
                bucket_sort=f"indexof({_color_domain}, datum.COLOR_DIM)"
            )
        else:
            # Sort by stage_sort_order for proper funnel ordering
            _stage_order = df_aging.sort_values("STAGE_SORT")["COLOR_DIM"].unique().tolist() if "STAGE_SORT" in df_aging.columns else None
            color_enc = alt.Color("COLOR_DIM:N", title=_color_title, sort=_stage_order)
            order_enc = alt.Order("STAGE_SORT:Q") if "STAGE_SORT" in df_aging.columns else alt.Order("COLOR_DIM:N")
            transform = lambda c: c

        aging_chart = transform(
            alt.Chart(df_aging)
            .mark_bar()
            .encode(
                y=alt.Y("REP:N", title="", sort=alt.EncodingSortField(field="BUCKET_ARR", op="sum", order="descending")),
                x=alt.X("BUCKET_ARR:Q", title="Open Pipeline ($)", axis=alt.Axis(format="$~s"), stack="zero"),
                color=color_enc,
                order=order_enc,
                tooltip=[
                    alt.Tooltip("REP:N", title="Rep"),
                    alt.Tooltip("COLOR_DIM:N", title=_color_title),
                    alt.Tooltip("BUCKET_ARR:Q", title="ARR ($)", format="$,.0f"),
                    alt.Tooltip("DEAL_COUNT:Q", title="# Deals"),
                ],
            )
        ).properties(height=350)

        st.altair_chart(aging_chart.configure_legend(orient="bottom"), use_container_width=True)
        st.caption(filter_caption())
        with st.expander("Show raw data"):
            aging_detail_sql = f"""
            SELECT
                de.display_name AS rep,
                fd.deal_name,
                dc.company_name,
                fd.deal_net_new_arr,
                fd.deal_created_date::DATE AS create_date,
                fd.deal_stage,
                fd.forecast_category,
                DATEDIFF('MONTH', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) AS months_open
            FROM {DWH}.FACT_DEALS fd
            JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
            LEFT JOIN {DWH}.DIM_COMPANY dc ON fd.sk_company = dc.sk_company
            WHERE fd.is_closed = FALSE
              AND fd.deal_net_new_arr > 0
              {build_filter_clauses()}
            ORDER BY months_open DESC
            """
            _df_aging_raw = run_query(aging_detail_sql)
            if not _df_aging_raw.empty:
                _ar_col1, _ar_col2 = st.columns(2)
                with _ar_col1:
                    _ar_reps = ["All"] + sorted(_df_aging_raw["REP"].dropna().unique().tolist())
                    _ar_sel_rep = st.selectbox("Rep", _ar_reps, key="aging_raw_rep")
                with _ar_col2:
                    _ar_stages = ["All"] + sorted(_df_aging_raw["DEAL_STAGE"].dropna().unique().tolist())
                    _ar_sel_stage = st.selectbox("Stage", _ar_stages, key="aging_raw_stage")
                if _ar_sel_rep != "All":
                    _df_aging_raw = _df_aging_raw[_df_aging_raw["REP"] == _ar_sel_rep]
                if _ar_sel_stage != "All":
                    _df_aging_raw = _df_aging_raw[_df_aging_raw["DEAL_STAGE"] == _ar_sel_stage]
                st.dataframe(_df_aging_raw, use_container_width=True, hide_index=True)
            else:
                st.info("No deals found.")
    else:
        st.info("No open pipeline deals found.")

st.markdown("---")

# =============================================================================
# SECTION 2.5: WEEKLY ACTIVITY
# =============================================================================
st.header("Weekly Activity")

st.subheader("Pipeline Movement")
st.caption("Deals that advanced, slipped, or were created/lost this week.")
st.info("Coming soon")

st.markdown("---")

# =============================================================================
# SECTION 3: REP COMPARISON LEADERBOARD
# =============================================================================
st.header("Rep Leaderboard")
st.caption(f"Performance comparison for {_period_label}. Sorted by Closed Won descending.")
st.caption("**Stuck Deals** = open deals older than the team's average close time (Enterprise: 250 days, Mid-Market: 100 days, Other: 150 days).")

leaderboard_sql = f"""
SELECT
    de.display_name AS rep,
    fd.deal_team_name AS team,
    COALESCE(SUM(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0) AS closed_won_arr,
    COALESCE(SUM(CASE WHEN fd.is_won = FALSE AND fd.is_closed = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0) AS closed_lost_arr,
    ROUND(
        COUNT(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN 1 END)::FLOAT
        / NULLIF(COUNT(CASE WHEN fd.is_closed = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN 1 END), 0) * 100
    , 1) AS win_rate_pct,
    ROUND(AVG(CASE WHEN fd.is_won = TRUE AND fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL} THEN fd.deal_net_new_arr END), 0) AS avg_deal_size,
    COALESCE(SUM(CASE WHEN fd.is_closed = FALSE AND (
        (fd.deal_team_name ILIKE '%Ent%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 250)
        OR (fd.deal_team_name ILIKE '%MM%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 100)
        OR (fd.deal_team_name NOT ILIKE '%Ent%' AND fd.deal_team_name NOT ILIKE '%MM%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 150)
    ) THEN fd.deal_net_new_arr END), 0) AS stuck_pipeline_arr,
    COUNT(CASE WHEN fd.is_closed = FALSE AND (
        (fd.deal_team_name ILIKE '%Ent%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 250)
        OR (fd.deal_team_name ILIKE '%MM%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 100)
        OR (fd.deal_team_name NOT ILIKE '%Ent%' AND fd.deal_team_name NOT ILIKE '%MM%' AND DATEDIFF('DAY', fd.deal_created_date, {SNAPSHOT_DATE_SQL}) > 150)
    ) THEN 1 END) AS stuck_deal_count
FROM {DWH}.FACT_DEALS fd
JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
WHERE fd.deal_net_new_arr > 0
  AND de.display_name IN ({ACTIVE_REPS_SQL})
  AND (
    (fd.deal_closed_date >= {Q_START_SQL} AND fd.deal_closed_date < {Q_END_SQL})
    OR (fd.is_closed = FALSE AND fd.qualified_date IS NOT NULL)
  )
  {build_filter_clauses()}
GROUP BY 1, 2
ORDER BY closed_won_arr DESC
"""

df_board = run_query(leaderboard_sql)

if not df_board.empty:
    # Cast Decimal columns to float for arithmetic
    for col in ["CLOSED_WON_ARR", "CLOSED_LOST_ARR", "WIN_RATE_PCT", "AVG_DEAL_SIZE", "STUCK_PIPELINE_ARR"]:
        if col in df_board.columns:
            df_board[col] = pd.to_numeric(df_board[col], errors="coerce").fillna(0)

    # Add attainment % from hardcoded quotas
    df_board["QUOTA"] = df_board["REP"].apply(lambda r: get_rep_quota(r, _period_label))
    df_board["ATTAINMENT_PCT"] = (df_board["CLOSED_WON_ARR"] / df_board["QUOTA"] * 100).round(1)

    display_df = df_board[["REP", "QUOTA", "ATTAINMENT_PCT", "CLOSED_WON_ARR", "CLOSED_LOST_ARR", "WIN_RATE_PCT", "AVG_DEAL_SIZE", "STUCK_PIPELINE_ARR", "STUCK_DEAL_COUNT"]].copy()
    display_df.columns = ["Rep", "Quota ($)", "Attainment %", "Closed Won ($)", "Closed Lost ($)", "Win Rate %", "Avg Deal ($)", "Stuck Pipe ($)", "Stuck Deals"]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Quota ($)": st.column_config.NumberColumn(format="$%d"),
            "Attainment %": st.column_config.ProgressColumn(
                "Attainment %", min_value=0, max_value=150, format="%.1f%%"
            ),
            "Closed Won ($)": st.column_config.NumberColumn(format="$%d"),
            "Closed Lost ($)": st.column_config.NumberColumn(format="$%d"),
            "Win Rate %": st.column_config.NumberColumn(format="%.1f%%"),
            "Avg Deal ($)": st.column_config.NumberColumn(format="$%d"),
            "Stuck Pipe ($)": st.column_config.NumberColumn(format="$%d"),
        },
    )
else:
    st.info("No rep data for this quarter.")

st.markdown("---")

# =============================================================================
# SECTION 4: MANAGER ACTION NOTES
# =============================================================================
st.header("Manager Action Plan")

if not df_board.empty:
    # Exclude specific reps from action plan
    _EXCLUDE_FROM_ACTIONS = EXCLUDED_REPS
    df_board_actions = df_board[~df_board["REP"].isin(_EXCLUDE_FROM_ACTIONS)]

    # Team selector for action plan
    _action_team = st.selectbox("Team focus", ["None", "All"] + TEAM_OPTIONS, key="action_team")

    # High-value deals needing exec support (always shown)
    exec_sql = f"""
    SELECT
        de.display_name AS rep,
        fd.deal_name,
        dc.company_name,
        fd.deal_net_new_arr,
        fd.forecast_category,
        fd.deal_stage
    FROM {DWH}.FACT_DEALS fd
    JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
    LEFT JOIN {DWH}.DIM_COMPANY dc ON fd.sk_company = dc.sk_company
    WHERE fd.is_closed = FALSE
      AND fd.deal_net_new_arr >= 100000
      AND fd.forecast_category IN ('COMMIT', 'BEST_CASE', 'Most Likely')
      AND de.display_name NOT IN ({EXCLUDED_REPS_SQL})
      {build_filter_clauses()}
    ORDER BY fd.deal_net_new_arr DESC
    LIMIT 5
    """
    df_exec = run_query(exec_sql)

    st.subheader("Executive Support Needed")
    if not df_exec.empty:
        for _, d in df_exec.iterrows():
            company = d["COMPANY_NAME"] or d["DEAL_NAME"]
            st.markdown(
                f"- **{company}** — {fmt_arr_md(d['DEAL_NET_NEW_ARR'])} "
                f"({d['FORECAST_CATEGORY']}, {d['DEAL_STAGE']}). Rep: {d['REP']}"
            )
    else:
        st.info("No high-value deals in Commit/Best Case this quarter.")

    # Pipeline scrub + coaching only shown when a team is selected
    if _action_team != "None":
        if _action_team == "All":
            _df_action = df_board_actions
        else:
            _df_action = df_board_actions[df_board_actions["TEAM"] == _action_team]

        # Pipeline scrub: top 3 reps by stuck ARR (>$500K threshold)
        scrub_reps = _df_action[_df_action["STUCK_PIPELINE_ARR"] > 500_000].nlargest(3, "STUCK_PIPELINE_ARR")
        # Coaching candidates: various performance gaps
        low_wr = _df_action[(_df_action["WIN_RATE_PCT"] < 15) & (_df_action["WIN_RATE_PCT"] > 0)].nlargest(3, "STUCK_PIPELINE_ARR")
        zero_perf = _df_action[(_df_action["CLOSED_WON_ARR"] == 0) & (_df_action["WIN_RATE_PCT"].isna() | (_df_action["WIN_RATE_PCT"] == 0))].nlargest(3, "STUCK_PIPELINE_ARR")
        # High ASP / low win rate = qualification gap
        high_asp_low_wr = _df_action[(_df_action["AVG_DEAL_SIZE"] > _df_action["AVG_DEAL_SIZE"].median()) & (_df_action["WIN_RATE_PCT"] < _df_action["WIN_RATE_PCT"].median()) & (_df_action["WIN_RATE_PCT"] > 0)]
        # Low ASP / high win rate = upsell opportunity
        low_asp_high_wr = _df_action[(_df_action["AVG_DEAL_SIZE"] < _df_action["AVG_DEAL_SIZE"].median()) & (_df_action["WIN_RATE_PCT"] > _df_action["WIN_RATE_PCT"].median())]
        # High loss rate
        high_loss = _df_action[_df_action["CLOSED_LOST_ARR"] > _df_action["CLOSED_WON_ARR"]]
        # Lots of stuck but decent win rate = time management
        stuck_but_winning = _df_action[(_df_action["STUCK_PIPELINE_ARR"] > 300_000) & (_df_action["WIN_RATE_PCT"] > 20)]

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Pipeline Scrub List")
            if not scrub_reps.empty:
                for _, r in scrub_reps.iterrows():
                    stuck_count = int(r["STUCK_DEAL_COUNT"])
                    stuck_arr = r["STUCK_PIPELINE_ARR"]
                    won_arr = r["CLOSED_WON_ARR"]
                    if won_arr == 0 and stuck_count > 5:
                        action = "No wins + many stale deals — full pipeline reset session needed"
                    elif won_arr == 0:
                        action = "No wins and stuck pipe — review if deals are real or should be closed-lost"
                    elif stuck_count > 5:
                        action = "Batch close-lost the 3 oldest deals, then rebuild with fresh opps"
                    elif stuck_arr > 1_000_000:
                        action = "High-value stuck pipe — get VP on the largest deal to unstick or kill"
                    elif stuck_arr > won_arr:
                        action = "Carrying more dead weight than wins — force-rank and cut bottom half"
                    else:
                        action = "Review close plans and next steps on each stuck deal this 1:1"
                    st.markdown(f"- **{r['REP']}** — {fmt_arr_md(stuck_arr)} stuck ({stuck_count} deals). {action}")
            else:
                st.success("No reps with excessive stuck pipeline.")

        with col_b:
            st.subheader("Coaching Priorities")
            _coaching_items = []

            # Zero performers
            for _, r in zero_perf.iterrows():
                _coaching_items.append(f"- **{r['REP']}** — No wins this period. Shadow a top performer's next demo, then debrief.")

            # High ASP but losing deals = qualification issue
            for _, r in high_asp_low_wr.head(2).iterrows():
                if r["REP"] not in [x.split("**")[1] for x in _coaching_items if "**" in x]:
                    _coaching_items.append(f"- **{r['REP']}** — Hunting big ({fmt_arr_md(r['AVG_DEAL_SIZE'])}) but {r['WIN_RATE_PCT']:.0f}% WR. Map the buying committee and multi-thread.")

            # Low ASP but winning = upsell coaching
            for _, r in low_asp_high_wr.head(2).iterrows():
                if r["REP"] not in [x.split("**")[1] for x in _coaching_items if "**" in x]:
                    _coaching_items.append(f"- **{r['REP']}** — Strong execution ({r['WIN_RATE_PCT']:.0f}% WR) but undersized deals ({fmt_arr_md(r['AVG_DEAL_SIZE'])}). Bring SE to next call to pitch platform story.")

            # High loss rate = lost more than won
            for _, r in high_loss.head(2).iterrows():
                if len(_coaching_items) >= 4:
                    break
                if r["REP"] not in [x.split("**")[1] for x in _coaching_items if "**" in x]:
                    _coaching_items.append(f"- **{r['REP']}** — Lost more ({fmt_arr_md(r['CLOSED_LOST_ARR'])}) than won ({fmt_arr_md(r['CLOSED_WON_ARR'])}). Do a lost-deal retro: winnable or bad-fit pipe?")

            # Stuck but winning = prioritization issue
            for _, r in stuck_but_winning.head(2).iterrows():
                if len(_coaching_items) >= 4:
                    break
                if r["REP"] not in [x.split("**")[1] for x in _coaching_items if "**" in x]:
                    _coaching_items.append(f"- **{r['REP']}** — Winning ({r['WIN_RATE_PCT']:.0f}% WR) but {fmt_arr_md(r['STUCK_PIPELINE_ARR'])} stuck. Good closer, bad hygiene — set a 15-min weekly scrub ritual.")

            # Generic low win rate
            for _, r in low_wr.iterrows():
                if len(_coaching_items) >= 4:
                    break
                if r["REP"] not in [x.split("**")[1] for x in _coaching_items if "**" in x]:
                    _coaching_items.append(f"- **{r['REP']}** — {r['WIN_RATE_PCT']:.1f}% win rate. Review last 3 losses: pricing, competitor, or qualification gap?")

            if _coaching_items:
                for item in _coaching_items[:4]:
                    st.markdown(item)
            else:
                st.success("All reps performing above thresholds.")

        # AI-generated coaching suggestion (on-demand)
        st.subheader("AI Manager Brief")
        if st.button("Generate AI insights", key="ai_brief_btn"):
            _ai_data = _df_action[["REP", "ATTAINMENT_PCT", "CLOSED_WON_ARR", "CLOSED_LOST_ARR", "WIN_RATE_PCT", "AVG_DEAL_SIZE", "STUCK_PIPELINE_ARR", "STUCK_DEAL_COUNT"]].copy()
            _ai_data["CLOSED_WON_ARR"] = _ai_data["CLOSED_WON_ARR"].apply(lambda x: fmt_arr(x))
            _ai_data["CLOSED_LOST_ARR"] = _ai_data["CLOSED_LOST_ARR"].apply(lambda x: fmt_arr(x))
            _ai_data["AVG_DEAL_SIZE"] = _ai_data["AVG_DEAL_SIZE"].apply(lambda x: fmt_arr(x))
            _ai_data["STUCK_PIPELINE_ARR"] = _ai_data["STUCK_PIPELINE_ARR"].apply(lambda x: fmt_arr(x))
            _ai_summary = _ai_data.to_string(index=False)

            # Team-level summary
            _team_closed = fmt_arr(_df_action["CLOSED_WON_ARR"].sum())
            _team_open = fmt_arr(_df_action["STUCK_PIPELINE_ARR"].sum())
            _team_attainment = round(_df_action["ATTAINMENT_PCT"].mean(), 1)

            # Week-over-week deal movement (deals that changed stage or went dark)
            _rep_list = ",".join(f"'{r}'" for r in _df_action["REP"].tolist())
            _wow_sql = f"""
            SELECT
                de.display_name AS rep,
                COUNT(CASE WHEN fd.deal_closed_date >= DATEADD('DAY', -7, {SNAPSHOT_DATE_SQL}) AND fd.is_won = TRUE THEN 1 END) AS won_this_week,
                COUNT(CASE WHEN fd.deal_closed_date >= DATEADD('DAY', -7, {SNAPSHOT_DATE_SQL}) AND fd.is_won = FALSE AND fd.is_closed = TRUE THEN 1 END) AS lost_this_week,
                COUNT(CASE WHEN fd.is_closed = FALSE AND fd.deal_net_new_arr > 0
                    AND NOT EXISTS (
                        SELECT 1 FROM {DWH}.FACT_CALL fc
                        WHERE ARRAY_CONTAINS(fd.sk_deal::VARIANT, fc.associated_deal)
                          AND fc.effective_start_datetime >= DATEADD('DAY', -21, {SNAPSHOT_DATE_SQL})
                    ) THEN 1 END) AS deals_gone_dark
            FROM {DWH}.FACT_DEALS fd
            JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
            WHERE de.display_name IN ({_rep_list})
              AND (fd.deal_closed_date >= DATEADD('DAY', -7, {SNAPSHOT_DATE_SQL}) OR fd.is_closed = FALSE)
              AND fd.deal_net_new_arr > 0
            GROUP BY 1
            HAVING won_this_week > 0 OR lost_this_week > 0 OR deals_gone_dark > 0
            """
            _df_wow = run_query(_wow_sql)
            _wow_context = ""
            if not _df_wow.empty:
                _wow_lines = []
                for _, w in _df_wow.iterrows():
                    parts = []
                    if w["WON_THIS_WEEK"] > 0:
                        parts.append(f"+{int(w['WON_THIS_WEEK'])} won")
                    if w["LOST_THIS_WEEK"] > 0:
                        parts.append(f"-{int(w['LOST_THIS_WEEK'])} lost")
                    if w["DEALS_GONE_DARK"] > 0:
                        parts.append(f"{int(w['DEALS_GONE_DARK'])} deals with no call in 3 weeks")
                    _wow_lines.append(f"[{w['REP']}] {', '.join(parts)}")
                _wow_context = "This week's changes:\n" + "\n".join(_wow_lines)

            # Recent closed-lost reasons
            _lost_sql = f"""
            SELECT de.display_name AS rep, fd.deal_name, fd.closed_lost_reason
            FROM {DWH}.FACT_DEALS fd
            JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
            WHERE de.display_name IN ({_rep_list})
              AND fd.is_won = FALSE AND fd.is_closed = TRUE
              AND fd.deal_closed_date >= DATEADD('DAY', -30, {SNAPSHOT_DATE_SQL})
              AND fd.closed_lost_reason IS NOT NULL
            ORDER BY fd.deal_closed_date DESC
            LIMIT 5
            """
            _df_lost = run_query(_lost_sql)
            _lost_context = ""
            if not _df_lost.empty:
                _lost_lines = [f"[{r['REP']}] {r['DEAL_NAME']}: {r['CLOSED_LOST_REASON']}" for _, r in _df_lost.iterrows()]
                _lost_context = "Recent loss reasons (last 30d):\n" + "\n".join(_lost_lines)

            # Gong calls per open deal
            _gong_sql = f"""
            WITH open_deals AS (
                SELECT fd.sk_deal, fd.deal_name, de.display_name AS rep, de.sk_employee
                FROM {DWH}.FACT_DEALS fd
                JOIN {DWH}.DIM_EMPLOYEE de ON fd.sk_sales_owner = de.sk_employee
                WHERE fd.is_closed = FALSE
                  AND fd.deal_net_new_arr > 0
                  AND de.display_name IN ({_rep_list})
            ),
            recent_calls AS (
                SELECT fc.title, fc.call_spotlight_brief, fc.call_spotlight_next_steps,
                       fc.associated_deal, fc.associated_owner, fc.effective_start_datetime
                FROM {DWH}.FACT_CALL fc
                WHERE fc.effective_start_datetime >= DATEADD('MONTH', -3, {SNAPSHOT_DATE_SQL})
                  AND fc.call_spotlight_brief IS NOT NULL
            ),
            matched AS (
                SELECT
                    od.rep, od.deal_name, rc.title, rc.call_spotlight_brief, rc.call_spotlight_next_steps,
                    rc.effective_start_datetime,
                    ROW_NUMBER() OVER (PARTITION BY od.sk_deal ORDER BY rc.effective_start_datetime DESC) AS rn
                FROM open_deals od
                JOIN recent_calls rc
                  ON ARRAY_CONTAINS(od.sk_deal::VARIANT, rc.associated_deal)
                  AND ARRAY_CONTAINS(od.sk_employee::VARIANT, rc.associated_owner)
            )
            SELECT rep, title, deal_name, call_spotlight_brief, call_spotlight_next_steps
            FROM matched
            WHERE rn = 1
            ORDER BY effective_start_datetime DESC
            LIMIT 6
            """
            _df_gong = run_query(_gong_sql)
            _gong_context = ""
            if not _df_gong.empty:
                _gong_lines = []
                for _, g in _df_gong.iterrows():
                    deal = g['DEAL_NAME'] or g['TITLE']
                    brief = str(g['CALL_SPOTLIGHT_BRIEF'])[:120]
                    _gong_lines.append(f"[{g['REP']}] {deal}: {brief}")
                _gong_context = "Latest Gong call per open deal:\n" + "\n".join(_gong_lines)

            _ai_prompt = f"""You are a VP of Sales. Write 3-4 short bullet points for the {_action_team} manager's weekly focus.

Rules: each bullet = 1 sentence. Use rep names + deal names. Focus on what changed this week and what needs immediate action. No filler.

Team ({_period_label}): avg attainment {_team_attainment}%, closed {_team_closed}, stuck pipe {_team_open}

Per rep:
{_ai_summary}

{_wow_context}

{_lost_context}

{_gong_context}
"""
            _ai_sql = f"""SELECT SNOWFLAKE.CORTEX.COMPLETE('mistral-large2', $${_ai_prompt}$$) AS response"""

            with st.spinner("Analyzing team data + Gong calls..."):
                _ai_result = run_llm(_ai_sql)
            if not _ai_result.empty:
                st.markdown(_ai_result.iloc[0]["RESPONSE"])
            st.caption("AI-generated content may contain inaccuracies. Verify before acting.")

else:
    st.info("Load data to generate action items.")

st.markdown("---")
st.caption("Quotas from FY2026 comp plan. Connect GONG Forecast Targets when available for live updates.")
