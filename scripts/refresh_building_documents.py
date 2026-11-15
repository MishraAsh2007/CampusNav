"""Collect the official project-linked building brochures using the saved UMass session."""

from pathlib import Path

from campus_notices.building_documents import collect


def main():
    payload = collect(Path(__file__).resolve().parents[1])
    for name, source in payload["sources"].items():
        print(name, source["mode"])
    print("Building brochures:", len(payload["records"]), "(source references, not route plans)")


if __name__ == "__main__":
    main()
