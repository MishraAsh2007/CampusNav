import hashlib
import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

from campus_notices.cache import atomic_json
from campus_notices.residence_workspace import building_identity, prepare_workspaces, source_floors
from campus_routing.api import create_app
from campus_routing.engine import RoutingEngine
from campus_routing.places import LocationQuery, PlaceResolver
from scripts.demo_navigation import pilot_fixtures
from scripts.make_demo import make_demo_graph


def test_identity_merges_duplicate_hall_folders_without_merging_ground_and_basement():
    assert building_identity("Brown Hall") == "brown-house"
    assert building_identity("Wheeler") == building_identity("Wheeler Hall")
    assert source_floors(dict(floors=["02", "03", "02"])) == ["2", "3"]
    assert source_floors(dict(extracted=dict(floor_label="ground"))) == ["ground"]


def test_all_pages_are_extracted_duplicates_merge_and_manual_work_survives(tmp_path):
    source = tmp_path / "plan.pdf"
    with pymupdf.open() as doc:
        for _ in range(2):
            page = doc.new_page()
            page.insert_text((40, 220), "201 202")
        doc.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    record = dict(
        area="Central",
        building="Wheeler",
        name="plan.pdf",
        floors=["02", "03"],
        local_path=str(source),
        sha256=digest,
        server_relative_url="/plans/plan.pdf",
    )
    manifest = tmp_path / "manifest.json"
    atomic_json(
        manifest,
        dict(
            site="https://umass.sharepoint.com",
            observed_at="2026-11-14T12:00:00Z",
            records=[record, dict(record, building="Wheeler Hall")],
        ),
    )
    output = tmp_path / "workspaces"
    result = prepare_workspaces(manifest, output)
    assert result["building_count"] == 1 and result["source_folder_count"] == 2
    evidence = json.loads((output / "wheeler/evidence.json").read_text())
    assert len(evidence["plans"]) == 1 and len(evidence["plans"][0]["pages"]) == 2
    candidates = evidence["plans"][0]["pages"][0]["room_label_candidates"]
    assert candidates[0]["x"] != candidates[1]["x"]
    map_path = output / "wheeler/map.json"
    data = json.loads(map_path.read_text())
    assert not data["edges"] and not data["portals"]
    data["review_notes"] = "Human work in progress; retain these edits."
    atomic_json(map_path, data)
    prepare_workspaces(manifest, output)
    assert json.loads(map_path.read_text())["review_notes"] == data["review_notes"]
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        prepare_workspaces(manifest, output)


def test_guided_workflow_supports_imported_residences_and_keeps_drafts_unroutable(tmp_path):
    from campus_routing.indoor import IndoorMap

    raw = pilot_fixtures()["ilc"].model_dump(mode="json")
    raw.update(building_id="brown-house", name="Brown House", synthetic=False)
    data = IndoorMap.model_validate(raw)
    resolver = PlaceResolver({"brown-house": data}, {})
    resolved = resolver.resolve(LocationQuery(text="Brown House N211"))
    assert resolved["endpoint"]["building_id"] == "brown-house"
    atomic_json(tmp_path / "brown-house.json", raw)
    atomic_json(tmp_path / "public_floorplans.json", dict(assets=[]))
    with TestClient(create_app(engine=RoutingEngine(make_demo_graph()), indoor_dir=tmp_path)) as c:
        assert c.get("/navigation/catalog").status_code == 200
        response = c.post(
            "/navigation/arrive",
            json=dict(
                building_id="brown-house",
                portal_id="ilc-entrance",
                confirmed=True,
                continue_indoors=True,
                destination=dict(text="N211"),
                closures=[],
            ),
        )
        assert response.status_code == 200 and response.json()["status"] == "route_ready"
        raw["status"] = "draft"
        atomic_json(tmp_path / "brown-house.json", raw)
        response = c.post(
            "/navigation/arrive", json=dict(building_id="brown-house", portal_id="ilc-entrance")
        )
        assert response.json()["status"] == "coverage_unavailable"
