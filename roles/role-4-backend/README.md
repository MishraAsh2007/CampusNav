# Role 4: Backend, Crowdsourcing & MongoDB Architecture

## 🎯 Mission
1. Manage the central database using **MongoDB Atlas** (qualifying for the MongoDB sponsor prize!).
2. Create collections:
   - `buildings` (seeded from `contracts/buildings.contract.json`)
   - `official_closures` (ingested from Role 3's scraped data)
   - `community_reports` (submitted from Role 2 via `/api/report`)
3. Expose the `/api/closures` endpoint which merges official notices with community reports (community reports take precedence for 12 hours).
4. Set up TTL index so crowdsourced reports expire automatically after 24 hours.

---

## 🍃 MongoDB Atlas Schema & TTL Index
```javascript
// Mongo Shell / Compass setup
db.community_reports.createIndex(
  { "timestamp": 1 },
  { expireAfterSeconds: 86400 } // Automatically purge after 24 hours!
);

db.community_reports.createIndex(
  { "location": "2dsphere" } // Geospatial index for radius queries
);
```

---

## 📡 Endpoints to Implement
- `GET /api/closures`: Merges official + community outages.
- `GET /api/buildings`: Serves building accessibility metadata.
- `POST /api/report`: Ingests student reports, stores to Atlas, and broadcasts new barrier.
- `GET /health`: Health probe used by Role 2 to auto-detect backend connectivity.
