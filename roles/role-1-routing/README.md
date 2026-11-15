# Role 1: The Routing Engine (Graph & Algorithms)

## 🎯 Mission
Turn raw OpenStreetMap (OSM) pedestrian networks into a mathematical graph that calculates the most accessible, step-free path across UMass Amherst central campus in milliseconds.

---

## 📐 Central Campus Bounding Box
For OSMnx graph downloading:
```python
import osmnx as ox

# UMass Amherst Central Campus (ILC, Campus Center, Library, Student Union)
north, south, east, west = 42.400, 42.380, -72.520, -72.538
G = ox.graph_from_bbox(north, south, east, west, network_type='walk')
```

---

## ⚡ API Specification
Your FastAPI server must listen on port `8000`:
- **Endpoint**: `POST /api/route`
- **Request Body**:
  ```json
  {
    "start": { "lat": 42.3916, "lng": -72.5277 },
    "end": { "lat": 42.3920, "lng": -72.5270 },
    "preferences": {
      "max_grade_pct": 5.0,
      "no_stairs": true,
      "prefer_indoor": false
    },
    "closures": [ /* array from closures contract */ ]
  }
  ```
- **Response**: Return a JSON object matching `contracts/route.contract.json` (GeoJSON FeatureCollection).

---

## 🏃 Quick Start
```bash
cd roles/role-1-routing
pip install -r requirements.txt
uvicorn mock_server:app --port 8000 --reload
```
Once this is running, Role 2 (Frontend) will automatically detect `http://localhost:8000` and switch its status pill to **"Live Backend Connected"**!
