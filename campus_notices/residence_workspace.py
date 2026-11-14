"""Prepare private, source-linked tracing workspaces for every residence building.

Text positions identify labels, never doorways. No corridor, metric scale, access
permission or elevator stop is inferred from those positions.
"""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from campus_routing.indoor import IndoorMap

from .cache import atomic_json


def building_identity(name):
    name = re.sub(r"\s+(?:hall|house)$", "", name.strip(), flags=re.I)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return "brown-house" if slug == "brown" else slug


def source_floors(record):
    labels = list(record.get("floors", []))
    if not labels:
        explicit = record.get("extracted", {}).get("floor_label")
        if explicit:
            labels = [explicit]
    # Ground is deliberately not equated to basement or floor 1.
    return list(dict.fromkeys(str(int(x)) if x.isdigit() else x.lower() for x in labels))


def extract_pages(path, render_dir):
    import pymupdf

    pages = []
    with pymupdf.open(path) as document:
        for index, page in enumerate(document):
            image_path = render_dir / f"page-{index + 1}.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(image_path)
            candidates = []
            for x0, y0, x1, y1, word, *_ in page.get_text("words"):
                # Unlike the older block extraction, two labels in a block keep
                # distinct positions. The reviewer still excludes legends/title blocks.
                if re.fullmatch(r"(?:-\d{2}[A-Z]?|\d{3,4}[A-Z]?)", word.upper()):
                    candidates.append(
                        dict(
                            label=word.upper(),
                            x=(x0 + x1) / 2,
                            y=(y0 + y1) / 2,
                            bounds=[x0, y0, x1, y1],
                            review_status="label_only",
                        )
                    )
            text = page.get_text()
            pages.append(
                dict(
                    page=index + 1,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    coordinate_system="pdf_points",
                    rendered_path=str(image_path),
                    render_scale=1.5,
                    room_label_candidates=candidates,
                    explicit_elevator_text=bool(re.search(r"\b(?:ELEVATOR|LIFT)\b", text, re.I)),
                    marked_not_to_scale=bool(re.search(r"not\s+to\s+scale", text, re.I)),
                )
            )
    return pages


def prepare_workspaces(manifest_path: Path, output_dir: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for record in manifest["records"]:
        groups[(record["area"], building_identity(record["building"]))].append(record)
    index = []
    for (area, identity), records in sorted(groups.items()):
        folder = output_dir / identity
        sources, plans, floors, seen_hashes = [], [], {}, set()
        issues = []
        for record in records:
            local = Path(record["local_path"])
            content = local.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != record["sha256"]:
                raise ValueError(f"Plan checksum changed: {record['name']}")
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            sid = "plan-" + digest[:20]
            labels = source_floors(record)
            if not labels:
                issues.append(dict(code="floor_unknown", source_id=sid))
            sources.append(
                dict(
                    id=sid,
                    url=manifest["site"]
                    + "/_api/web/GetFileByServerRelativeUrl(@p)/$value?@p="
                    + quote("'" + record["server_relative_url"] + "'", safe=""),
                    edition=record["name"] + "; source revision must be reviewed",
                    observed_at=manifest["observed_at"],
                )
            )
            pages = extract_pages(local, folder / "plans" / sid)
            plans.append(
                dict(
                    source_id=sid,
                    name=record["name"],
                    sha256=digest,
                    modified=record.get("modified"),
                    floors=labels,
                    pages=pages,
                )
            )
            for label in labels:
                floors.setdefault(
                    label,
                    dict(
                        id=label,
                        label=label,
                        coordinate_system="image_pixels",
                        source_id=sid,
                    ),
                )
            if len(labels) > 1:
                issues.append(dict(code="grouped_floor_template", source_id=sid, floors=labels))
            if len(pages) > 1:
                issues.append(dict(code="page_to_floor_mapping_required", source_id=sid))
        name = records[0]["building"]
        raw = dict(
            building_id=identity,
            name=name,
            status="draft",
            sources=sources,
            floors=list(floors.values()),
            nodes=[],
            edges=[],
            assets=[],
            portals=[],
            review_notes="Source preparation only. Trace doorways, suites, corridors, "
            "scale, resident access, elevator stops and outdoor connections before review.",
        )
        map_path = folder / "map.json"
        if floors and not map_path.exists():
            atomic_json(map_path, IndoorMap.model_validate(raw).model_dump(mode="json"))
        review_path = folder / "review.json"
        if not review_path.exists():
            atomic_json(
                review_path,
                dict(
                    building_id=identity,
                    checks={
                        key: False
                        for key in (
                            "floor_page_mapping",
                            "doorways_and_suite_connections",
                            "corridors",
                            "scale_and_distances",
                            "resident_access",
                            "elevator_stops",
                            "entrance_alignment",
                            "outdoor_portal",
                            "closure_asset_ids",
                        )
                    },
                    notes="",
                    reviewed_by=None,
                ),
            )
        evidence = dict(
            building_id=identity,
            area=area,
            aliases=sorted({r["building"] for r in records}),
            observed_at=manifest["observed_at"],
            plans=plans,
            issues=issues,
            routing_eligible=False,
            note="Label positions are PDF points; multiply by render_scale for PNG. "
            "A label is not a room threshold. Grouped templates need floor review.",
        )
        # Keep the existing hand-built Brown traces discoverable without replacing
        # them or treating their approximate links as reviewed geometry.
        candidates = []
        for candidate in sorted((manifest_path.parent / "traces").glob(identity + "*.json")):
            data = IndoorMap.model_validate_json(candidate.read_text(encoding="utf-8"))
            candidates.append(
                dict(
                    path=str(candidate),
                    status=data.status,
                    nodes=len(data.nodes),
                    edges=len(data.edges),
                    review_notes=data.review_notes,
                )
            )
        evidence["existing_traces"] = candidates
        atomic_json(folder / "evidence.json", evidence)
        index.append(
            dict(
                building_id=identity,
                area=area,
                aliases=evidence["aliases"],
                plan_count=len(plans),
                floor_count=len(floors),
                evidence_path=str(folder / "evidence.json"),
                map_path=str(map_path) if floors else None,
                review_path=str(review_path),
                status="needs_topology_review",
                routing_eligible=False,
                issues=issues,
            )
        )
    result = dict(
        observed_at=manifest["observed_at"],
        source_folder_count=len({(r["area"], r["building"]) for r in manifest["records"]}),
        building_count=len(index),
        buildings=index,
    )
    atomic_json(output_dir / "index.json", result)
    return result
