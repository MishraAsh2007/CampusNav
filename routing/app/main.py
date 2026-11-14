"""FastAPI app: stateless /route and /health.

Run from routing/:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .frontend_api import router as frontend_router
from .graph.load import load_graph
from .routing.pathfinding import plan_routes
from .schemas import HealthResponse, RouteRequest, RouteResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.graph = None
    app.state.graph_error = None
    try:
        app.state.graph = load_graph()
        print(f"[startup] graph loaded: {app.state.graph.number_of_nodes()} nodes")
    except Exception as exc:  # keep the server up so /health explains what is wrong
        app.state.graph_error = str(exc)
        print(f"[startup] graph NOT loaded: {exc}")
    yield


app = FastAPI(title="CampusNav Routing Engine", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(frontend_router)  # POST /api/route for the map UI


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    G = app.state.graph
    return HealthResponse(
        status="ok" if G is not None else "degraded",
        graph_loaded=G is not None,
        nodes=G.number_of_nodes() if G is not None else 0,
        edges=G.number_of_edges() if G is not None else 0,
        graph_path=str(config.GRAPH_PATH),
    )


@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    G = app.state.graph
    if G is None:
        raise HTTPException(503, detail=f"graph not loaded: {app.state.graph_error}")

    # Reject points far outside the covered area rather than snapping across campus.
    points = [("start", req.start.lat, req.start.lon)]
    if req.end is not None:
        points.append(("end", req.end.lat, req.end.lon))
    if req.destination is not None:
        b = req.destination.building
        points.append((f"destination {b.name}", b.lat, b.lng))
    for label, lat, lon in points:
        lat_ok = config.BBOX["south"] - 0.002 <= lat <= config.BBOX["north"] + 0.002
        lon_ok = config.BBOX["west"] - 0.002 <= lon <= config.BBOX["east"] + 0.002
        if not (lat_ok and lon_ok):
            raise HTTPException(422, detail=f"{label} is outside the supported campus area")

    return plan_routes(G, req)
