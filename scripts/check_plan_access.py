"""Read-only check of saved UMass session access; never logs cookies or passwords."""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from campus_notices.cache import atomic_json
from campus_notices.residence_plans import ROOT_FOLDER, SITE, _folder_url, _FreshSharePointClient
from campus_notices.sharepoint import read_session

ROOT = Path(__file__).resolve().parents[1]


def main():
    from playwright.sync_api import sync_playwright

    state, agent = read_session(ROOT / "data/private/sharepoint-session.json", datetime.now(UTC))
    with sync_playwright() as playwright:
        client = _FreshSharePointClient(playwright, state, agent)
        response = client.get(
            _folder_url(SITE, ROOT_FOLDER) + "?$expand=Folders,Files",
            headers={"Accept": "application/json;odata=verbose"},
            fail_on_status_code=False,
            timeout=30000,
        )
        result = dict(site=SITE, checked_at=datetime.now(UTC).isoformat(), status=response.status)
        if response.status == 200:
            payload = response.json().get("d", {})
            result["folders"] = [
                r.get("Name") for r in payload.get("Folders", {}).get("results", [])
            ]
        result["plan_searches"] = []
        for building in ("Integrative Learning Center", "Du Bois Library"):
            query = (
                f'"{building}" AND (Title:floor* OR Title:plan* OR Title:manual*) AND FileType:pdf'
            )
            url = (
                SITE
                + "/_api/search/query?"
                + urlencode(
                    {
                        "querytext": "'" + query + "'",
                        "rowlimit": "20",
                        "selectproperties": "'Title,Path'",
                        "trimduplicates": "true",
                    }
                )
            )
            search = client.get(
                url,
                headers={"Accept": "application/json;odata=verbose"},
                fail_on_status_code=False,
                timeout=30000,
            )
            item = dict(building=building, status=search.status, matches=[])
            if search.status == 200:
                body = search.json().get("d", {}).get("query", {})
                rows = (
                    body.get("PrimaryQueryResult", {})
                    .get("RelevantResults", {})
                    .get("Table", {})
                    .get("Rows", {})
                    .get("results", [])
                )
                for row in rows:
                    cells = {
                        c.get("Key"): c.get("Value")
                        for c in row.get("Cells", {}).get("results", [])
                    }
                    item["matches"].append(dict(title=cells.get("Title"), path=cells.get("Path")))
            result["plan_searches"].append(item)
        atomic_json(ROOT / "data/private/residence_floorplans/access-check.json", result)
        print("Residence folder HTTP status:", result["status"])
        for search in result["plan_searches"]:
            print(
                search["building"],
                "search HTTP",
                search["status"],
                "candidate documents:",
                len(search["matches"]),
            )
        print("Private details: data/private/residence_floorplans/access-check.json")


if __name__ == "__main__":
    main()
