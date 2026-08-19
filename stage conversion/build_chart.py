"""
Generates a self-contained Plotly HTML file with interactive stage conversion line chart.
Dropdowns: From Stage, To Stage, Metric, Pacing, Deals Filter, Breakdown.
"""

import json
import os
from datetime import datetime, timezone

import pandas as pd

from build_deals import (
    CLASSIC_STAGE_ORDER,
    load_json_files,
    deduplicate,
    deals_to_dataframe,
    stage_timestamps_dataframe,
)

FOLDER = os.path.dirname(os.path.abspath(__file__))
CHART_STAGES = [s for s in CLASSIC_STAGE_ORDER if "SDR" not in s]
MIN_QUARTER = datetime(2025, 1, 1, tzinfo=timezone.utc)
BREAKDOWN_DIMS = {"none": "None", "team": "Team", "geo": "Geo", "mega_source": "Mega Source"}


def load_data():
    import json as _json
    from build_deals import Deal

    # Prefer the fresh fetch (hubspot_deals.json) if it exists; otherwise fall back
    # to the manual response (4-7).json exports.
    fresh_path = os.path.join(FOLDER, "hubspot_deals.json")
    if os.path.exists(fresh_path):
        with open(fresh_path) as fh:
            data = _json.load(fh)
        raw = [Deal.from_raw(r) for r in data.get("results", [])]
        print(f"Loaded {len(raw)} deal records from hubspot_deals.json")
    else:
        files = [
            os.path.join(FOLDER, "response (4).json"),
            os.path.join(FOLDER, "response (5).json"),
            os.path.join(FOLDER, "response (6).json"),
            os.path.join(FOLDER, "response (7).json"),
        ]
        raw = []
        for f in files:
            with open(f) as fh:
                data = _json.load(fh)
            for r in data.get("results", []):
                raw.append(Deal.from_raw(r))
        print(f"Loaded {len(raw)} deal records from {len(files)} files (responses 4-7)")

    deals = deduplicate(raw)
    deals_df = deals_to_dataframe(deals)
    ts_df = stage_timestamps_dataframe(deals)

    base_mask = (
        (deals_df["pipeline"] == "Classic")
        & (deals_df["deal_type"] == "New Business")
        & (pd.to_datetime(deals_df["qualified_date"], errors="coerce") >= pd.Timestamp("2024-01-01"))
    )
    all_deals_df = deals_df[base_mask].reset_index(drop=True)
    all_ts_df = ts_df[ts_df["deal_id"].isin(all_deals_df["deal_id"])].reset_index(drop=True)

    merged_all = all_ts_df.merge(
        all_deals_df[["deal_id", "deal_name", "amount", "qualified_date",
                       "team", "geo", "mega_source", "deal_source", "stage"]],
        on="deal_id", how="left",
    )

    closed_ids = all_deals_df.loc[
        all_deals_df["stage"].isin(["Closed Won", "Closed Lost"]), "deal_id"
    ]
    merged_closed = merged_all[merged_all["deal_id"].isin(closed_ids)].reset_index(drop=True)

    return merged_closed, merged_all




def quarter_start(dt):
    q_month = ((dt.month - 1) // 3) * 3 + 1
    return datetime(dt.year, q_month, 1, tzinfo=timezone.utc)


def days_into_quarter(dt):
    qs = quarter_start(dt)
    return (dt - qs).days


def quarter_label(dt):
    q = (dt.month - 1) // 3 + 1
    return f"Q{q} {dt.year}"


def prepare_entered(merged: pd.DataFrame, from_stage: str, to_stage: str):
    """Filter and prepare deals for a stage pair."""
    entered = merged[merged[from_stage].notna()].copy()
    if entered.empty:
        return None

    if "qualified_date" in entered.columns:
        qual = pd.to_datetime(entered["qualified_date"], utc=True, errors="coerce")
        entered = entered[entered[from_stage] >= qual].copy()
        if entered.empty:
            return None

    entered["from_q_start"] = entered[from_stage].apply(quarter_start)
    entered["from_q_label"] = entered[from_stage].apply(quarter_label)
    entered["from_days_in_q"] = entered[from_stage].apply(days_into_quarter)
    entered = entered[entered["from_q_start"] >= MIN_QUARTER]
    if entered.empty:
        return None

    entered["converted"] = entered[to_stage].notna()
    # For Method C pacing: days between from-stage quarter start and to-stage entry
    entered["to_days_from_q_start"] = (
        (entered[to_stage] - entered["from_q_start"]).dt.total_seconds() / 86400
    )
    # Time between stages (for raw table display)
    entered["days_to_next"] = (entered[to_stage] - entered[from_stage]).dt.total_seconds() / 86400
    return entered


def compute_series(subset: pd.DataFrame, pacing_days: int):
    """Compute quarterly conversion for a subset of deals."""
    all_quarters = sorted(subset["from_q_start"].unique())

    full_deals, full_arr, paced_deals, paced_arr = [], [], [], []

    for q_start in all_quarters:
        q_label = quarter_label(q_start.to_pydatetime() if hasattr(q_start, 'to_pydatetime') else q_start)
        q_deals = subset[subset["from_q_start"] == q_start]

        dc = len(q_deals)
        da = q_deals["amount"].sum()
        nc = int(q_deals["converted"].sum())
        na = q_deals.loc[q_deals["converted"], "amount"].sum()

        full_deals.append({"quarter": q_label, "rate": (nc / dc * 100) if dc > 0 else None, "numerator": nc, "denominator": dc})
        full_arr.append({"quarter": q_label, "rate": (na / da * 100) if da > 0 else None, "numerator": float(na), "denominator": float(da)})

        # Paced (Method C): both cohort AND numerator are clipped to first `pacing_days` of quarter
        # - Cohort: deals that entered from-stage in first `pacing_days` days of quarter
        # - Converted: of cohort, reached to-stage by day `pacing_days` of quarter
        pq = q_deals[q_deals["from_days_in_q"] <= pacing_days]
        pdc = len(pq)
        pda = pq["amount"].sum()
        paced_converted = pq["converted"] & (pq["to_days_from_q_start"] <= pacing_days)
        pnc = int(paced_converted.sum())
        pna = pq.loc[paced_converted, "amount"].sum()

        paced_deals.append({"quarter": q_label, "rate": (pnc / pdc * 100) if pdc > 0 else None, "numerator": pnc, "denominator": pdc})
        paced_arr.append({"quarter": q_label, "rate": (pna / pda * 100) if pda > 0 else None, "numerator": float(pna), "denominator": float(pda)})

    return {"full_deals": full_deals, "full_arr": full_arr, "paced_deals": paced_deals, "paced_arr": paced_arr}


def compute_all(merged: pd.DataFrame):
    """Compute conversions for overall + each breakdown dimension."""
    now = datetime.now(timezone.utc)
    pacing_days = days_into_quarter(now) - 1
    current_q_label = quarter_label(now)

    merged["team"] = merged["team"].fillna("Unknown")
    merged["geo"] = merged["geo"].fillna("Unknown")
    merged["mega_source"] = merged["mega_source"].fillna("Unknown")

    stages = CHART_STAGES
    # Structure: {stage_pair: {none: {All: series}, team: {val: series}, geo: {val: series}, ...}}
    results = {}

    for i, from_stage in enumerate(stages[:-1]):
        for to_stage in stages[i + 1:]:
            entered = prepare_entered(merged, from_stage, to_stage)
            if entered is None:
                continue

            key = f"{from_stage}|{to_stage}"
            results[key] = {}

            # Overall
            results[key]["none"] = {"All": compute_series(entered, pacing_days)}

            # Breakdowns
            for dim in ["team", "geo", "mega_source"]:
                results[key][dim] = {}
                for val, group in entered.groupby(dim):
                    if len(group) >= 3:  # skip tiny groups
                        results[key][dim][str(val)] = compute_series(group, pacing_days)

    return results, current_q_label, pacing_days


def compute_raw_data(merged: pd.DataFrame):
    now = datetime.now(timezone.utc)
    pacing_days = days_into_quarter(now) - 1

    stages = CHART_STAGES
    raw_data = {}

    for i, from_stage in enumerate(stages[:-1]):
        for to_stage in stages[i + 1:]:
            entered = prepare_entered(merged, from_stage, to_stage)
            if entered is None:
                continue

            records = []
            for _, row in entered.iterrows():
                from_dt = row[from_stage]
                to_dt = row[to_stage] if row["converted"] else None
                records.append({
                    "deal_id": row["deal_id"],
                    "deal_name": row.get("deal_name", "") or "",
                    "company_name": "",
                    "team": row.get("team", "") or "",
                    "geo": row.get("geo", "") or "",
                    "mega_source": row.get("mega_source", "") or "",
                    "deal_source": row.get("deal_source", "") or "",
                    "current_stage": row.get("stage", "") or "",
                    "amount": row["amount"] if pd.notna(row["amount"]) else 0,
                    "quarter": row["from_q_label"],
                    "from_date": from_dt.strftime("%Y-%m-%d") if pd.notna(from_dt) else None,
                    "to_date": to_dt.strftime("%Y-%m-%d") if pd.notna(to_dt) else None,
                    "converted": bool(row["converted"]),
                    "days_in_q": int(row["from_days_in_q"]),
                    "to_days_from_q_start": float(row["to_days_from_q_start"]) if pd.notna(row.get("to_days_from_q_start")) else None,
                })

            raw_data[f"{from_stage}|{to_stage}"] = records

    return raw_data


def build_html(data_closed: dict, data_all: dict, current_q_label: str, pacing_days: int, raw_closed: dict, raw_all: dict, generated_at: str):
    stages_json = json.dumps(CHART_STAGES)
    data_closed_json = json.dumps(data_closed)
    data_all_json = json.dumps(data_all)
    raw_closed_json = json.dumps(raw_closed)
    raw_all_json = json.dumps(raw_all)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Stage Conversion Analysis</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  :root {{
    --bg: #f5f7fb;
    --surface: #ffffff;
    --border: #e5e7eb;
    --text: #0f172a;
    --text-muted: #64748b;
    --text-subtle: #94a3b8;
    --primary: #4f46e5;
    --primary-hover: #4338ca;
    --primary-soft: #eef2ff;
    --success: #16a34a;
    --danger: #dc2626;
    --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
    --shadow-md: 0 1px 3px rgba(15, 23, 42, 0.06), 0 4px 12px rgba(15, 23, 42, 0.04);
    --radius: 10px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif;
    margin: 0; padding: 28px 32px 60px; background: var(--bg); color: var(--text);
    font-size: 14px; line-height: 1.5;
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  }}
  h2 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.01em; margin: 0 0 4px; }}
  h3 {{ font-size: 16px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 4px; color: var(--text); }}
  .header-row {{
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 16px; margin-bottom: 4px;
  }}
  .refresh-bar {{
    display: flex; align-items: center; gap: 10px; font-size: 12px;
    color: var(--text-muted); white-space: nowrap;
  }}
  #refresh-btn {{
    padding: 6px 14px; border: 1px solid var(--border); border-radius: 8px;
    background: white; color: var(--text); cursor: pointer; font-family: inherit;
    font-size: 12.5px; font-weight: 500; transition: background 0.1s, border-color 0.1s;
  }}
  #refresh-btn:hover:not(:disabled) {{ background: var(--primary-soft); border-color: var(--primary); color: var(--primary); }}
  #refresh-btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  #refresh-status {{ font-style: italic; color: var(--text-subtle); }}
  .scope {{ font-size: 13px; color: var(--text-muted); margin-bottom: 4px; }}
  .scope strong {{ color: var(--text); font-weight: 600; }}
  .question {{ font-size: 12.5px; color: var(--text-subtle); font-style: italic; margin-bottom: 20px; }}
  .question strong {{ color: var(--text-muted); font-style: normal; font-weight: 600; }}

  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 22px; box-shadow: var(--shadow-md);
    margin-bottom: 20px;
  }}

  .controls {{
    display: flex; gap: 14px; flex-wrap: wrap; align-items: flex-end;
    padding: 16px 18px; background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); margin-bottom: 20px; box-shadow: var(--shadow-sm);
  }}
  .control-group {{ display: flex; flex-direction: column; position: relative; min-width: 140px; }}
  .control-group label {{
    font-size: 10.5px; font-weight: 600; color: var(--text-muted);
    margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.06em;
    display: flex; align-items: center;
  }}
  select {{
    padding: 8px 32px 8px 12px; border: 1px solid var(--border); border-radius: 8px;
    font-size: 13px; background: white; color: var(--text); cursor: pointer;
    font-family: inherit; appearance: none;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='%2364748b' d='M6 8L2 4h8z'/></svg>");
    background-repeat: no-repeat; background-position: right 10px center;
    transition: border-color 0.15s, box-shadow 0.15s;
  }}
  select:hover {{ border-color: #cbd5e1; }}
  select:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12); }}

  #chart, #chart2 {{
    width: 100%; height: 520px; background: var(--surface);
    border-radius: var(--radius); border: 1px solid var(--border);
    padding: 12px; box-shadow: var(--shadow-md);
  }}
  #chart2 {{ height: 460px; margin-bottom: 24px; }}

  .section-header {{ margin: 8px 0 12px; }}
  .section-header h3 {{ display: inline-block; margin-right: 8px; }}

  .info {{
    font-size: 12.5px; color: var(--text-muted);
    background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--primary);
    padding: 12px 16px; border-radius: 8px; margin-top: 16px; line-height: 1.55;
  }}
  .info strong {{ color: var(--text); font-weight: 600; }}

  #raw-section {{ margin-top: 24px; }}
  .raw-controls {{
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 12px;
  }}
  #raw-filter {{
    padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
    font-size: 13px; width: 340px; font-family: inherit; background: white;
    transition: border-color 0.15s, box-shadow 0.15s;
  }}
  #raw-filter:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12); }}
  #raw-filter::placeholder {{ color: var(--text-subtle); }}
  #raw-conv-filter {{
    padding: 8px 30px 8px 12px; border: 1px solid var(--border); border-radius: 8px;
    font-size: 13px; background: white; cursor: pointer; appearance: none;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='%2364748b' d='M6 8L2 4h8z'/></svg>");
    background-repeat: no-repeat; background-position: right 10px center; font-family: inherit;
  }}
  #deal-count-label {{ font-size: 12.5px; color: var(--text-muted); margin-left: auto; }}

  #raw-table {{
    width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12.5px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow-sm);
  }}
  #raw-table th {{
    background: #f8fafc; color: var(--text-muted); padding: 10px 14px;
    text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.04em; border-bottom: 1px solid var(--border);
    cursor: pointer; user-select: none; white-space: nowrap;
    transition: background 0.1s, color 0.1s;
  }}
  #raw-table th:hover {{ background: #eef2ff; color: var(--primary); }}
  #raw-table th.sorted {{ background: var(--primary-soft); color: var(--primary); }}
  #raw-table th .sort-arrow {{ font-size: 9px; margin-left: 4px; opacity: 0.5; }}
  #raw-table th.sorted .sort-arrow {{ opacity: 1; }}
  #raw-table td {{
    padding: 8px 14px; border-bottom: 1px solid #f1f5f9; color: var(--text);
    white-space: nowrap;
  }}
  #raw-table tbody tr:last-child td {{ border-bottom: none; }}
  #raw-table tbody tr:hover td {{ background: #f8fafc; }}
  .converted-yes {{ color: var(--success); font-weight: 700; }}
  .converted-no {{ color: var(--danger); font-weight: 500; opacity: 0.85; }}

  .info-icon {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 15px; height: 15px; border-radius: 50%;
    background: #e2e8f0; color: var(--text-muted);
    font-size: 10px; font-weight: 700; cursor: help; margin-left: 6px;
    font-family: Georgia, serif; font-style: italic; position: relative;
    transition: background 0.15s, color 0.15s;
  }}
  .info-icon:hover {{ background: var(--primary); color: white; }}
  .info-icon:hover .tooltip {{ visibility: visible; opacity: 1; transform: translateX(-50%) translateY(-4px); }}
  .tooltip {{
    visibility: hidden; opacity: 0;
    transition: opacity 0.15s, transform 0.15s;
    position: absolute; z-index: 100; bottom: 24px; left: 50%;
    transform: translateX(-50%); width: 320px; padding: 12px 14px;
    background: #0f172a; color: #f1f5f9; border-radius: 8px;
    font-size: 12px; line-height: 1.55; font-family: inherit; font-style: normal;
    font-weight: 400; text-align: left;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.25), 0 2px 4px rgba(15, 23, 42, 0.1);
    text-transform: none; letter-spacing: normal;
  }}
  .tooltip strong {{ color: white; font-weight: 600; }}
  .tooltip em {{ color: #a5b4fc; font-style: normal; font-weight: 500; }}
  .tooltip::after {{
    content: ''; position: absolute; top: 100%; left: 50%; margin-left: -6px;
    border: 6px solid transparent; border-top-color: #0f172a;
  }}
</style>
</head>
<body>
<div class="header-row">
  <div>
    <h2>Stage-to-Stage Conversion Rate by Quarter</h2>
    <div class="scope">
      Pipeline = <strong>Classic</strong> &middot; Deal Type = <strong>New Business</strong> &middot; Qualified Date &ge; <strong>2024-01-01</strong>
    </div>
  </div>
  <div class="refresh-bar">
    <span id="last-refreshed"></span>
    <button id="refresh-btn" title="Rebuild the dashboard from fresh HubSpot + Snowflake data">Refresh</button>
    <span id="refresh-status"></span>
  </div>
</div>
<div class="question">
  Of deals that entered the <strong>From Stage</strong> in each quarter, what % reached the <strong>To Stage</strong>?
  <br>
  <span style="color:var(--text-subtle);">Entry-cohort: grouped by from-stage entry quarter.</span>
</div>
<div class="controls">
  <div class="control-group">
    <label>From Stage</label>
    <select id="fromStage"></select>
  </div>
  <div class="control-group">
    <label>To Stage</label>
    <select id="toStage"></select>
  </div>
  <div class="control-group">
    <label>Metric</label>
    <select id="metric">
      <option value="arr">ARR</option>
      <option value="deals">Deal Count</option>
    </select>
  </div>
  <div class="control-group">
    <label>Pacing <span class="info-icon">i<span class="tooltip"><strong>Method C — Apples-to-apples pacing.</strong><br><br>Every quarter is measured at <strong>day {pacing_days}</strong> (matching current elapsed days in {current_q_label}).<br><br><strong>Cohort:</strong> deals that entered the <em>from-stage</em> in the first {pacing_days} days of the quarter.<br><br><strong>Converted:</strong> of that cohort, deals whose <em>to-stage</em> entry was also within day {pacing_days} of the same quarter.<br><br>Both bounds use the identical cutoff so no quarter gets extra time.</span></span></label>
    <select id="pacing">
      <option value="paced">Paced (first {pacing_days} days)</option>
      <option value="full">Full Quarter</option>
    </select>
  </div>
  <div class="control-group">
    <label>Deals Filter</label>
    <select id="closedFilter">
      <option value="closed">Closed Only</option>
      <option value="all">All Deals</option>
    </select>
  </div>
  <div class="control-group">
    <label>Breakdown</label>
    <select id="breakdown">
      <option value="none">None</option>
      <option value="team">Team</option>
      <option value="geo">Geo</option>
      <option value="mega_source">Mega Source</option>
    </select>
  </div>
</div>
<div id="chart"></div>
<div style="height:32px;"></div>
<h3>Stage → Closed Won <span style="color:var(--text-subtle);font-weight:500;">(all stages)</span></h3>
<div class="question" style="margin-bottom:12px;">
  Of deals that entered a given stage in each quarter, what % <strong>eventually reached Closed Won</strong> (at any time)?
</div>
<div id="chart2"></div>
<div id="raw-section">
  <h3>Raw Data</h3>
  <div class="raw-controls">
    <input type="text" id="raw-filter" placeholder="Filter by name, company, team, geo, source...">
    <select id="raw-conv-filter">
      <option value="all">All</option>
      <option value="yes">Converted Only</option>
      <option value="no">Not Converted</option>
    </select>
    <span id="deal-count-label"></span>
  </div>
  <table id="raw-table"><thead></thead><tbody></tbody></table>
</div>
<div class="info">
  Pacing snapshots every quarter at <strong>day {pacing_days}</strong> (Method C):
  cohort = deals entering from-stage in the first {pacing_days} days of the quarter;
  converted = of that cohort, reached to-stage by day {pacing_days} of the same quarter.
  Matches elapsed time in current quarter {current_q_label} (up through yesterday).
  Conversion = deals reaching "To Stage" / deals that entered "From Stage" in that quarter.
</div>

<script>
const STAGES = {stages_json};
const DATA_CLOSED = {data_closed_json};
const DATA_ALL = {data_all_json};
const RAW_CLOSED = {raw_closed_json};
const RAW_ALL = {raw_all_json};
const PACING_DAYS = {pacing_days};
const GENERATED_AT = "{generated_at}";
const COLORS = ['#4f46e5','#dc2626','#16a34a','#ca8a04','#9333ea','#0891b2','#be185d','#65a30d','#c2410c','#6366f1'];
const TARGETS = {{
  "Demo / Presentation|Business Validation": 70,
  "Formal Pilot|Business Case Confirmation": 85,
  "Business Case Confirmation|Negotiation / Legal": 80,
  "Negotiation / Legal|Closed Won": 90,
}};

const fromSelect = document.getElementById('fromStage');
const toSelect = document.getElementById('toStage');
const metricSelect = document.getElementById('metric');
const pacingSelect = document.getElementById('pacing');
const closedFilter = document.getElementById('closedFilter');
const breakdownSelect = document.getElementById('breakdown');

STAGES.slice(0, -1).forEach((s, i) => {{
  const opt = document.createElement('option');
  opt.value = s; opt.text = s;
  if (i === 0) opt.selected = true;
  fromSelect.appendChild(opt);
}});

function updateToOptions() {{
  const fromIdx = STAGES.indexOf(fromSelect.value);
  toSelect.innerHTML = '';
  STAGES.slice(fromIdx + 1).forEach((s, i) => {{
    const opt = document.createElement('option');
    opt.value = s; opt.text = s;
    if (i === 0) opt.selected = true;
    toSelect.appendChild(opt);
  }});
  updateChart();
}}

function updateChart() {{
  const from = fromSelect.value;
  const to = toSelect.value;
  const metric = metricSelect.value;
  const pacing = pacingSelect.value;
  const closed = closedFilter.value;
  const breakdown = breakdownSelect.value;

  const DATA = closed === 'closed' ? DATA_CLOSED : DATA_ALL;
  const key = from + '|' + to;
  const seriesKey = pacing + '_' + metric;

  if (!DATA[key] || !DATA[key][breakdown]) {{
    Plotly.react('chart', [], {{
      annotations: [{{text: 'No data for this combination', showarrow: false, font: {{size: 16}}}}],
      xaxis: {{visible: false}}, yaxis: {{visible: false}}
    }});
    updateRawTable(from, to, pacing, closed);
    return;
  }}

  const dimData = DATA[key][breakdown];
  const traces = [];
  const groups = Object.keys(dimData).sort();

  groups.forEach((groupName, idx) => {{
    const series = dimData[groupName][seriesKey];
    if (!series || series.length === 0) return;

    const x = series.map(d => d.quarter);
    const y = series.map(d => d.rate);
    const suffix = pacing === 'paced' ? ' [first ' + PACING_DAYS + 'd]' : '';
    const hoverText = series.map(d => {{
      const pct = d.rate !== null ? d.rate.toFixed(1) + '%' : 'N/A';
      if (metric === 'deals') return groupName + suffix + ': ' + pct + ' (' + d.numerator + '/' + d.denominator + ')';
      return groupName + suffix + ': ' + pct + ' ($' + Math.round(d.numerator).toLocaleString() + '/$' + Math.round(d.denominator).toLocaleString() + ')';
    }});

    traces.push({{
      x: x,
      y: y,
      type: 'scatter',
      mode: groups.length === 1 ? 'lines+markers+text' : 'lines+markers',
      name: groupName,
      text: groups.length === 1 ? y.map(v => v !== null ? v.toFixed(1) + '%' : '') : undefined,
      textposition: 'top center',
      textfont: {{ size: 11 }},
      hovertext: hoverText,
      hoverinfo: 'text+x',
      line: {{ color: COLORS[idx % COLORS.length], width: 2.5 }},
      marker: {{ size: 7 }},
    }});
  }});

  const breakdownLabel = breakdown === 'none' ? '' : ' by ' + breakdown.replace('mega_source', 'Mega Source').replace('geo', 'Geo').replace('team', 'Team');
  const pacingLabel = pacing === 'paced' ? '  ·  First ' + PACING_DAYS + ' days of each quarter' : '';

  // Target line: only show for ARR + Full Quarter + Closed Only + no breakdown, and if defined
  const targetKey = from + '|' + to;
  const target = (
    metric === 'arr'
    && pacing === 'full'
    && closed === 'closed'
    && breakdown === 'none'
    && TARGETS[targetKey] !== undefined
  ) ? TARGETS[targetKey] : null;

  const layout = {{
    title: {{
      text: from + ' → ' + to + breakdownLabel + '<br><span style="font-size:12px;color:#64748b;font-weight:400;">' + (pacing === 'paced' ? 'Snapshot at day ' + PACING_DAYS + ' of each quarter' : 'Full quarter') + '</span>',
      font: {{ size: 15 }}
    }},
    xaxis: {{ title: 'Quarter' + pacingLabel, tickangle: -45 }},
    yaxis: {{ title: 'Conversion Rate (%)', rangemode: 'tozero' }},
    margin: {{ t: 70, b: 80, l: 60, r: 30 }},
    hovermode: 'x unified',
    showlegend: groups.length > 1 || target !== null,
    legend: {{ orientation: 'h', y: -0.25 }},
  }};

  if (target !== null && traces.length > 0) {{
    const xVals = traces[0].x;
    traces.push({{
      x: xVals,
      y: xVals.map(() => target),
      type: 'scatter',
      mode: 'lines',
      name: 'Target: ' + target + '%',
      line: {{ color: '#16a34a', width: 2, dash: 'dash' }},
      hovertext: xVals.map(() => 'Target: ' + target + '%'),
      hoverinfo: 'text+x',
    }});
  }}

  Plotly.react('chart', traces, layout);
  updateRawTable(from, to, pacing, closed);
  updateChart2();
}}

function updateChart2() {{
  const metric = metricSelect.value;
  const pacing = pacingSelect.value;
  const closed = closedFilter.value;
  const DATA = closed === 'closed' ? DATA_CLOSED : DATA_ALL;
  const seriesKey = pacing + '_' + metric;

  // Each stage → Closed Won
  const stagesForWon = STAGES.slice(0, -1); // all except Closed Won itself
  const traces2 = [];

  stagesForWon.forEach((stage, idx) => {{
    const key = stage + '|Closed Won';
    if (!DATA[key] || !DATA[key]['none'] || !DATA[key]['none']['All']) return;
    const series = DATA[key]['none']['All'][seriesKey];
    if (!series || series.length === 0) return;

    traces2.push({{
      x: series.map(d => d.quarter),
      y: series.map(d => d.rate),
      type: 'scatter',
      mode: 'lines+markers',
      name: stage,
      hovertext: series.map(d => {{
        const pct = d.rate !== null ? d.rate.toFixed(1) + '%' : 'N/A';
        const suf = pacing === 'paced' ? ' [first ' + PACING_DAYS + 'd]' : '';
        if (metric === 'deals') return stage + suf + ': ' + pct + ' (' + d.numerator + '/' + d.denominator + ')';
        return stage + suf + ': ' + pct + ' ($' + Math.round(d.numerator).toLocaleString() + '/$' + Math.round(d.denominator).toLocaleString() + ')';
      }}),
      hoverinfo: 'text+x',
      line: {{ color: COLORS[idx % COLORS.length], width: 2.5 }},
      marker: {{ size: 7 }},
    }});
  }});

  const layout2 = {{
    title: {{
      text: 'Stage → Closed Won<br><span style="font-size:12px;color:#64748b;font-weight:400;">' + (pacing === 'paced' ? 'Snapshot at day ' + PACING_DAYS + ' of each quarter' : 'Full quarter') + '  ·  ' + (metric === 'arr' ? 'ARR' : 'Deal Count') + '</span>',
      font: {{ size: 15 }}
    }},
    xaxis: {{ title: 'Quarter' + (pacing === 'paced' ? '  ·  First ' + PACING_DAYS + ' days of each quarter' : ''), tickangle: -45 }},
    yaxis: {{ title: 'Conversion Rate (%)', rangemode: 'tozero' }},
    margin: {{ t: 70, b: 80, l: 60, r: 30 }},
    hovermode: 'x unified',
    showlegend: true,
    legend: {{ orientation: 'h', y: -0.25 }},
  }};

  Plotly.react('chart2', traces2, layout2);
}}

let currentRecords = [];
let sortCol = null;
let sortAsc = true;

function updateRawTable(from, to, pacing, closed) {{
  const RAW = closed === 'closed' ? RAW_CLOSED : RAW_ALL;
  const key = from + '|' + to;
  let records = (RAW[key] || []).slice();

  if (pacing === 'paced') {{
    // Method C: cohort is deals in first N days of quarter;
    // convert flag flipped to false if to-stage happened after day N
    records = records.filter(r => r.days_in_q <= PACING_DAYS).map(r => {{
      const pacedConv = r.converted && r.to_days_from_q_start !== null && r.to_days_from_q_start <= PACING_DAYS;
      return Object.assign({{}}, r, {{ converted: pacedConv }});
    }});
  }}

  currentRecords = records;
  sortCol = 'quarter';
  sortAsc = false;
  document.getElementById('raw-filter').value = '';
  document.getElementById('raw-conv-filter').value = 'all';
  renderTable();
}}

function renderTable() {{
  let records = currentRecords.slice();
  const filterText = document.getElementById('raw-filter').value.toLowerCase();
  const convFilter = document.getElementById('raw-conv-filter').value;

  if (filterText) {{
    records = records.filter(r =>
      (r.deal_name || '').toLowerCase().includes(filterText) ||
      (r.company_name || '').toLowerCase().includes(filterText) ||
      (r.team || '').toLowerCase().includes(filterText) ||
      (r.geo || '').toLowerCase().includes(filterText) ||
      (r.mega_source || '').toLowerCase().includes(filterText) ||
      (r.current_stage || '').toLowerCase().includes(filterText) ||
      (r.deal_source || '').toLowerCase().includes(filterText)
    );
  }}

  if (convFilter === 'yes') records = records.filter(r => r.converted);
  if (convFilter === 'no') records = records.filter(r => !r.converted);

  if (sortCol) {{
    records.sort((a, b) => {{
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) va = '';
      if (vb == null) vb = '';
      if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va;
      if (typeof va === 'boolean') {{ va = va ? 1 : 0; vb = vb ? 1 : 0; return sortAsc ? va - vb : vb - va; }}
      va = String(va); vb = String(vb);
      return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    }});
  }}

  const cols = [
    {{key: 'deal_name', label: 'Deal Name'}},
    {{key: 'company_name', label: 'Company'}},
    {{key: 'team', label: 'Team'}},
    {{key: 'geo', label: 'Geo'}},
    {{key: 'mega_source', label: 'Source'}},
    {{key: 'current_stage', label: 'Current Stage'}},
    {{key: 'amount', label: 'Amount'}},
    {{key: 'quarter', label: 'Quarter'}},
    {{key: 'from_date', label: 'From Date'}},
    {{key: 'to_date', label: 'To Date'}},
    {{key: 'converted', label: 'Conv'}},
  ];

  const thead = document.querySelector('#raw-table thead');
  const tbody = document.querySelector('#raw-table tbody');
  thead.innerHTML = '<tr>' + cols.map(c => {{
    const arrow = sortCol === c.key ? (sortAsc ? '\u25B2' : '\u25BC') : '\u25B4';
    const cls = sortCol === c.key ? ' class="sorted"' : '';
    return '<th' + cls + ' data-col="' + c.key + '">' + c.label + '<span class="sort-arrow">' + arrow + '</span></th>';
  }}).join('') + '</tr>';

  tbody.innerHTML = records.map(r => {{
    const cc = r.converted ? 'converted-yes' : 'converted-no';
    const ct = r.converted ? 'Y' : 'N';
    const amt = r.amount ? '$' + Math.round(r.amount).toLocaleString() : '-';
    return '<tr><td>' + (r.deal_name || r.deal_id) + '</td><td>' + (r.company_name || '-') + '</td><td>' + (r.team || '-') + '</td><td>' + (r.geo || '-') + '</td><td>' + (r.mega_source || '-') + '</td><td>' + (r.current_stage || '-') + '</td><td>' + amt + '</td><td>' + r.quarter + '</td><td>' + (r.from_date || '-') + '</td><td>' + (r.to_date || '-') + '</td><td class="' + cc + '">' + ct + '</td></tr>';
  }}).join('');

  document.getElementById('deal-count-label').textContent = records.length + ' of ' + currentRecords.length + ' deals';

  // Attach sort handlers
  thead.querySelectorAll('th').forEach(th => {{
    th.onclick = () => {{
      const col = th.dataset.col;
      if (sortCol === col) {{ sortAsc = !sortAsc; }}
      else {{ sortCol = col; sortAsc = true; }}
      renderTable();
    }};
  }});
}}

document.getElementById('raw-filter').addEventListener('input', renderTable);
document.getElementById('raw-conv-filter').addEventListener('change', renderTable);

fromSelect.addEventListener('change', updateToOptions);
toSelect.addEventListener('change', updateChart);
metricSelect.addEventListener('change', updateChart);
pacingSelect.addEventListener('change', updateChart);
closedFilter.addEventListener('change', updateChart);
breakdownSelect.addEventListener('change', updateChart);

// ─── Refresh toolbar ───
const _gen = new Date(GENERATED_AT);
const _lastRefreshedEl = document.getElementById('last-refreshed');
const _refreshBtn = document.getElementById('refresh-btn');
const _refreshStatusEl = document.getElementById('refresh-status');

function _fmtRelative(dt) {{
  const diffMs = Date.now() - dt.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + ' min ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return hrs + ' hr ago';
  const days = Math.floor(hrs / 24);
  return days + ' day' + (days === 1 ? '' : 's') + ' ago';
}}
_lastRefreshedEl.textContent = 'Last refreshed: ' + _gen.toLocaleString() + ' · ' + _fmtRelative(_gen);

function _setStatus(t) {{ _refreshStatusEl.textContent = t || ''; }}
function _isAppsScript() {{ return typeof google !== 'undefined' && google.script && google.script.run; }}

_refreshBtn.onclick = function() {{
  if (!_isAppsScript()) {{
    _setStatus('Refresh only works when served by Apps Script.');
    return;
  }}
  if (_gen.toDateString() === new Date().toDateString()) {{
    if (!confirm('Already refreshed today at ' + _gen.toLocaleTimeString() + '. Rebuild anyway?')) return;
  }}
  _refreshBtn.disabled = true;
  _setStatus('Queuing...');
  google.script.run
    .withSuccessHandler(function(res) {{
      if (!res) {{ _setStatus('No response'); _refreshBtn.disabled = false; return; }}
      if (res.status === 'cooldown') {{
        _setStatus('Cooldown until ' + new Date(res.nextAllowed).toLocaleTimeString());
        _refreshBtn.disabled = false;
        return;
      }}
      _setStatus('Rebuilding on GitHub Actions (~2–3 min)...');
      _pollUntilNew(GENERATED_AT);
    }})
    .withFailureHandler(function(err) {{
      _setStatus('Error: ' + (err && err.message ? err.message : err));
      _refreshBtn.disabled = false;
    }})
    .triggerRefresh();
}};

function _pollUntilNew(oldGen) {{
  const started = Date.now();
  const iv = setInterval(function() {{
    if (Date.now() - started > 10 * 60 * 1000) {{
      clearInterval(iv);
      _setStatus('Timed out — reload manually.');
      _refreshBtn.disabled = false;
      return;
    }}
    google.script.run.withSuccessHandler(function(s) {{
      if (s && s.generatedAt && s.generatedAt !== oldGen) {{
        clearInterval(iv);
        _setStatus('New data ready — reloading...');
        setTimeout(function() {{ location.reload(); }}, 800);
      }}
    }}).getStatus();
  }}, 15000);
}}

updateToOptions();
</script>
</body>
</html>"""
    return html


def main():
    merged_closed, merged_all = load_data()
    print(f"Closed deals: {len(merged_closed)}, All deals: {len(merged_all)}")

    print("Computing conversions (closed)...")
    data_closed, current_q_label, pacing_days = compute_all(merged_closed)
    print("Computing conversions (all)...")
    data_all, _, _ = compute_all(merged_all)
    print(f"Current quarter: {current_q_label}, pacing: {pacing_days} days (up to yesterday)")

    print("Computing raw deal data...")
    raw_closed = compute_raw_data(merged_closed)
    raw_all = compute_raw_data(merged_all)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    html = build_html(data_closed, data_all, current_q_label, pacing_days, raw_closed, raw_all, generated_at)
    output_path = os.path.join(FOLDER, "conversion_chart.html")
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
