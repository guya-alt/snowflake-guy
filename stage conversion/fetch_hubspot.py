"""
Fetches HubSpot deals via the Search API and writes to hubspot_deals.json.
Handles pagination automatically. Run this before build_chart.py to refresh data.

Usage:
    python3 fetch_hubspot.py
"""

import json
import os
import time
import urllib.request
import urllib.error

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
API_URL = "https://api.hubapi.com/crm/v3/objects/deals/search"

# Qualified date >= 2024-01-01 (Unix millis)
QUALIFIED_AFTER_MS = "1704067200000"

PROPERTIES = [
    "dealname", "qualified_date", "pipeline", "dealstage", "dealtype",
    "hubspot_team_id", "amount", "geography", "mega_source", "deal_source",
    "associations.company",
    "hs_v2_date_entered_982622489", "hs_v2_date_entered_65800978",
    "hs_v2_date_entered_65800980", "hs_v2_date_entered_65537604",
    "hs_v2_date_entered_22339760", "hs_v2_date_entered_contractsent",
    "hs_v2_date_entered_65537605", "hs_v2_date_entered_closedwon",
    "hs_v2_date_entered_closedlost",
    "hs_v2_date_entered_134696621", "hs_v2_date_entered_134696622",
    "hs_v2_date_entered_134696623", "hs_v2_date_entered_134696624",
    "hs_v2_date_entered_134696626", "hs_v2_date_entered_134696627",
    "hs_date_entered_982622489", "hs_date_entered_65800978",
    "hs_date_entered_65800980", "hs_date_entered_65537604",
    "hs_date_entered_22339760", "hs_date_entered_contractsent",
    "hs_date_entered_65537605", "hs_date_entered_closedwon",
    "hs_date_entered_closedlost",
    "hs_date_entered_134696621", "hs_date_entered_134696622",
    "hs_date_entered_134696623", "hs_date_entered_134696624",
    "hs_date_entered_134696626", "hs_date_entered_134696627",
]

FOLDER = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(FOLDER, "hubspot_deals.json")


def fetch_page(after: int) -> dict:
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "qualified_date", "operator": "GTE", "value": QUALIFIED_AFTER_MS}
            ]
        }],
        "properties": PROPERTIES,
        "limit": 200,
        "after": after,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {HUBSPOT_TOKEN}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    all_results = []
    after = 0
    total = None
    page = 0

    while True:
        page += 1
        try:
            data = fetch_page(after)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"HTTP {e.code}: {body}")
            raise

        if total is None:
            total = data.get("total")
            print(f"Total deals matching filter: {total}")

        results = data.get("results", [])
        all_results.extend(results)
        print(f"  Page {page}: fetched {len(results)} (running total: {len(all_results)}/{total})")

        # Follow cursor
        paging = data.get("paging") or {}
        nxt = paging.get("next") or {}
        after = nxt.get("after")
        if not after:
            break

        # HubSpot search API caps at 10,000 records
        if len(all_results) >= 10000:
            print("Hit 10,000 record cap of HubSpot search API. Some deals may be missing.")
            break

        # Gentle rate limiting
        time.sleep(0.1)

    output = {"total": len(all_results), "results": all_results}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {len(all_results)} deals to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
