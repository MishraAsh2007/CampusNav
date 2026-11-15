"""Check source-backed entrance matches for drawing-to-outdoor journey composition."""

from pathlib import Path

from campus_notices.plan_portals import collect


def main():
    result = collect(Path(__file__).resolve().parents[1])
    for portal in result.portals:
        print(portal.building_id, portal.id, "source-matched threshold; not field verified")
    for row in result.unresolved:
        print(row["building_id"], row["indoor_node_id"], "unresolved:", row["reason"])


if __name__ == "__main__":
    main()
