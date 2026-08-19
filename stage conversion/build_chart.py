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
    OWNERS,
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

    fresh_path = os.path.join(FOLDER, "hubspot_deals.json")
    with open(fresh_path) as fh:
        data = _json.load(fh)
    raw = [Deal.from_raw(r, OWNERS) for r in data.get("results", [])]
    print(f"Loaded {len(raw)} deal records from hubspot_deals.json")

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
                       "owner", "team", "geo", "mega_source", "deal_source", "stage"]],
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
        qual = pd.to_datetime(entered["qualified_date"], utc=True, errors="coerce").dt.normalize()
        entered = entered[entered[from_stage].dt.normalize() >= qual].copy()
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
        paced_converted = pq["converted"] & (pq["to_days_from_q_start"] < pacing_days + 1)
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
                    "owner": row.get("owner", "") or "",
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
  *{{box-sizing:border-box}}
  body{{
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    margin:0;padding:0;background:#f9f9f7;color:#0b0b0b;
    font-size:14px;line-height:1.5;
    -webkit-font-smoothing:antialiased;
  }}
  .wrap{{max-width:1280px;margin:0 auto;padding:28px 32px 64px}}

  .hdr{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:24px}}
  .hdr h1{{font-size:20px;font-weight:700;letter-spacing:-.02em;margin:0 0 2px}}
  .hdr-meta{{font-size:12.5px;color:#898781}}
  .hdr-meta b{{color:#52514e;font-weight:600}}
  .refresh-bar{{display:flex;align-items:center;gap:8px;white-space:nowrap}}
  #last-refreshed{{font-size:12px;color:#898781}}
  #refresh-btn{{
    padding:5px 14px;border:1px solid #e1e0d9;border-radius:6px;
    background:#fcfcfb;color:#52514e;cursor:pointer;font:500 12px/1 system-ui,sans-serif;
    transition:.15s;
  }}
  #refresh-btn:hover:not(:disabled){{border-color:#2a78d6;color:#2a78d6;background:#f0f6ff}}
  #refresh-btn:disabled{{opacity:.45;cursor:not-allowed}}
  #refresh-status{{font-size:12px;color:#898781;font-style:italic}}

  .controls{{
    display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;
    padding:14px 16px;background:#fcfcfb;border:1px solid #e1e0d9;
    border-radius:8px;margin-bottom:20px;
  }}
  .ctrl{{display:flex;flex-direction:column;min-width:130px;position:relative}}
  .ctrl label{{
    font-size:10px;font-weight:700;color:#898781;
    margin-bottom:5px;text-transform:uppercase;letter-spacing:.06em;
    display:flex;align-items:center;
  }}
  select{{
    padding:7px 30px 7px 10px;border:1px solid #e1e0d9;border-radius:6px;
    font:13px/1.4 system-ui,sans-serif;color:#0b0b0b;background:#fff;
    cursor:pointer;appearance:none;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 10 10'%3E%3Cpath fill='%23898781' d='M5 7L1 3h8z'/%3E%3C/svg%3E");
    background-repeat:no-repeat;background-position:right 8px center;
    transition:.15s;
  }}
  select:focus{{outline:none;border-color:#2a78d6;box-shadow:0 0 0 2px rgba(42,120,214,.15)}}

  .chart-card{{
    background:#fcfcfb;border:1px solid #e1e0d9;border-radius:8px;
    padding:20px;margin-bottom:24px;
  }}
  .chart-card h2{{font-size:15px;font-weight:600;margin:0 0 2px;letter-spacing:-.01em}}
  .chart-card .subtitle{{font-size:12.5px;color:#898781;margin-bottom:12px}}
  #chart{{width:100%;height:420px}}
  #chart2{{width:100%;height:380px}}

  .info-i{{
    display:inline-flex;align-items:center;justify-content:center;
    width:14px;height:14px;border-radius:50%;background:#e1e0d9;
    color:#898781;font:italic 700 9px/1 Georgia,serif;cursor:help;
    margin-left:5px;position:relative;transition:.15s;
  }}
  .info-i:hover{{background:#2a78d6;color:#fff}}
  .info-i:hover .tip{{visibility:visible;opacity:1;transform:translateX(-50%) translateY(-4px)}}
  .tip{{
    visibility:hidden;opacity:0;transition:.15s;
    position:absolute;z-index:100;bottom:22px;left:50%;transform:translateX(-50%);
    width:300px;padding:10px 12px;background:#0b0b0b;color:#e1e0d9;
    border-radius:6px;font:400 11.5px/1.5 system-ui,sans-serif;
    text-align:left;text-transform:none;letter-spacing:normal;font-style:normal;
    box-shadow:0 8px 20px rgba(0,0,0,.25);
  }}
  .tip strong{{color:#fff}}.tip em{{color:#86b6ef;font-style:normal;font-weight:500}}
  .tip::after{{content:'';position:absolute;top:100%;left:50%;margin-left:-5px;border:5px solid transparent;border-top-color:#0b0b0b}}

  .raw-section{{margin-top:8px}}
  .raw-section h2{{font-size:15px;font-weight:600;margin:0 0 12px}}
  .raw-bar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}}
  #raw-filter{{
    padding:7px 12px;border:1px solid #e1e0d9;border-radius:6px;
    font:13px/1.4 system-ui,sans-serif;width:320px;background:#fff;transition:.15s;
  }}
  #raw-filter:focus{{outline:none;border-color:#2a78d6;box-shadow:0 0 0 2px rgba(42,120,214,.15)}}
  #raw-filter::placeholder{{color:#c3c2b7}}
  #raw-conv-filter{{font:13px/1.4 system-ui,sans-serif}}
  #deal-count-label{{font-size:12px;color:#898781;margin-left:auto}}
  .tbl-wrap{{
    background:#fcfcfb;border:1px solid #e1e0d9;border-radius:8px;
    overflow:auto;max-height:520px;
  }}
  #raw-table{{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}}
  #raw-table thead{{position:sticky;top:0;z-index:2}}
  #raw-table th{{
    background:#f4f4f1;color:#898781;padding:9px 12px;
    text-align:left;font-weight:600;font-size:10.5px;text-transform:uppercase;
    letter-spacing:.04em;border-bottom:1px solid #e1e0d9;
    cursor:pointer;user-select:none;white-space:nowrap;transition:.1s;
  }}
  #raw-table th:hover{{color:#2a78d6}}
  #raw-table th.sorted{{color:#2a78d6}}
  #raw-table th .sa{{font-size:8px;margin-left:3px;opacity:.4}}
  #raw-table th.sorted .sa{{opacity:1}}
  #raw-table td{{padding:7px 12px;border-bottom:1px solid #f0efec;color:#0b0b0b;white-space:nowrap}}
  #raw-table tbody tr:hover td{{background:#f4f4f1}}
  .cy{{color:#006300;font-weight:700}}
  .cn{{color:#d03b3b;font-weight:500}}

  .foot{{
    font-size:12px;color:#898781;margin-top:20px;padding:12px 16px;
    background:#fcfcfb;border:1px solid #e1e0d9;border-left:3px solid #2a78d6;
    border-radius:6px;line-height:1.6;
  }}
  .foot b{{color:#52514e}}
</style>
</head>
<body>
<div class="wrap">
<div class="hdr">
  <div>
    <h1>Stage Conversion Analysis</h1>
    <div class="hdr-meta">
      Pipeline = <b>Classic</b> &middot; Deal Type = <b>New Business</b> &middot; Qualified &ge; <b>2024-01-01</b>
    </div>
  </div>
  <div class="refresh-bar">
    <span id="last-refreshed"></span>
    <button id="refresh-btn">Refresh</button>
    <span id="refresh-status"></span>
  </div>
</div>

<div class="controls">
  <div class="ctrl">
    <label>From Stage</label>
    <select id="fromStage"></select>
  </div>
  <div class="ctrl">
    <label>To Stage</label>
    <select id="toStage"></select>
  </div>
  <div class="ctrl">
    <label>Metric</label>
    <select id="metric">
      <option value="arr">ARR</option>
      <option value="deals">Deal Count</option>
    </select>
  </div>
  <div class="ctrl">
    <label>Pacing <span class="info-i">i<span class="tip"><strong>Apples-to-apples pacing.</strong><br>Every quarter measured at <strong>day {pacing_days}</strong> (elapsed days in {current_q_label}).<br><br><strong>Cohort:</strong> deals entering <em>from-stage</em> in the first {pacing_days} days.<br><strong>Converted:</strong> of that cohort, reaching <em>to-stage</em> by day {pacing_days}.<br>Both bounds use the same cutoff.</span></span></label>
    <select id="pacing">
      <option value="paced">Paced (first {pacing_days} days)</option>
      <option value="full">Full Quarter</option>
    </select>
  </div>
  <div class="ctrl">
    <label>Deals</label>
    <select id="closedFilter">
      <option value="closed">Closed Only</option>
      <option value="all">All Deals</option>
    </select>
  </div>
  <div class="ctrl">
    <label>Breakdown</label>
    <select id="breakdown">
      <option value="none">None</option>
      <option value="team">Team</option>
      <option value="geo">Geo</option>
      <option value="mega_source">Mega Source</option>
    </select>
  </div>
</div>

<div class="chart-card">
  <h2 id="chart-title"></h2>
  <div class="subtitle" id="chart-sub"></div>
  <div id="chart"></div>
</div>

<div class="chart-card">
  <h2>Stage &rarr; Closed Won</h2>
  <div class="subtitle">For each stage, what % of deals that entered it in a given quarter went on to close won?</div>
  <div id="chart2"></div>
</div>

<div class="raw-section">
  <h2>Deal-Level Data</h2>
  <div class="raw-bar">
    <input type="text" id="raw-filter" placeholder="Search deals, owners, teams...">
    <select id="raw-conv-filter">
      <option value="all">All</option>
      <option value="yes">Converted</option>
      <option value="no">Not Converted</option>
    </select>
    <span id="deal-count-label"></span>
  </div>
  <div class="tbl-wrap">
    <table id="raw-table"><thead></thead><tbody></tbody></table>
  </div>
</div>

<div class="foot">
  <b>Pacing (day {pacing_days}):</b> cohort = deals entering from-stage in the first {pacing_days} days of the quarter;
  converted = of that cohort, reached to-stage by day {pacing_days} of the same quarter.
  Matches elapsed time in {current_q_label} (through yesterday).
</div>
</div>

<script>
const STAGES = {stages_json};
const DATA_CLOSED = {data_closed_json};
const DATA_ALL = {data_all_json};
const RAW_CLOSED = {raw_closed_json};
const RAW_ALL = {raw_all_json};
const PACING_DAYS = {pacing_days};
const GENERATED_AT = "{generated_at}";
const COLORS = ['#2a78d6','#eb6834','#1baf7a','#eda100','#e87ba4','#008300'];
const TARGETS = {{
  "Demo / Presentation|Business Validation": 70,
  "Formal Pilot|Business Case Confirmation": 85,
  "Business Case Confirmation|Negotiation / Legal": 80,
  "Negotiation / Legal|Closed Won": 90,
}};
const PLOTLY_LAYOUT = {{
  font: {{ family: 'system-ui, -apple-system, sans-serif', size: 12, color: '#52514e' }},
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  margin: {{ t: 8, b: 52, l: 48, r: 16 }},
  hovermode: 'x unified',
  xaxis: {{
    tickangle: -45, tickfont: {{ size: 11, color: '#898781' }},
    gridcolor: '#e1e0d9', gridwidth: 1, zeroline: false,
    linecolor: '#c3c2b7', linewidth: 1,
  }},
  yaxis: {{
    title: {{ text: 'Conversion %', font: {{ size: 11, color: '#898781' }} }},
    rangemode: 'tozero', ticksuffix: '%',
    tickfont: {{ size: 11, color: '#898781' }},
    gridcolor: '#e1e0d9', gridwidth: 1, zeroline: false,
    linecolor: '#c3c2b7', linewidth: 1,
  }},
  legend: {{ orientation: 'h', y: -0.22, font: {{ size: 11 }} }},
}};
const PCFG = {{ displayModeBar: false, responsive: true }};

function fmtK(n) {{
  if (n >= 1e6) return '$' + (n/1e6).toFixed(1) + 'M';
  if (n >= 1e3) return '$' + (n/1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString();
}}

const fromSelect = document.getElementById('fromStage');
const toSelect = document.getElementById('toStage');
const metricSelect = document.getElementById('metric');
const pacingSelect = document.getElementById('pacing');
const closedFilter = document.getElementById('closedFilter');
const breakdownSelect = document.getElementById('breakdown');

STAGES.slice(0, -1).forEach(function(s, i) {{
  const opt = document.createElement('option');
  opt.value = s; opt.text = s;
  if (i === 0) opt.selected = true;
  fromSelect.appendChild(opt);
}});

function updateToOptions() {{
  const fromIdx = STAGES.indexOf(fromSelect.value);
  toSelect.innerHTML = '';
  STAGES.slice(fromIdx + 1).forEach(function(s, i) {{
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

  const brkLabel = breakdown === 'none' ? '' : ' by ' + {{team:'Team',geo:'Geo',mega_source:'Mega Source'}}[breakdown];
  document.getElementById('chart-title').textContent = from + ' → ' + to + brkLabel;
  document.getElementById('chart-sub').textContent =
    'Of deals entering ' + from + ' each quarter, what % reached ' + to + '?' +
    (pacing === 'paced' ? '  ·  Paced at day ' + PACING_DAYS : '');

  if (!DATA[key] || !DATA[key][breakdown]) {{
    Plotly.react('chart', [], Object.assign({{}}, PLOTLY_LAYOUT, {{
      annotations: [{{text: 'No data for this combination', showarrow: false, font: {{size: 14, color: '#898781'}}}}],
      xaxis: {{visible: false}}, yaxis: {{visible: false}}
    }}), PCFG);
    updateRawTable(from, to, pacing, closed);
    return;
  }}

  const dimData = DATA[key][breakdown];
  const traces = [];
  const groups = Object.keys(dimData).sort();

  groups.forEach(function(groupName, idx) {{
    const series = dimData[groupName][seriesKey];
    if (!series || series.length === 0) return;

    const x = series.map(function(d) {{ return d.quarter; }});
    const y = series.map(function(d) {{ return d.rate; }});
    const hoverText = series.map(function(d) {{
      const pct = d.rate !== null ? d.rate.toFixed(1) + '%' : 'N/A';
      if (metric === 'deals') return '<b>' + pct + '</b>  ' + groupName + '  (' + d.numerator + '/' + d.denominator + ')';
      return '<b>' + pct + '</b>  ' + groupName + '  (' + fmtK(d.numerator) + '/' + fmtK(d.denominator) + ')';
    }});

    traces.push({{
      x: x, y: y,
      type: 'scatter',
      mode: groups.length === 1 ? 'lines+markers+text' : 'lines+markers',
      name: groupName,
      text: groups.length === 1 ? y.map(function(v) {{ return v !== null ? v.toFixed(1) + '%' : ''; }}) : undefined,
      textposition: 'top center',
      textfont: {{ size: 11, color: '#52514e' }},
      hovertext: hoverText,
      hoverinfo: 'text',
      line: {{ color: COLORS[idx % COLORS.length], width: 2, shape: 'spline', smoothing: 0.3 }},
      marker: {{ size: 8, line: {{ color: '#fcfcfb', width: 2 }} }},
    }});
  }});

  const targetKey = from + '|' + to;
  const target = (
    metric === 'arr' && pacing === 'full' && closed === 'closed'
    && breakdown === 'none' && TARGETS[targetKey] !== undefined
  ) ? TARGETS[targetKey] : null;

  if (target !== null && traces.length > 0) {{
    traces.push({{
      x: traces[0].x,
      y: traces[0].x.map(function() {{ return target; }}),
      type: 'scatter', mode: 'lines',
      name: 'Target ' + target + '%',
      line: {{ color: '#d03b3b', width: 2, dash: 'dash' }},
      hovertext: traces[0].x.map(function() {{ return '<b>Target: ' + target + '%</b>'; }}),
      hoverinfo: 'text',
    }});
  }}

  Plotly.react('chart', traces, Object.assign({{}}, PLOTLY_LAYOUT, {{
    showlegend: groups.length > 1 || target !== null,
  }}), PCFG);
  updateRawTable(from, to, pacing, closed);
  updateChart2();
}}

function updateChart2() {{
  const metric = metricSelect.value;
  const pacing = pacingSelect.value;
  const closed = closedFilter.value;
  const DATA = closed === 'closed' ? DATA_CLOSED : DATA_ALL;
  const seriesKey = pacing + '_' + metric;
  const stagesForWon = STAGES.slice(0, -1);
  const traces2 = [];

  stagesForWon.forEach(function(stage, idx) {{
    const key = stage + '|Closed Won';
    if (!DATA[key] || !DATA[key]['none'] || !DATA[key]['none']['All']) return;
    const series = DATA[key]['none']['All'][seriesKey];
    if (!series || series.length === 0) return;

    traces2.push({{
      x: series.map(function(d) {{ return d.quarter; }}),
      y: series.map(function(d) {{ return d.rate; }}),
      type: 'scatter', mode: 'lines+markers',
      name: stage,
      hovertext: series.map(function(d) {{
        const pct = d.rate !== null ? d.rate.toFixed(1) + '%' : 'N/A';
        if (metric === 'deals') return '<b>' + pct + '</b>  ' + stage + '  (' + d.numerator + '/' + d.denominator + ')';
        return '<b>' + pct + '</b>  ' + stage + '  (' + fmtK(d.numerator) + '/' + fmtK(d.denominator) + ')';
      }}),
      hoverinfo: 'text',
      line: {{ color: COLORS[idx % COLORS.length], width: 2, shape: 'spline', smoothing: 0.3 }},
      marker: {{ size: 8, line: {{ color: '#fcfcfb', width: 2 }} }},
    }});
  }});

  Plotly.react('chart2', traces2, Object.assign({{}}, PLOTLY_LAYOUT, {{
    showlegend: true,
  }}), PCFG);
}}

let currentRecords = [];
let sortCol = null;
let sortAsc = true;

function updateRawTable(from, to, pacing, closed) {{
  const RAW = closed === 'closed' ? RAW_CLOSED : RAW_ALL;
  const key = from + '|' + to;
  let records = (RAW[key] || []).slice();

  if (pacing === 'paced') {{
    records = records.filter(function(r) {{ return r.days_in_q <= PACING_DAYS; }}).map(function(r) {{
      const pacedConv = r.converted && r.to_days_from_q_start !== null && r.to_days_from_q_start < PACING_DAYS + 1;
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
  const ft = document.getElementById('raw-filter').value.toLowerCase();
  const cf = document.getElementById('raw-conv-filter').value;

  if (ft) {{
    records = records.filter(function(r) {{
      return (r.deal_name||'').toLowerCase().indexOf(ft)>=0 ||
        (r.owner||'').toLowerCase().indexOf(ft)>=0 ||
        (r.team||'').toLowerCase().indexOf(ft)>=0 ||
        (r.geo||'').toLowerCase().indexOf(ft)>=0 ||
        (r.mega_source||'').toLowerCase().indexOf(ft)>=0 ||
        (r.current_stage||'').toLowerCase().indexOf(ft)>=0 ||
        (r.deal_source||'').toLowerCase().indexOf(ft)>=0;
    }});
  }}
  if (cf === 'yes') records = records.filter(function(r) {{ return r.converted; }});
  if (cf === 'no') records = records.filter(function(r) {{ return !r.converted; }});

  if (sortCol) {{
    records.sort(function(a, b) {{
      var va = a[sortCol], vb = b[sortCol];
      if (va == null) va = '';
      if (vb == null) vb = '';
      if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va;
      if (typeof va === 'boolean') {{ va = va ? 1 : 0; vb = vb ? 1 : 0; return sortAsc ? va - vb : vb - va; }}
      return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    }});
  }}

  var cols = [
    {{key:'deal_id',label:'Deal ID'}},{{key:'deal_name',label:'Deal'}},
    {{key:'owner',label:'Owner'}},{{key:'team',label:'Team'}},
    {{key:'geo',label:'Geo'}},{{key:'mega_source',label:'Source'}},
    {{key:'current_stage',label:'Stage'}},{{key:'amount',label:'Amount'}},
    {{key:'quarter',label:'Quarter'}},{{key:'from_date',label:'From'}},
    {{key:'to_date',label:'To'}},{{key:'converted',label:'Conv'}},
  ];

  var thead = document.querySelector('#raw-table thead');
  var tbody = document.querySelector('#raw-table tbody');

  thead.innerHTML = '<tr>' + cols.map(function(c) {{
    var arrow = sortCol === c.key ? (sortAsc ? '▲' : '▼') : '▴';
    var cls = sortCol === c.key ? ' class="sorted"' : '';
    return '<th' + cls + ' data-col="' + c.key + '">' + c.label + '<span class="sa">' + arrow + '</span></th>';
  }}).join('') + '</tr>';

  var esc = function(s) {{ var d = document.createElement('span'); d.textContent = s; return d.innerHTML; }};

  tbody.innerHTML = records.map(function(r) {{
    var cc = r.converted ? 'cy' : 'cn';
    var ct = r.converted ? '✓' : '✗';
    var amt = r.amount ? '$' + Math.round(r.amount).toLocaleString() : '—';
    return '<tr>'
      + '<td>' + esc(r.deal_id || '—') + '</td>'
      + '<td>' + esc(r.deal_name || '—') + '</td>'
      + '<td>' + esc(r.owner || '—') + '</td>'
      + '<td>' + esc(r.team || '—') + '</td>'
      + '<td>' + esc(r.geo || '—') + '</td>'
      + '<td>' + esc(r.mega_source || '—') + '</td>'
      + '<td>' + esc(r.current_stage || '—') + '</td>'
      + '<td>' + amt + '</td>'
      + '<td>' + r.quarter + '</td>'
      + '<td>' + (r.from_date || '—') + '</td>'
      + '<td>' + (r.to_date || '—') + '</td>'
      + '<td class="' + cc + '">' + ct + '</td>'
      + '</tr>';
  }}).join('');

  document.getElementById('deal-count-label').textContent = records.length + ' of ' + currentRecords.length + ' deals';

  thead.querySelectorAll('th').forEach(function(th) {{
    th.onclick = function() {{
      var col = th.dataset.col;
      if (sortCol === col) sortAsc = !sortAsc;
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

var _gen = new Date(GENERATED_AT);
var _lastRefreshedEl = document.getElementById('last-refreshed');
var _refreshBtn = document.getElementById('refresh-btn');
var _refreshStatusEl = document.getElementById('refresh-status');

function _fmtRel(dt) {{
  var m = Math.floor((Date.now() - dt.getTime()) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return m + 'm ago';
  var h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  return Math.floor(h / 24) + 'd ago';
}}
_lastRefreshedEl.textContent = _fmtRel(_gen);

function _setStatus(t) {{ _refreshStatusEl.textContent = t || ''; }}
function _isAppsScript() {{ return typeof google !== 'undefined' && google.script && google.script.run; }}

_refreshBtn.onclick = function() {{
  if (!_isAppsScript()) {{ _setStatus('Refresh only works when served by Apps Script.'); return; }}
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
        _refreshBtn.disabled = false; return;
      }}
      _setStatus('Rebuilding (~2–3 min)...');
      _pollUntilNew(GENERATED_AT);
    }})
    .withFailureHandler(function(err) {{
      _setStatus('Error: ' + (err && err.message ? err.message : err));
      _refreshBtn.disabled = false;
    }})
    .triggerRefresh();
}};

function _pollUntilNew(oldGen) {{
  var started = Date.now();
  var iv = setInterval(function() {{
    if (Date.now() - started > 600000) {{
      clearInterval(iv); _setStatus('Timed out — reload manually.'); _refreshBtn.disabled = false; return;
    }}
    google.script.run.withSuccessHandler(function(s) {{
      if (s && s.generatedAt && s.generatedAt !== oldGen) {{
        clearInterval(iv); _setStatus('New data ready — reloading...');
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
