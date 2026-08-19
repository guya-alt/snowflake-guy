# Apps Script project

The Apps Script web app pulls `conversion_chart.html` directly from GitHub
at runtime — no clasp or push step needed.

## Setup

1. Paste `../appscript_Code.gs` into Code.gs in the Apps Script editor (one time).
2. Set the Script Properties listed in `../SETUP.md`.
3. Deploy as a web app.

The GitHub Actions workflow builds and commits the chart HTML to the repo.
Apps Script fetches it on each page load.
