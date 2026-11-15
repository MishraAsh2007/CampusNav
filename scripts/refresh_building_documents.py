"""Collect official building documents, including Chapel and Goodell floor references."""

from pathlib import Path

from campus_notices.building_documents import collect


def main():
    payload = collect(Path(__file__).resolve().parents[1])
    for name, source in payload["sources"].items():
        print(name, source["mode"])
    print("Building documents:", len(payload["records"]), "(source references, not route maps)")


if __name__ == "__main__":
    main()
