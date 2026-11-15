"""Run: python -m uvicorn campus_routing.api:app --reload"""

import json
import logging
import os
import re
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from campus_notices.cache import active_closures, read_snapshot, snapshot_status
from campus_notices.community import ReportStore, UserReport
from campus_notices.models import ExternalReport
from campus_notices.reports import active_reports, read_reports, reports_status

from .buildings import Place, TripRequest, choices, plan_trip, read_buildings
from .engine import RoutingEngine, RoutingError
from .indoor import IndoorEngine, IndoorRouteRequest, read_indoor
from .journey import JourneyRequest, plan_journey
from .models import Closure, RouteRequest, RouteResponse
from .navigation import ArrivalRequest, NavigationRequest, NavigationService
from .places import PILOT_BUILDINGS, LocationQuery, PlaceResolver, ResolveRequest
from .plan_wayfinding import PlanWayfindingMap, PlanWayfindingRequest, plan_directions

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def create_app(
    engine: RoutingEngine | None = None,
    graph_path: Path | None = None,
    official_path: Path | None = None,
    reports_path: Path | None = None,
    buildings_path: Path | None = None,
    community_path: Path | None = None,
    indoor_dir: Path | None = None,
    indoor_sources_path: Path | None = None,
    plan_wayfinding_dir: Path | None = None,
    data_app: FastAPI | None = None,
) -> FastAPI:
    bridge = None
    if data_app is not None:
        from .data_bridge import DataBridge

        bridge = DataBridge(data_app)
    path = graph_path or Path(os.getenv("ROUTING_GRAPH", ROOT / "data" / "umass.graph.json"))
    official = official_path or Path(
        os.getenv("OFFICIAL_CLOSURES_SNAPSHOT", ROOT / "data" / "official_snapshot.json")
    )
    reports = reports_path or Path(
        os.getenv(
            "EXTERNAL_REPORTS_SNAPSHOT",
            ROOT / "data/private/external_reports.json",
        )
    )
    building_file = buildings_path or Path(
        os.getenv("BUILDINGS_PATH", ROOT / "data/buildings.json")
    )
    community = ReportStore(community_path or ROOT / "data/private/community_reports.json")
    indoor_maps = indoor_dir or Path(os.getenv("INDOOR_MAPS_DIR", ROOT / "data/indoor"))
    indoor_sources = indoor_sources_path or ROOT / "data/indoor_sources.json"
    plan_dir = plan_wayfinding_dir or os.getenv("PLAN_WAYFINDING_DIR")

    def source_plan(building_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", building_id):
            raise HTTPException(422, detail="Invalid building ID")
        if not plan_dir:
            raise HTTPException(503, detail="Drawing wayfinding is not configured for this server.")
        try:
            return PlanWayfindingMap.model_validate_json(
                (Path(plan_dir) / (building_id + ".json")).read_text(encoding="utf-8")
            )
        except FileNotFoundError as error:
            raise HTTPException(
                404, detail="No drawing wayfinding pilot for this building."
            ) from error
        except (OSError, ValueError) as error:
            raise HTTPException(503, detail="Drawing wayfinding map failed validation.") from error

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            if data_app is not None:
                await stack.enter_async_context(data_app.router.lifespan_context(data_app))
            app.state.engine = engine
            if engine is None:
                try:
                    app.state.engine = RoutingEngine.from_file(path)
                except (OSError, ValueError, KeyError, TypeError):
                    logger.exception("Could not load routing graph from %s", path)
            yield

    app = FastAPI(
        title="UMass Campus Routing",
        version="0.1.0",
        lifespan=lifespan,
        description="Open POST /route and click Execute to run the prefilled campus example. "
        "The Responses section lists possible outcomes; your actual result appears "
        "under Server response after Execute. For a simpler test, open the [start page](/).",
        swagger_ui_parameters={"tryItOutEnabled": True},
    )
    origins = os.getenv(
        "ROUTING_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.strip() for s in origins.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=[
            "X-Closures-Stale",
            "X-Closures-Status",
            "X-Closures-Demo",
            "X-Reports-Stale",
        ],
    )

    def get_engine():
        current = getattr(app.state, "engine", None)
        if current is None:
            raise HTTPException(
                503,
                detail={
                    "code": "graph_unavailable",
                    "message": "Build the campus graph or set ROUTING_GRAPH=data/demo.graph.json.",
                },
            )
        return current

    @app.get("/backend", response_class=HTMLResponse, include_in_schema=False)
    def home():
        return Path(__file__).with_name("start.html").read_text(encoding="utf-8")

    def catalog():
        try:
            local = read_buildings(building_file)
            return bridge.catalog(local) if bridge is not None else local
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(
                503,
                detail={"message": "Building catalog unavailable. Run scripts.sync_campus_access."},
            ) from exc

    @app.get("/buildings", tags=["Campus navigation"])
    def buildings():
        return catalog()["buildings"]

    @app.get("/buildings/status", tags=["Campus navigation"])
    def building_status():
        data = catalog()
        return {k: v for k, v in data.items() if k != "buildings"}

    @app.post("/plan", tags=["Campus navigation"])
    def plan(request: TripRequest):
        try:
            result = plan_trip(get_engine(), catalog(), current_closures(request))
            if bridge is not None and bridge.official_status()["stale"]:
                result["notes"].append("Official closure data is stale or unavailable.")
            return result
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.get("/closures/status", tags=["Campus navigation"])
    def closure_status():
        if bridge is not None:
            return bridge.official_status()
        status = snapshot_status(official)
        status["community_count"] = len(community.active())
        status["community_storage"] = "local_file"
        return status

    def official_records(*, scheduled=False):
        if bridge is not None:
            return bridge.official(scheduled=scheduled)
        try:
            snapshot = read_snapshot(official)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                503,
                detail={"message": "Official notice cache unavailable; run refresh-notices.cmd."},
            ) from exc
        now = datetime.now(UTC)
        data = catalog()
        by_lift = {lift["id"]: b for b in data["buildings"] for lift in b["elevators"]["list"]}
        rows = []
        for closure in snapshot.closures:
            if closure.end_time and closure.end_time <= now:
                continue
            if not scheduled and closure.start_time > now:
                continue
            row = closure.model_dump(mode="json")
            b = by_lift.get(closure.location_id)
            row.update(
                title=f"{b['name'] if b else 'Campus'}: {closure.type} {closure.status}",
                building_name=b["name"] if b else None,
                building_id=b["id"] if b else closure.building_id,
                connector_id=closure.asset_id or closure.location_id,
                confirmations_count=0,
                scheduled=closure.start_time > now,
            )
            rows.append(row)
        return rows

    @app.get("/closures", tags=["Campus navigation"])
    def closures(response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Closures-Stale"] = str(closure_status()["stale"]).lower()
        return bridge.active() if bridge is not None else official_records() + community.active()

    @app.get("/notices", tags=["Campus navigation"])
    def scheduled_notices():
        return official_records(scheduled=True)

    @app.post("/reports", status_code=201, tags=["Campus navigation"])
    def submit_report(request: UserReport):
        if request.asset_id or request.floor_id:
            indoor = indoor_map(request.building_id)
            if indoor.status != "reviewed" or indoor.synthetic:
                raise HTTPException(
                    409, detail={"message": "This indoor map is not published for routing."}
                )
            if request.floor_id and request.floor_id not in {f.id for f in indoor.floors}:
                raise HTTPException(422, detail={"message": "Unknown floor for this building."})
            if request.asset_id:
                asset = next((a for a in indoor.assets if a.id == request.asset_id), None)
                if asset is None or asset.kind != request.type:
                    raise HTTPException(
                        422, detail={"message": "Select a mapped indoor asset of this type."}
                    )
                if asset.position:
                    request = request.model_copy(update=asset.position.model_dump())
        if request.asset_id and request.connector_id and request.connector_id != request.asset_id:
            raise HTTPException(422, detail={"message": "Conflicting asset and connector IDs."})
        if request.connector_id and not request.asset_id:
            lift = next(
                (
                    elevator
                    for b in catalog()["buildings"]
                    for elevator in b["elevators"]["list"]
                    if elevator["id"] == request.connector_id
                ),
                None,
            )
            if not lift or request.type != "elevator":
                raise HTTPException(
                    422, detail={"message": "Select a mapped elevator or use a map pin."}
                )
            request = request.model_copy(update={"lat": lift["lat"], "lng": lift["lng"]})
        try:
            return bridge.submit(request) if bridge is not None else community.submit(request)
        except ValueError:
            raise HTTPException(422, detail={"message": "The report does not fit the data contract."}) from None

    @app.post("/reports/{report_id}/confirm", tags=["Campus navigation"])
    def confirm_report(report_id: str):
        if bridge is not None:
            confirmed = bridge.app.state.closures.confirm(report_id)
            if confirmed is None:
                raise HTTPException(404, "This community report has expired or was resolved.")
            return bridge.display_closure(confirmed)
        try:
            return community.confirm(report_id)
        except KeyError as exc:
            raise HTTPException(
                404, detail={"message": "This community report has expired or was resolved."}
            ) from exc

    @app.get("/health")
    def health():
        current = get_engine()
        return {
            "status": "ok",
            "graph_source": current.graph.graph.get("source"),
            "synthetic": current.graph.graph.get("synthetic", False),
            "nodes": current.graph.number_of_nodes(),
            "edges": current.graph.number_of_edges(),
            "demo": demo_enabled(),
            "routes": ["/plan", "/navigation/plan", "/navigation/arrive", "/indoor/status"],
            "storage_mode": bridge.app.state.storage_mode if bridge is not None else "local_files",
        }

    def demo_enabled():
        return (os.getenv("CAMPUSNAV_DEMO") == "1" and
                (bridge is None or bridge.app.state.storage_mode == "memory"))

    def current_closures(request):
        if bridge is None:
            return request
        rows = bridge.active(routing=True)
        if demo_enabled():
            rows = [*rows, *(request.closures or [])]
        return request.model_copy(update={"closures": rows})

    @app.post(
        "/route",
        response_model=RouteResponse,
        responses={
            404: {"description": "No feasible route"},
            503: {"description": "Graph unavailable"},
        },
    )
    def route(request: RouteRequest):
        try:
            return get_engine().route(current_closures(request))
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.get("/official-closures/status", tags=["Official notices"])
    def official_status():
        return closure_status() if bridge is not None else snapshot_status(official)

    @app.get(
        "/official-closures",
        response_model=list[Closure],
        tags=["Official notices"],
        description="Cached official closures only. Role 4 merges these with community reports.",
    )
    def official_closures(response: Response):
        if bridge is not None:
            status = bridge.official_status()
            response.headers["X-Closures-Stale"] = str(status["stale"]).lower()
            response.headers["X-Closures-Status"] = status["status"]
            response.headers["X-Closures-Demo"] = "false"
            response.headers["Cache-Control"] = "no-store"
            return [row for row in bridge.active(routing=True) if row.source == "official"]
        try:
            snapshot = read_snapshot(official)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                503,
                detail={
                    "code": "official_data_unavailable",
                    "message": "No valid official snapshot. Run the notice refresh first.",
                },
            ) from exc
        status = snapshot_status(official)
        response.headers["X-Closures-Stale"] = str(status["stale"]).lower()
        response.headers["X-Closures-Status"] = status["status"]
        response.headers["X-Closures-Demo"] = str(snapshot.synthetic).lower()
        response.headers["Cache-Control"] = "no-store"
        return active_closures(snapshot, datetime.now(UTC))

    @app.get("/external-reports/status", tags=["Discovered reports"])
    def external_status():
        return bridge.public_reports()[1] if bridge is not None else reports_status(reports)

    @app.get(
        "/external-reports",
        response_model=list[ExternalReport],
        tags=["Discovered reports"],
        description="Public reports awaiting review. These are not routing closures.",
    )
    def external_reports(response: Response):
        if bridge is not None:
            rows, status = bridge.public_reports()
            response.headers["X-Reports-Stale"] = str(status["stale"]).lower()
            response.headers["Cache-Control"] = "no-store"
            return rows
        status = reports_status(reports)
        if status["status"] == "unavailable":
            raise HTTPException(
                503,
                detail={
                    "code": "reports_unavailable",
                    "message": "No usable public report source yet. Run refresh-reports.cmd "
                    "and check /external-reports/status.",
                },
            )
        try:
            snapshot = read_reports(reports)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                503,
                detail={
                    "code": "reports_unavailable",
                    "message": "Saved reports could not be read.",
                },
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Reports-Stale"] = str(status["stale"]).lower()
        return active_reports(snapshot, datetime.now(UTC))

    def indoor_map(building_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", building_id):
            raise HTTPException(422, detail={"message": "Invalid building ID"})
        try:
            return read_indoor(indoor_maps / (building_id + ".json"))
        except FileNotFoundError as exc:
            raise HTTPException(
                404,
                detail={
                    "code": "indoor_not_mapped",
                    "message": "No indoor topology has been published for this building. "
                    "Floor plans may still be available under /indoor/sources.",
                },
            ) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, detail={"message": "Indoor map failed validation."}) from exc

    def indoor_engine(building_id):
        return IndoorEngine(indoor_map(building_id))

    def place_resolver():
        maps = {}
        building_ids = set(PILOT_BUILDINGS)
        for path in indoor_maps.glob("*.json"):
            # The directory also contains asset indexes, such as public_floorplans.json.
            # They are not IndoorMap documents and must not break the navigation catalog.
            try:
                header = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(header, dict) and header.get("building_id") == path.stem:
                building_ids.add(path.stem)
        for building_id in sorted(building_ids):
            path = indoor_maps / (building_id + ".json")
            if path.exists():
                maps[building_id] = indoor_map(building_id)
        try:
            sources = json.loads(indoor_sources.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sources = {"records": [], "sources": {"catalog": {"mode": "unavailable"}}}
        return PlaceResolver(maps, sources)

    def navigation_closures():
        if bridge is not None:
            rows = bridge.active(routing=True)
            status = bridge.official_status()
            return [row.model_dump() for row in rows], {
                "stale": status["stale"], "count": len(rows), "generated_at": status["generated_at"],
            }
        rows = official_records() + community.active()
        status = snapshot_status(official)
        return rows, dict(
            stale=status["stale"], count=len(rows), generated_at=status.get("generated_at")
        )

    @app.get("/navigation/catalog", tags=["Guided navigation"])
    def navigation_catalog():
        return place_resolver().catalog()

    @app.post("/navigation/resolve", tags=["Guided navigation"])
    def resolve_location(request: ResolveRequest):
        return place_resolver().resolve(
            request.location,
            purpose=request.purpose,
            allow_building=request.purpose == "destination",
        )

    @app.post("/navigation/plan", tags=["Guided navigation"])
    def guided_plan(request: NavigationRequest):
        if bridge is not None:
            request = request.model_copy(update={"closures": None})
        try:
            service = NavigationService(
                get_engine(),
                place_resolver(),
                navigation_closures,
            )
            origin = request.origin
            if (bridge is not None and origin and origin.building_id
                    and not (origin.node_id or origin.floor_id or origin.text)):
                local = catalog()
                building = next((row for row in local["buildings"] if row["id"] == origin.building_id), None)
                if building is None:
                    raise RoutingError("unknown_building", "This building is not in the campus catalog.", 422)
                entrances = choices(
                    Place(**building["location"], building_id=origin.building_id,
                          entrance_id=request.origin_entrance_id),
                    local, step_free=request.no_stairs, automatic=request.need_automatic_door,
                )
                # Use one snapshot for all candidate approaches.
                captured = navigation_closures()
                service = NavigationService(service.outdoor, service.resolver, lambda: captured)
                results = [service.plan(request.model_copy(update={
                    "origin": LocationQuery(outdoor={"lat": entry["lat"], "lng": entry["lng"]}),
                })) for entry in entrances]
                ready = [row for row in results if row["status"] == "route_ready"]
                return min(ready, key=lambda row: row["journey"]["routing_cost"]) if ready else results[0]
            return service.plan(request)
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.post("/navigation/arrive", tags=["Guided navigation"])
    def guided_arrival(request: ArrivalRequest):
        if bridge is not None:
            request = request.model_copy(update={"closures": None})
        try:
            return NavigationService(
                get_engine(),
                place_resolver(),
                navigation_closures,
            ).arrive(request)
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.get("/indoor/sources", tags=["Indoor navigation"])
    def indoor_source_catalog():
        try:
            return json.loads(indoor_sources.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(
                503, detail={"message": "Run refresh-indoor.cmd to fetch floor directories."}
            ) from exc

    @app.get("/plan-wayfinding", tags=["Drawing wayfinding pilot"])
    def wayfinding_catalog():
        if not plan_dir:
            return dict(buildings=[], status="not_configured")
        buildings = []
        for path in sorted(Path(plan_dir).glob("*.json")):
            try:
                data = PlanWayfindingMap.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.building_id != path.stem:
                continue
            buildings.append(
                dict(
                    building_id=data.building_id,
                    floors=sorted({n.floor_id or data.floor_id for n in data.nodes}),
                    coordinate_system=data.coordinate_system,
                    landmark_count=len(data.nodes),
                    resident_access_required=data.resident_access_required,
                    physical_verification=False,
                    source_warnings=data.source_warnings,
                )
            )
        return dict(buildings=buildings, status="drawing_wayfinding_only")

    @app.get("/plan-wayfinding/{building_id}", tags=["Drawing wayfinding pilot"])
    def get_plan_wayfinding(building_id: str):
        return source_plan(building_id)

    @app.post("/plan-wayfinding/{building_id}", tags=["Drawing wayfinding pilot"])
    def drawing_directions(building_id: str, request: PlanWayfindingRequest):
        try:
            return plan_directions(source_plan(building_id), request)
        except RoutingError as error:
            raise HTTPException(
                error.status, detail=dict(code=error.code, message=error.message)
            ) from error

    @app.get("/indoor/status", tags=["Indoor navigation"])
    def indoor_status():
        rows = []
        for path in sorted(indoor_maps.glob("*.json")):
            try:
                data = read_indoor(path)
                rows.append(
                    dict(
                        building_id=data.building_id,
                        name=data.name,
                        status=data.status,
                        routable=data.status == "reviewed" and not data.synthetic,
                        room_routable=any(node.kind == "room" for node in data.nodes)
                        and data.status == "reviewed"
                        and not data.synthetic,
                        room_count=sum(node.kind == "room" for node in data.nodes),
                        synthetic=data.synthetic,
                        floor_count=len(data.floors),
                        portal_count=len(data.portals),
                        reviewed_at=data.reviewed_at,
                    )
                )
            except (OSError, ValueError):
                rows.append(dict(building_id=path.stem, status="invalid", routable=False))
        return dict(buildings=rows, note="Floor-plan references alone are not routing topology.")

    @app.post("/indoor/route", tags=["Indoor navigation"])
    def indoor_route(request: IndoorRouteRequest):
        try:
            return indoor_engine(request.building_id).route(current_closures(request))
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.post("/journey", tags=["Indoor navigation"])
    def journey(request: JourneyRequest):
        try:
            return plan_journey(get_engine(), indoor_engine, current_closures(request))
        except RoutingError as exc:
            raise HTTPException(
                exc.status, detail={"code": exc.code, "message": exc.message}
            ) from exc

    @app.get("/indoor/maps/{building_id}", tags=["Indoor navigation"])
    def indoor_floor_map(building_id: str):
        return indoor_map(building_id)

    if data_app is not None:
        app.mount("/api/data", data_app, name="data-api")
    frontend = ROOT / "frontend/dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="map-ui")
    else:
        app.add_api_route("/", home, response_class=HTMLResponse, include_in_schema=False)
    return app


app = create_app()
