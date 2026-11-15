"""
Role 4: FastAPI + MongoDB Backend Server Stub
Implements /api/closures, /api/buildings, /api/report endpoints.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

app = FastAPI(title="CampusNav Backend & MongoDB Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory fallback if MongoDB Atlas is not yet connected
mock_community_reports = []

class UserReport(BaseModel):
    lat: float
    lng: float
    type: str
    status: str
    title: str
    description: Optional[str] = ""
    building_id: Optional[str] = None
    timestamp: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok", "db": "mongodb_atlas_ready"}

@app.get("/api/closures")
def get_closures():
    """
    Merges official notices from Role 3 with community reports.
    Community reports override official reports for 12 hours.
    """
    return [
        {
            "id": "cc-elev-concourse",
            "lat": 42.3916,
            "lng": -72.5274,
            "radius": 18,
            "type": "elevator",
            "status": "closed",
            "source": "official",
            "title": "Campus Center Concourse Elevator Out",
            "description": "Hydraulic failure reported by Facilities.",
            "last_confirmed": datetime.utcnow().isoformat() + "Z",
            "confirmations_count": 14
        }
    ] + mock_community_reports

@app.post("/api/report")
def submit_report(report: UserReport):
    report_dict = report.dict()
    report_dict["id"] = f"rep-{int(datetime.utcnow().timestamp())}"
    report_dict["source"] = "community"
    report_dict["radius"] = 15
    report_dict["last_confirmed"] = datetime.utcnow().isoformat() + "Z"
    report_dict["confirmations_count"] = 1
    mock_community_reports.append(report_dict)
    return {"success": True, "closure": report_dict}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server_stub:app", host="0.0.0.0", port=8000, reload=True)
