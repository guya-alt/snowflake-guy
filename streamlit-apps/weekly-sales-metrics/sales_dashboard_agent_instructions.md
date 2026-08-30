# System Instructions for Dashboard Agent: Weekly Sales Metrics (v3)

## Purpose
This document outlines strict configuration, rendering, and interaction rules for building the Weekly Sales Metrics Dashboard. The agent must adhere to these constraints to ensure data consistency, professional formatting, and deep drill-down capabilities.

---

## 1. Global Visualization & Interaction Principles

### 1.1 Default Chart Configuration
* **Chart Type:** Every analytical metric must render as a **Line Chart** by default to explicitly show chronological trends.
* **Metadata Requirements:** Every single chart or visualization block MUST include:
  * **Title:** Clear, concise name of the metric (e.g., *Net New Pipeline Created ($)*).
  * **Subtitle:** Detailed context explaining exactly what is being measured and the timeframe (e.g., *Trailing average and YoY comparison of new opportunities generated in the last X days*).
* **Axis Labels:** No axis can remain unlabelled.
  * **X-Axis:** Temporal component (e.g., *Week Commencing*, *Month*, *Date*).
  * **Y-Axis:** Explicit unit of measurement (e.g., *Conversion Rate (%)*, *Pipeline Value ($ USD)*, *Count of Deals*).

### 1.2 Global Filtering Framework
* **Unified Scope:** All filters provided on the dashboard UI must act **globally**. Applying a filter must instantly slice data across all charts, graphs, and components simultaneously.
* **Required Global Filters:** Time Range, Mega Source/Channel (Inbound/Outbound/Partner), Geography/Territory, Customer Segment, Sales Motion (Land/Expand), and Team/Manager/Rep.

### 1.3 Data Formatting & Tooltips
* **Informative Tooltips:** Hovering over any data point must show a comprehensive, highly descriptive tooltip displaying the exact date/period, metric name, absolute value, and relevant contextual comparison (e.g., WoW % change).
* **ARR / Financial Formatting:** All monetary ARR values must use abbreviated currency notation based on magnitude:
  * Thousands: `$XXK` (e.g., `$300K`)
  * Millions: `$X.XM` (e.g., `$2.2M`)
* **Percentage Formatting:** All percentage and ratio values must be formatted to exactly one decimal place followed by the percentage symbol:
  * Format: `XX.X%` (e.g., `85.4%`, `12.0%`, `0.5%`).

### 1.4 Calendar & Date Conventions
* **Week Start:** The business and reporting week must strictly begin on **Monday** (e.g., any weekly aggregate trend line must anchor to Monday as day 1 of that period).
* **Date Format Structure:** All calendar dates displayed anywhere on the dashboard—including axis timelines, tooltip headers, and raw data drill-down rows—must adhere strictly to the **DD/M/YY** layout (e.g., `15/6/26` or `02/11/26`).

### 1.5 Chart Drill-Down Interactivity
* **Raw Data Drill-Down:** All charts must be interactive. Clicking on any data point, line segment, or trend vector must immediately open a filtered **Raw Data Table** containing the underlying records.
* **Table Columns:** The raw data table must display all relevant operational columns for auditability (e.g., *Opportunity Name, Owner, Account Name, ARR Value, Stage, Close Date, Source, and Region*).

---

## 2. Core Metrics Engine Configuration

### Section 1: Top-of-Funnel & Conversion
1. **Sign-Up to Meeting Ratio**
   * *Formula:* Total new signup companies / New meetings booked.
   * *Formatting:* `XX.X%`
   * *Breakdown Properties:* Mega Source, Geo, Segment.
2. **SDR Discovery Process Analysis**
   * *Formula:* Total discovery calls completed vs. Qualified opportunities advanced.
   * *Formatting:* `XX.X%`
   * *Breakdown Properties:* Mega Source, Creator (SDR/AE), Segment.
3. **Net New Pipeline Created ($)**
   * *Formula:* Total dollar value of new opportunities generated in last X days.
   * *Formatting:* ARR format (`$300K` / `$2.2M`).
   * *Trend:* Multi-line chart (Current performance vs. Trailing average line vs. YoY line).
   * *Breakdown Properties:* Motion (Expand vs. Land), Region, Segment, Representative.

### Section 2: Pipeline & Forecasting
4. **Weekly Pipeline Coverage Ratio**
   * *Formula:* Total active pipeline / Remaining quarterly sales target.
   * *Formatting:* `XX.X%` or decimal (e.g., `3.1x`).
   * *Breakdown Properties:* Territory, Segment, Product Line.
5. **Forecast Category - Net Flow (NewBiz)**
   * *Formula:* Weekly net dollar volume adjustments between stages.
   * *Formatting:* ARR format (`$300K` / `$2.2M`).
   * *Trend:* Line charts tracing net movement across Pipeline, Best Case, and Commit categories.
   * *Breakdown Properties:* Category Shift, Territory, Regional Manager.
6. **Sales Velocity**
   * *Formula:* `(Opportunities * Deal Value * Win Rate) / Sales Cycle Length`
   * *Formatting:* Combined speed metric represented as absolute currency velocity (ARR format).
   * *Breakdown Properties:* Territory, Segment, Product Line.

### Section 3: Deal Health & CRM Hygiene
7. **Stalled Deals**
   * *Formula:* Count/Value of active opportunities with no progression past threshold days.
   * *Formatting:* ARR format for value; integers for counts.
   * *Breakdown Properties:* Sales Stage, Forecast Category, Territory, Rep.
8. **Stage-to-Stage Deal Slippage & Duration**
   * *Formula:* Average days a deal sits in a single stage & count of deals pushing close dates out.
   * *Formatting:* Average days (1 decimal place) and counts. Emphasis on last week & last month of quarter.
   * *Breakdown Properties:* Territory Lens, Commit Status in last month, Sales Stage.
9. **CRM Hygiene**
   * *Formula:* % of top critical/field completions on active opportunities.
   * *Formatting:* `XX.X%`
   * *Breakdown Properties:* Sub-team, Manager, Individual Rep.

### Section 4: Revenue, Retention & Activity
10. **Win Rate**
    * *Formula:* Closed Won Deals / Total Closed Deals.
    * *Formatting:* `XX.X%`
    * *Breakdown Properties:* Mega Source, Geo, Segment.
11. **Early-Warning Churn & Risk Assessment**
    * *Formula:* Total ARR value of accounts triggering critical risk indicators (e.g., usage drop, missed QBRs).
    * *Formatting:* ARR format (`$300K` / `$2.2M`).
    * *Breakdown Properties:* AM/CSM Owner, Risk Trigger Category, Product Line.
12. **NRR Logo / ARR**
    * *Formula:* Net Revenue Retention measured both by logo retention and expansion ARR.
    * *Formatting:* `XX.X%`
    * *Breakdown Properties:* Customer Segment, Geography, Core Product.

### Section 5: Team Activity & Benchmarking
13. **Rep & Manager Calls**
    * *Formula:* Dynamic volume of high-impact coaching/alignment calls logged.
    * *Formatting:* Integer metrics.
    * *Breakdown Properties:* Manager, Territory, Representative.
14. **Rep Comparison to Team Average**
    * *Formula:* Individual rep score vs. Compiled team mean across key parameters.
    * *Trend:* Multi-line overlay tracking individual rep progression over time versus the shifting team baseline average.
    * *Comparative Vectors:* Open pipeline, conversion rate to won, total won, CRM hygiene, deal slippage/duration, stalled deals, and sales velocity. All values must respect global ARR/percentage formatting rules.

---

## 3. Implementation Verification Checklist
Before rendering, the agent must verify:
- [ ] Is every visualization formatted as a line chart by default?
- [ ] Do all charts contain a standalone Title and descriptive Subtitle?
- [ ] Are both X and Y axes explicitly named with descriptors and units?
- [ ] Do global dashboard filters successfully pass down parameter constraints to update every widget simultaneously?
- [ ] Do all tooltips display informative, deep context instead of raw standalone numbers?
- [ ] Are financial metrics utilizing condensed abbreviation (`$300K`, `$2.2M`)?
- [ ] Are percentage rates formatted strictly to one decimal place (`XX.X%`)?
- [ ] Is the start of the week locked to **Monday** globally across historical charts?
- [ ] Are all dates mapped out strictly in the format **DD/M/YY**?
- [ ] Does clicking any chart point reveal a granular, filtered raw data table showing all relevant background columns?