"""
Role 1: Python FastAPI Routing Engine Server
Implements /api/route and /health endpoints matching shared contracts.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict

app = FastAPI(title="CampusNav Routing Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Coordinates(BaseModel):
    lat: float
    lng: float

class Preferences(BaseModel):
    max_grade_pct: float = 5.0
    no_stairs: bool = True
    prefer_indoor: bool = False

class RouteRequest(BaseModel):
    start: Coordinates
    end: Coordinates
    preferences: Preferences
    closures: Optional[List[Dict[str, Any]]] = []

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "CampusNav Python Routing Engine"}

@app.post("/api/route")
def calculate_route_endpoint(req: RouteRequest):
    """
    Role 1 algorithm goes here:
    1. Filter OSMnx graph edges (drop 'highway=steps', drop slope > max_grade_pct)
    2. Drop edges within closure.radius of active closures
    3. Run Dijkstra / A*
    4. Return GeoJSON LineString
    """
    # Sample compliant GeoJSON response
    return {
        "type": "FeatureCollection",
        "summary": {
            "total_distance_m": 145,
            "total_duration_s": 130,
            "max_grade_pct": 3.8,
            "avg_grade_pct": 2.1,
            "elevation_gain_m": 4.5,
            "is_step_free": True,
            "stair_count": 0,
            "warnings": ["Rerouted around Campus Center Elevator via Student Union ramp"]
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [req.start.lng, req.start.lat],
                        [-72.5276, 42.3914],
                        [-72.5272, 42.3918],
                        [req.end.lng, req.end.lat]
                    ]
                },
                "properties": {
                    "grade": 3.8,
                    "surface": "paved_ramp",
                    "is_step": False,
                    "is_ramp": True,
                    "segment_name": "Campus Center Concourse to Promenade"
                }
            }
        ],
        "steps": [
            {
                "instruction": "Depart via Student Union covered ramp (3.8% grade)",
                "distance_m": 75,
                "grade_pct": 3.8,
                "icon": "ramp"
            },
            {
                "instruction": "Continue along Campus Center Level 2 Promenade",
                "distance_m": 70,
                "grade_pct": 1.2,
                "icon": "straight"
            }
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mock_server:app", host="0.0.0.0", port=8000, reload=True)
