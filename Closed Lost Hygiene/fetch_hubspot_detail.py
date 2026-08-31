"""
Fetches closed_lost_reason_detail for closed-lost deals via HubSpot Search API.
Writes deal_id + closed_lost_reason_detail to hubspot_closed_lost_details.json.
Handles pagination automatically.

Usage:
    export HUBSPOT_TOKEN="pat-na1-..."
    python3 fetch_hubspot_detail.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
API_URL = "https://api.hubapi.com/crm/v3/objects/deals/search"

# Closed-lost deals with a qualified date >= 2025-07-01 (Unix millis)
QUALIFIED_AFTER_MS = "1751328000000"

PROPERTIES = ["closed_lost_reason_detail"]

FOLDER = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(FOLDER, "hubspot_closed_lost_details.json")


def fetch_page(after: int) -> dict:
    body = {
        "filterGroups": [{
            "filters": [
                {"propertyName": "qualified_date", "operator": "GTE", "value": QUALIFIED_AFTER_MS},
                {"propertyName": "hs_is_closed_won", "operator": "EQ", "value": "false"},
                {"propertyName": "closed_lost_reason_detail", "operator": "HAS_PROPERTY"},
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
    if not HUBSPOT_TOKEN:
        sys.exit("Set HUBSPOT_TOKEN environment variable (HubSpot private app token)")

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
        for deal in results:
            all_results.append({
                "deal_id": deal["id"],
                "closed_lost_reason_detail": deal.get("properties", {}).get("closed_lost_reason_detail"),
            })
        print(f"  Page {page}: fetched {len(results)} (running total: {len(all_results)}/{total})")

        paging = data.get("paging") or {}
        nxt = paging.get("next") or {}
        after = nxt.get("after")
        if not after:
            break

        if len(all_results) >= 10000:
            print("Hit 10,000 record cap of HubSpot search API. Some deals may be missing.")
            break

        time.sleep(0.1)

    output = {"total": len(all_results), "results": all_results}
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {len(all_results)} deals to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
