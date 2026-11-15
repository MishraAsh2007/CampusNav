"""Collect central-building plan images, PDFs and official gallery directions."""

from pathlib import Path

from campus_notices.central_plans import collect_sources


def main():
    root = Path(__file__).resolve().parents[1]
    payload = collect_sources(root / ".cache/central-plans")
    for key, status in payload["sources"].items():
        print(key, status["mode"])
    print("Saved", len(payload["records"]), "plan/direction references. Graphs unchanged.")


if __name__ == "__main__":
    main()
