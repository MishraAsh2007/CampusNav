"""One collection workflow over the existing source adapters.

Collection does not promote source references into reviewed routing topology.
Only explicitly allowlisted datasets enter the combined files; authentication
state and environment files are never scanned or copied.
"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .cache import active_closures, atomic_json, read_snapshot, snapshot_status, writer_lock


@dataclass(frozen=True)
class Stage:
    id: str
    commands: tuple[tuple[str, ...], ...]
    artifacts: tuple[str, ...]
    derived: bool = False


def stages(rules_only=False, rebuild_graphs=False):
    parsing = ("--rules-only",) if rules_only else ()
    result = [
        Stage(
            "campus-map", (("scripts.fetch_residence_access",),), (".cache/residence-access.json",)
        ),
        Stage("outdoor-osm", (("scripts.fetch_residence_osm",),), (".cache/residence-map.osm",)),
        Stage(
            "residence-plans",
            (("scripts.refresh_residence_plans",),),
            ("data/private/residence_floorplans/manifest.json",),
        ),
        Stage(
            "building-catalogs",
            (
                (
                    "scripts.sync_campus_access",
                    "--gis-cache",
                    ".cache/residence-access.json",
                    "--allow-no-osm",
                ),
                ("scripts.build_residence_catalog",),
            ),
            (
                "data/buildings.json",
                "data/residence_buildings.json",
                "data/residence_assets.json",
                "data/location_registry.json",
            ),
            derived=True,
        ),
        Stage(
            "entrance-evidence",
            (("scripts.refresh_entrances",),),
            ("data/entrance_evidence.json", "data/buildings.json", "data/residence_buildings.json"),
        ),
        Stage(
            "indoor-references",
            (("scripts.refresh_indoor_sources",),),
            ("data/indoor_sources.json",),
        ),
        Stage(
            "library-elevators",
            (("scripts.refresh_library_elevators",),),
            ("data/library_elevator_sources.json",),
        ),
        Stage(
            "central-plans",
            (("scripts.refresh_central_sources",),),
            (".cache/central-plans/source-manifest.json",),
        ),
        Stage(
            "plan-search",
            (("scripts.search_central_plans",),),
            ("data/private/central-plan-search.json",),
        ),
        Stage(
            "building-documents",
            (("scripts.refresh_building_documents",),),
            ("data/private/building_documents/manifest.json",),
        ),
        Stage(
            "additional-wayfinding",
            (("scripts.build_additional_wayfinding",),),
            tuple(
                f"data/private/plan_wayfinding/{b}.json"
                for b in ("old-chapel", "north-d", "goodell")
            ),
            derived=True,
        ),
        Stage(
            "plan-portals",
            (("scripts.build_plan_portals",),),
            ("data/private/plan_wayfinding_portals.json",),
            derived=True,
        ),
        Stage(
            "official-notices",
            (("scripts.refresh_notices", *parsing),),
            ("data/official_snapshot.json",),
        ),
        Stage(
            "public-reports",
            (("scripts.refresh_reports", *parsing),),
            ("data/private/external_reports.json",),
        ),
    ]
    if rebuild_graphs:
        result.append(
            Stage(
                "outdoor-graphs",
                (
                    ("scripts.build_graph",),
                    (
                        "scripts.build_graph",
                        "--bbox",
                        "-72.541",
                        "42.381",
                        "-72.512",
                        "42.401",
                        "--output",
                        "data/umass-residences.graph.json",
                    ),
                ),
                ("data/umass.graph.json", "data/umass-residences.graph.json"),
                derived=True,
            )
        )
    return result


def read_json(root, relative, default=None):
    try:
        return json.loads((root / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def artifact_info(root, relative):
    path = root / relative
    if not path.is_file():
        return dict(path=relative, available=False)
    return dict(
        path=relative,
        available=True,
        bytes=path.stat().st_size,
        file_modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def inspect_stage(root, stage, *, exit_code, attempted_at, offline=False):
    artifacts = [artifact_info(root, p) for p in stage.artifacts]
    main = read_json(root, stage.artifacts[0], {})
    if not isinstance(main, dict):
        main = {}
    available = artifacts[0]["available"] and (bool(main) or stage.artifacts[0].endswith(".osm"))
    details = main.get("source_status") or main.get("sources") or {}
    if not isinstance(details, dict):
        details = {}
    # Whitelist metadata only: neither raw error messages nor private document
    # titles/paths or extracted social posts enter the public run report.
    sources = {}
    for key, value in details.items():
        if isinstance(value, dict):
            sources[key] = {
                k: value[k]
                for k in (
                    "mode",
                    "state",
                    "observed_at",
                    "attempted_at",
                    "last_success_at",
                    "count",
                    "fetched_count",
                    "error_type",
                )
                if k in value
            }
    observed = main.get("observed_at") or main.get("checked_at") or main.get("generated_at")
    modes = [v.get("mode", v.get("state")) for v in sources.values()]
    if modes and not any(
        m in ("live", "cache", "cached", "file", "spreadsheet_fallback") for m in modes
    ):
        available = False
    if main.get("synthetic") is True:
        available = False
    problems = {"cache", "cached", "error", "unavailable", "spreadsheet_fallback", "not_configured"}
    if not available:
        mode = "unavailable"
    elif offline or exit_code != 0:
        mode = "cache"
    elif any(m in problems for m in modes):
        mode = "partial" if "live" in modes else "cache"
    elif any(not r.get("search_complete", True) for r in main.get("searches", [])):
        mode = "partial"
    else:
        mode = "derived" if stage.derived else "live"
    return dict(
        id=stage.id,
        mode=mode,
        available=bool(available),
        attempted_at=None if offline else attempted_at,
        observed_at=observed,
        exit_code=exit_code,
        sources=sources,
        artifacts=artifacts,
    )


def execute_stage(stage, root, log_path):
    """No shell interpolation and no credentials on the command line."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with log_path.open("w", encoding="utf-8") as log:
        for command in stage.commands:
            try:
                result = subprocess.run(
                    [sys.executable, "-u", "-m", *command],
                    cwd=root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=900,
                    check=False,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                )
                failed = failed or result.returncode
            except subprocess.TimeoutExpired:
                log.write("\nSource stage timed out; consult last successful cache.\n")
                failed = 124
    return failed


def _indoor_maps(root, relative):
    result = []
    for path in sorted((root / relative).glob("*.json")):
        value = read_json(root, path.relative_to(root), {})
        if (
            isinstance(value, dict)
            and value.get("building_id")
            and "nodes" in value
            and ("edges" in value or "connections" in value)
        ):
            result.append(value)
    return result


def assemble(root, statuses, now):
    """Build public and private collections without changing individual API stores."""
    buildings = {}
    for name in ("data/residence_buildings.json", "data/buildings.json"):
        for row in (read_json(root, name, {}) or {}).get("buildings", []):
            buildings[row["id"]] = row
    snapshot = None
    try:
        snapshot = read_snapshot(root / "data/official_snapshot.json")
        if snapshot.synthetic:
            snapshot = None
    except (OSError, ValueError):
        pass
    indoor = read_json(root, "data/indoor_sources.json", {}) or {}
    central = read_json(root, ".cache/central-plans/source-manifest.json", {}) or {}
    reports = read_json(root, "data/private/external_reports.json", {}) or {}
    images = [
        {
            k: r[k]
            for k in ("id", "url", "sha256", "observed_at", "width", "height", "pages", "revision")
            if k in r
        }
        for r in central.get("records", [])
    ]
    public = dict(
        version=1,
        assembled_at=now.isoformat(),
        note="Collection snapshot, not a routing response. Source times remain separate from "
        "assembly time. Source references and public complaints do not become graph edges "
        "or closures automatically.",
        sources=statuses,
        buildings=list(buildings.values()),
        official_closures=(
            [c.model_dump(mode="json") for c in active_closures(snapshot, now)]
            if snapshot
            else None
        ),
        official_snapshot_generated_at=snapshot.generated_at.isoformat() if snapshot else None,
        official_feed_status=snapshot_status(root / "data/official_snapshot.json", now),
        indoor_references=indoor.get("records", []),
        library_elevator_sources=read_json(root, "data/library_elevator_sources.json"),
        entrance_evidence=read_json(root, "data/entrance_evidence.json"),
        central_plan_references=images,
        campus_map=read_json(root, ".cache/residence-access.json"),
        indoor_maps=_indoor_maps(root, "data/indoor"),
        outdoor_graphs=[
            artifact_info(root, p)
            for p in (
                "data/umass.graph.json",
                "data/umass-residences.graph.json",
                ".cache/elevations.json",
            )
        ],
        external_reports_summary=dict(
            count=len(reports.get("reports", [])), routing_eligible=False
        ),
    )
    private = dict(
        version=1,
        assembled_at=now.isoformat(),
        public_bundle="data/collected_data.json",
        residence_plans=read_json(root, "data/private/residence_floorplans/manifest.json"),
        plan_search=read_json(root, "data/private/central-plan-search.json"),
        external_reports=reports,
        local_community_reports=read_json(root, "data/private/community_reports.json"),
        drawing_wayfinding_maps=_indoor_maps(root, "data/private/plan_wayfinding"),
        drawing_portals=read_json(root, "data/private/plan_wayfinding_portals.json"),
        building_documents=read_json(root, "data/private/building_documents/manifest.json"),
        indoor_gap_research={
            key: read_json(root, "data/private/indoor_gap_research/" + name)
            for key, name in (
                ("alternate_oak_source", "oak-alternate-source.json"),
                ("targeted_plan_search", "targeted-search.json"),
            )
        },
    )
    return public, private


def run_all(
    root: Path,
    *,
    rules_only=False,
    offline=False,
    selected=None,
    rebuild_graphs=False,
    executor=execute_stage,
    progress=print,
    now=None,
):
    root = root.resolve()
    now = now or datetime.now(UTC)
    output = root / "data/scrape_status.json"
    pipeline = stages(rules_only, rebuild_graphs)
    if selected and set(selected) - {s.id for s in pipeline}:
        raise ValueError("Unknown collection stage")
    results = []
    with writer_lock(output):
        for stage in pipeline:
            if selected and stage.id not in selected:
                status = inspect_stage(root, stage, exit_code=None, attempted_at=None, offline=True)
                status["requested"] = False
                results.append(status)
                continue
            progress(f"{'Reading cache' if offline else 'Collecting'}: {stage.id}", flush=True)
            attempt = datetime.now(UTC).isoformat()
            code = None
            if not offline:
                try:
                    code = executor(
                        stage, root, root / "data/private/scrape_logs" / (stage.id + ".log")
                    )
                except Exception as exc:
                    # Continue independent families; never echo arbitrary exception text.
                    progress(f"{stage.id}: worker error ({type(exc).__name__})", flush=True)
                    code = 1
            status = inspect_stage(
                root, stage, exit_code=code, attempted_at=attempt, offline=offline
            )
            status["requested"] = True
            results.append(status)
            progress(f"  {stage.id}: {status['mode']}", flush=True)
        public, private = assemble(root, results, now)
        requested = [r for r in results if r["requested"]]
        complete = all(r["mode"] in ("live", "derived") for r in requested)
        available = any(r["available"] for r in requested)
        report = dict(
            version=1,
            assembled_at=now.isoformat(),
            status="ready" if complete else "partial" if available else "unavailable",
            offline=offline,
            stages=results,
            outputs=dict(
                public="data/collected_data.json", private="data/private/collected_data.json"
            ),
        )
        public["collection_status"] = report["status"]
        atomic_json(root / "data/collected_data.json", public)
        atomic_json(root / "data/private/collected_data.json", private)
        atomic_json(output, report)
        return report
