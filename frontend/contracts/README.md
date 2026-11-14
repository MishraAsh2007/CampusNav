# CampusNav Shared API Contracts & Team Integration Guide

Welcome to the **CampusNav** core contracts repository! To ensure all 4 team roles work in parallel without blocking each other during HackUMass, everyone adheres strictly to these JSON data contracts.

---

## 👥 The 4 Roles Breakdown

| Role | Domain | Tech Stack | Input Contract | Output Contract |
|------|--------|------------|----------------|-----------------|
| **Role 1** | **Routing Engine** | Python (OSMnx, NetworkX, FastAPI) | Start/End coords, `max_grade`, active `closures[]` | `route.contract.json` (GeoJSON) |
| **Role 2** | **Map UI & Frontend (You)** | React 18, TypeScript, Leaflet, Tailwind | User clicks, preferences, `closures[]`, `buildings[]` | Renders map, routes, POSTs `report.contract.json` |
| **Role 3** | **Official Data Pipeline** | Python (BeautifulSoup, Gemini Flash API) | UMass Facilities pages, PDFs | `closures.contract.json` (Structured JSON) |
| **Role 4** | **Backend & MongoDB Database** | FastAPI / Express, MongoDB Atlas | Community reports, Scraped JSON | Serves `/closures`, `/buildings`, handles `/report` |

---

## 📡 API Endpoints

### 1. `GET /api/closures`
- **Output**: Array complying with `closures.contract.json`
- **Description**: Returns all currently active closures (merged from Role 3 scraped official notices + Role 4 community reports).
- **Rule**: Community reports override official reports for 12 hours. Reports expire after 24h via MongoDB TTL unless reconfirmed.

### 2. `POST /api/route`
- **Payload**:
  ```json
  {
    "start": { "lat": 42.3912, "lng": -72.5267 },
    "end": { "lat": 42.3898, "lng": -72.5281 },
    "preferences": {
      "max_grade_pct": 5.0,
      "no_stairs": true,
      "prefer_indoor": false,
      "wheelchair_preset": "manual"
    },
    "closures": [ /* active closures array passed in for stateless pathfinding */ ]
  }
  ```
- **Output**: `route.contract.json` (GeoJSON FeatureCollection with elevation & slope metadata).

### 3. `GET /api/buildings`
- **Output**: Array complying with `buildings.contract.json`
- **Description**: Comprehensive central UMass building accessibility metadata (entrances, automatic doors, elevators).

### 4. `POST /api/report`
- **Payload**: Complies with `report.contract.json`
- **Description**: Ingests student crowdsourced outage report, logs to MongoDB, updates active closures immediately.

---

## ⏱️ 36-Hour Integration Checkpoints
- **Friday 11:59 PM (Contract Check)**: Role 2 renders hardcoded mock data. Role 1 parses dummy closures.
- **Saturday 12:00 PM (First Integration)**: Role 2 toggles `api.ts` from mock simulation to live backend (`http://localhost:8000`).
- **Saturday 6:00 PM (Demo Rehearsal)**: Lock features. Run the demo moment (breaking the Campus Center elevator and watching the route live-divert).
