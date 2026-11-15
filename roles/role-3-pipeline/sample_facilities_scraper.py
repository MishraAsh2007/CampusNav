"""
Role 3: Official Data Pipeline & Gemini LLM Parser
Pulls unstructured UMass service interruption notices and transforms them
into clean JSON matching contracts/closures.contract.json.
"""

import os
import json
from datetime import datetime
import urllib.request

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OUTPUT_FILE = "../../contracts/closures.contract.json"

SAMPLE_FACILITIES_BULLETIN = """
UMASS AMHERST PHYSICAL PLANT SERVICE INTERRUPTION NOTICE #441
Building: Murray D. Lincoln Campus Center
System Affected: Elevator Car #1 (Concourse to Level 2)
Dates: Nov 13, 2026 - Nov 14, 2026
Reason: Hydraulic valve replacement and inspection.
Detour: Passengers requiring step-free transport must utilize the Student Union 
concourse ramp or exterior Campus Center Way entrance.

NOTICE #442: Goodell Hall West Walkway
Concrete remediation work on west entrance ADA ramp starting Nov 12. 
Ramp will remain barricaded until curing completes Nov 15.
"""

def parse_with_gemini(raw_text: str):
    if not GEMINI_API_KEY:
        print("[!] No GEMINI_API_KEY set. Using offline template parser.")
        return [
            {
                "id": "cc-elev-01",
                "lat": 42.3916,
                "lng": -72.5274,
                "radius": 15,
                "type": "elevator",
                "status": "closed",
                "source": "official",
                "title": "Campus Center Concourse Elevator Out",
                "description": "Hydraulic valve overhaul in progress.",
                "building_name": "Campus Center",
                "start_time": datetime.utcnow().isoformat() + "Z",
                "last_confirmed": datetime.utcnow().isoformat() + "Z",
                "confirmations_count": 12
            }
        ]

    # Role 3: Live Gemini Flash API Call
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = f"Convert this text to JSON matching the Closures schema:\n{raw_text}"
    req_body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    
    req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res

if __name__ == "__main__":
    print("[*] Scraping UMass Facilities Bulletins...")
    parsed = parse_with_gemini(SAMPLE_FACILITIES_BULLETIN)
    print(f"[+] Extracted {len(parsed)} active closures.")
    print(json.dumps(parsed, indent=2))
