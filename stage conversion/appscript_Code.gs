// Google Apps Script — serves the conversion chart by pulling the latest HTML
// from GitHub on each page load. No clasp needed.
//
// ═══ ONE-TIME SETUP ═══
// 1. In script.google.com, create a new project (or open existing).
// 2. Replace the default Code.gs with THIS file (no index.html needed).
// 3. Project Settings → Script Properties → set:
//      GITHUB_TOKEN    — fine-grained PAT with contents:read + actions:write
//      GITHUB_OWNER    — e.g. "guya-alt"
//      GITHUB_REPO     — e.g. "snowflake-guy"
//      CHART_PATH      — "stage conversion/conversion_chart.html"
//      WORKFLOW_FILE   — "refresh-dashboard.yml"
// 4. Deploy → New Deployment → "Web app" → Execute as: Me → Anyone with link.

const COOLDOWN_MS = 5 * 60 * 1000;

function _ghHeaders(accept) {
  return {
    Authorization: 'Bearer ' + PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN'),
    Accept: accept || 'application/vnd.github.raw',
    'X-GitHub-Api-Version': '2022-11-28',
  };
}

function _repoBase() {
  const p = PropertiesService.getScriptProperties();
  return 'https://api.github.com/repos/' + p.getProperty('GITHUB_OWNER') +
    '/' + p.getProperty('GITHUB_REPO');
}

function doGet() {
  const chartPath = PropertiesService.getScriptProperties()
    .getProperty('CHART_PATH') || 'stage conversion/conversion_chart.html';
  const url = _repoBase() + '/contents/' + encodeURIComponent(chartPath);
  const resp = UrlFetchApp.fetch(url, {
    headers: _ghHeaders('application/vnd.github.raw'),
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() >= 300) {
    return HtmlService.createHtmlOutput(
      '<h2>Dashboard not available</h2><p>GitHub API ' + resp.getResponseCode() +
      '. Run the refresh workflow to generate the chart.</p>'
    );
  }
  return HtmlService
    .createHtmlOutput(resp.getContentText())
    .setTitle('Stage Conversion Analysis')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function triggerRefresh() {
  const props = PropertiesService.getScriptProperties();
  const now = Date.now();
  const last = Number(props.getProperty('LAST_TRIGGER_AT') || 0);
  if (now - last < COOLDOWN_MS) {
    return {
      status: 'cooldown',
      nextAllowed: new Date(last + COOLDOWN_MS).toISOString(),
    };
  }

  const wf = props.getProperty('WORKFLOW_FILE');
  const url = _repoBase() + '/actions/workflows/' + wf + '/dispatches';
  const resp = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: _ghHeaders('application/vnd.github+json'),
    payload: JSON.stringify({ ref: 'main' }),
    muteHttpExceptions: true,
  });

  const code = resp.getResponseCode();
  if (code >= 300) {
    throw new Error('GitHub API ' + code + ': ' + resp.getContentText());
  }

  props.setProperty('LAST_TRIGGER_AT', String(now));
  return { status: 'queued', triggeredAt: new Date(now).toISOString() };
}

function getStatus() {
  const chartPath = PropertiesService.getScriptProperties()
    .getProperty('CHART_PATH') || 'stage conversion/conversion_chart.html';
  const url = _repoBase() + '/commits?path=' + encodeURIComponent(chartPath) + '&per_page=1';
  const resp = UrlFetchApp.fetch(url, {
    headers: _ghHeaders('application/vnd.github+json'),
    muteHttpExceptions: true,
  });
  if (resp.getResponseCode() >= 300) {
    return { generatedAt: null, lastTriggerAt: null };
  }
  const commits = JSON.parse(resp.getContentText());
  const lastCommit = commits.length ? commits[0].commit.committer.date : null;
  return {
    generatedAt: lastCommit,
    lastTriggerAt: PropertiesService.getScriptProperties().getProperty('LAST_TRIGGER_AT') || null,
  };
}
