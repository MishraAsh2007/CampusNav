"""Download public central-campus plan references; keep provenance and render for review."""

import hashlib
from pathlib import Path

import httpx
import pymupdf

from campus_notices.cache import atomic_json

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "cc-upper": "https://people.umass.edu/sdestef/Campus%20Center%2010%20and%2011%20Floor%20Layouts.pdf",
    "cc-concourse-historical": "https://people.umass.edu/sdestef/Campus%20Center%20Second%20Floor%20Layout.pdf",
    "cc-su-diagrams": "https://www.umass.edu/student-life/sites/default/files/2024-08/Diagrams%20CC%20%26%20SU.pdf",
    "su-business-map": "https://www.umass.edu/studentlife/sites/default/files/documents/pdf/Student_Business_Map_Locations.pdf",
}


def main():
    folder = ROOT / ".cache/central-plans"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        for key, url in URLS.items():
            r = client.get(url)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                print(key, "unavailable", r.status_code)
                continue
            path = folder / (key + ".pdf")
            path.write_bytes(r.content)
            with pymupdf.open(path) as doc:
                text = []
                for i, page in enumerate(doc):
                    text.append(page.get_text())
                    page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False).save(
                        str(folder / f"{key}-{i + 1}.png")
                    )
                rec = dict(
                    id=key,
                    url=url,
                    sha256=hashlib.sha256(r.content).hexdigest(),
                    pages=len(doc),
                    local_path=str(path),
                    text=text,
                )
                records.append(rec)
                print(key, len(doc), "pages", [(i + 1, t[:180]) for i, t in enumerate(text)])
    atomic_json(folder / "manifest.json", dict(records=records))


if __name__ == "__main__":
    main()
