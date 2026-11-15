# Role 3: Official Data Pipeline & Pitch Strategy

## 🎯 Mission
1. Scrape messy UMass Facilities construction & elevator interruption notices.
2. Pass raw HTML/PDF text to the Gemini Flash API to extract structured coordinates, barrier types, and status matching `contracts/closures.contract.json`.
3. Save structured JSON to disk/MongoDB on an hourly cron job with fallback caching.
4. Architect the Devpost submission and pitch narrative!

---

## 🔗 Official UMass Sources
- **Facilities Maintenance Interruptions**:  
  `https://umass.sharepoint.com/sites/impactnotices/Lists/Service%20Interruption%20Notices/Current%20Interruptions.aspx`
- **UMass Campus Accessibility Map**:  
  `https://www.umass.edu/planning-design-construction/sites/default/files/2024-11/CampusMap-Accessbility-Large-2024.pdf`

---

## 🤖 Gemini Prompt for Text -> JSON Extraction
Use Gemini 2.0 Flash with `response_mime_type="application/json"`:
```python
prompt = f"""
Extract all active campus accessibility barriers (elevators out, ramps closed, construction) from this UMass Facilities text.
Return a JSON array where each object has:
- id: string
- lat: float (accurate UMass Amherst coordinates)
- lng: float
- radius: integer (meters)
- type: 'elevator' | 'ramp' | 'path' | 'automatic_door' | 'construction'
- status: 'closed' | 'degraded'
- source: 'official'
- title: string
- description: string
- last_confirmed: ISO 8601 string

Text:
{raw_facilities_text}
"""
```

---

## 🏆 Devpost Pitch Strategy
- **Primary Track**: Accessibility
- **Sponsor Prizes**: Gemini API Prize, MongoDB Atlas Prize
- **Key Demo Hook**: Show side-by-side shortest vs step-free paths, then break an elevator live and watch the route recalculate!
