"""Render official residence plans and extract coordinates for manual topology tracing."""

import argparse
import json
import re
from pathlib import Path

from campus_notices.cache import atomic_json

ROOT = Path(__file__).resolve().parents[1]
ROOM_TOKEN = re.compile(r"(?:-\d{2}[A-Z]?|\b\d{3}[A-Z]?\b)")


def _safe(value):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def prepare(manifest_path: Path, render_root: Path):
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError("Install the pipeline dependencies to render residence plans") from exc

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for record in manifest["records"]:
        source = Path(record["local_path"])
        if not source.exists():
            raise FileNotFoundError(source)
        document = pymupdf.open(str(source))
        page = document[0]
        render_path = (
            render_root
            / _safe(record["area"])
            / _safe(record["building"])
            / f"{source.stem}.png"
        )
        render_path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        pixmap.save(str(render_path))
        candidates = []
        for block in page.get_text("blocks"):
            text = " ".join(block[4].split()).upper()
            if block[1] < 150 or block[3] > page.rect.height - 100:
                continue
            tokens = ROOM_TOKEN.findall(text)
            if not tokens:
                continue
            x = round((block[0] + block[2]) / 2, 3)
            y = round((block[1] + block[3]) / 2, 3)
            for token in dict.fromkeys(tokens):
                candidates.append({"label": token, "x": x, "y": y})
        record["trace"] = {
            "rendered_path": str(render_path),
            "page_width": float(page.rect.width),
            "page_height": float(page.rect.height),
            "room_label_candidates": candidates,
        }
        document.close()
    atomic_json(manifest_path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/manifest.json",
    )
    parser.add_argument(
        "--render-root",
        type=Path,
        default=ROOT / "data/private/residence_floorplans/rendered",
    )
    args = parser.parse_args()
    result = prepare(args.manifest, args.render_root)
    print(f"Prepared tracing assets for {result['file_count']} official plans")


if __name__ == "__main__":
    main()
