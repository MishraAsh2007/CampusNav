"""Read-only, authenticated discovery of central-building drawing references.

Search results stay private and never become routing edges automatically.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from campus_notices.cache import atomic_json
from campus_notices.residence_plans import SITE, _FreshSharePointClient
from campus_notices.sharepoint import read_session

ROOT = Path(__file__).resolve().parents[1]
QUERIES = {
    "student-union": '"Student Union" AND (floor OR drawing OR elevator OR egress) '
    "AND (FileType:pdf OR FileType:dwg)",
    "campus-center": '"Campus Center" AND (floor OR drawing OR egress) '
    "AND (FileType:pdf OR FileType:dwg)",
    "library": '("Du Bois" OR "DuBois" OR "Tower Library") AND (elevator OR lift)',
}


def main():
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--building", action="append", choices=QUERIES)
    parser.add_argument(
        "--session", type=Path, default=ROOT / "data/private/sharepoint-session.json"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/private/central-plan-search.json"
    )
    args = parser.parse_args()
    state, agent = read_session(args.session, datetime.now(UTC))
    searches = []
    with sync_playwright() as playwright:
        client = _FreshSharePointClient(playwright, state, agent)
        for building in args.building or list(QUERIES):
            query = QUERIES[building]
            url = (
                SITE
                + "/_api/search/query?"
                + urlencode(
                    {
                        "querytext": "'" + query + "'",
                        "rowlimit": "500",
                        "selectproperties": "'Title,Path,LastModifiedTime,FileType'",
                        "trimduplicates": "true",
                    }
                )
            )
            response = client.get(
                url,
                headers={"Accept": "application/json;odata=verbose"},
                fail_on_status_code=False,
                timeout=30000,
            )
            if response.status != 200:
                raise SystemExit(
                    f"{building}: SharePoint HTTP {response.status}; previous search file retained."
                )
            relevant = response.json()["d"]["query"]["PrimaryQueryResult"]["RelevantResults"]
            matches = []
            for row in relevant["Table"]["Rows"]["results"]:
                cells = {c["Key"]: c.get("Value") for c in row["Cells"]["results"]}
                matches.append(
                    {k: cells.get(k) for k in ["Title", "Path", "LastModifiedTime", "FileType"]}
                )
            total = int(relevant["TotalRows"])
            searches.append(
                dict(
                    building_id=building,
                    query=query,
                    total_rows=total,
                    search_complete=total <= len(matches),
                    matches=matches,
                )
            )
            print(building, ":", len(matches), "references; total reported:", total)
    atomic_json(
        args.output,
        dict(checked_at=datetime.now(UTC).isoformat(), searches=searches, routing_eligible=False),
    )
    print("Private references saved:", args.output)
    print("Search is limited to indexed documents visible to this account, not all UMass plans.")


if __name__ == "__main__":
    main()
