# Setup checklist — live-refresh dashboard

Follow these steps once, in order. Everything code-side is already committed.

## 1. Create the GitHub repo

```bash
cd "stage conversion"
git init -b main
git add .
git commit -m "Initial import of stage conversion dashboard"
gh repo create <owner>/<repo> --private --source=. --push
```

## 2. Set up the Apps Script project

1. https://script.google.com → New project → name it "Stage Conversion Dashboard".
2. Replace the default `Code.gs` contents with the contents of `appscript_Code.gs`.
   (No `index.html` needed — the script pulls the chart HTML from GitHub at runtime.)
3. Project Settings → Script Properties → **Add property** for each:

| Name | Value |
| --- | --- |
| `GITHUB_TOKEN` | A fine-grained PAT with `contents:read` + `actions:write` on the repo. Generate at https://github.com/settings/personal-access-tokens/new |
| `GITHUB_OWNER` | e.g. `guya-alt` |
| `GITHUB_REPO` | e.g. `snowflake-guy` |
| `CHART_PATH` | `stage conversion/conversion_chart.html` |
| `WORKFLOW_FILE` | `refresh-dashboard.yml` |

4. Deploy → New Deployment → "Web app":
   - Execute as: **Me**
   - Who has access: Anyone with the link (or restrict to your org)
5. Copy the `/exec` URL.

## 3. GitHub Actions secret

Repo → Settings → Secrets and variables → Actions → **New repository secret**:

| Name | Value |
| --- | --- |
| `SNOWFLAKE_CONNECTIONS_TOML` | Full contents of your local `~/.snowflake/connections.toml` (or just the `[default]` block). Include the header line `[default]`. |
| `HUBSPOT_TOKEN` | HubSpot private app token (starts with `pat-na1-…`). |

## 4. First run

Trigger the workflow to build and commit the chart HTML:

```bash
gh workflow run refresh-dashboard.yml
gh run watch
```

Or from the GitHub UI: Actions → Refresh Stage Conversion Dashboard → Run workflow.

Watch it complete (~2–3 min). Confirm:
- Snowflake step passes.
- Commit step pushes `conversion_chart.html` to the repo.

Open your Apps Script deployment URL — you should see the dashboard.

## 5. Smoke test the Refresh button

Click Refresh. Expected sequence:
1. "Already refreshed today at HH:MM — Rebuild anyway?" confirm dialog. Click OK.
2. Button shows "Queuing..." → "Rebuilding on GitHub Actions (~2–3 min)..."
3. In the GitHub Actions tab, a new run appears (event: `workflow_dispatch`).
4. When the workflow finishes and commits new HTML, reload the page to see updated data.

Click Refresh again immediately — you should get a "Cooldown until HH:MM" message.
Cooldown is 5 minutes, adjustable in `appscript_Code.gs` (`COOLDOWN_MS`).

## Troubleshooting

- **"GitHub API 401"** on trigger or page load → `GITHUB_TOKEN` is wrong or expired. Regenerate the PAT.
- **"GitHub API 404"** → check `GITHUB_OWNER`, `GITHUB_REPO`, `CHART_PATH`, `WORKFLOW_FILE` values.
- **Snowflake connection error** → verify `SNOWFLAKE_CONNECTIONS_TOML` is the full file contents including the `[default]` header, and that the key/user in it are still valid.
- **"Dashboard not available"** → the workflow hasn't committed `conversion_chart.html` yet. Check the Actions tab.
