"""Prefill USGS 3DEP (1 m lidar) elevations for every graph node, resumably.

    python scripts/fetch_3dep.py              # run until done; safe to stop and rerun
    python scripts/fetch_3dep.py --workers 8

EPQS answers one point per request and takes several seconds each, so this runs requests in
parallel and saves to data/elevation_cache_epqs.json every few results. Rerunning skips
points already cached and retries ones that failed.

Seeds the cache from role-2-map-ui's scripts/cache/elevation.json (same USGS 3DEP source,
keyed by "lat,lon" to 6 decimals) via `git show`, so only the remaining points are fetched.
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.graph.build import download_graph  # noqa: E402
from app.graph.elevation import _load_cache, cache_path_for, epqs_point, write_cache  # noqa: E402

SEED_REFS = ("role-2-map-ui", "origin/role-2-map-ui")
SEED_FILE = "scripts/cache/elevation.json"


def load_seed() -> dict:
    for ref in SEED_REFS:
        try:
            raw = subprocess.run(["git", "show", f"{ref}:{SEED_FILE}"], cwd=ROOT, capture_output=True,
                                 check=True).stdout.decode("utf-8-sig")
            return json.loads(raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            continue
    print("[3dep] no role-2 seed found; fetching everything")
    return {}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--save-every", type=int, default=20)
    args = p.parse_args()

    path = cache_path_for("epqs")
    G = download_graph()
    cache = _load_cache(path)
    seed = load_seed()

    seeded = 0
    for n, d in G.nodes(data=True):
        if str(n) in cache:
            continue
        z = seed.get(f"{d['y']:.6f},{d['x']:.6f}")
        if z is not None:
            cache[str(n)] = float(z)
            seeded += 1
    write_cache(path, cache)

    todo = [(n, (d["y"], d["x"])) for n, d in G.nodes(data=True) if str(n) not in cache]
    print(f"[3dep] nodes {G.number_of_nodes()} | cached {len(cache) - seeded} | seeded from role-2 {seeded} "
          f"| to fetch {len(todo)}", flush=True)

    done = failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(epqs_point, pt): n for n, pt in todo}
        for fut in as_completed(futures):
            z = fut.result()
            if z is None:
                failed += 1
            else:
                cache[str(futures[fut])] = z
            done += 1
            if done % args.save_every == 0 or done == len(todo):
                write_cache(path, cache)
                rate = done / max(time.time() - t0, 1e-9)
                left = (len(todo) - done) / rate if rate else 0
                print(f"[3dep] {done}/{len(todo)} done, {failed} failed, ~{left / 60:.0f} min left", flush=True)

    write_cache(path, cache)
    print(f"[3dep] finished: {len(cache)}/{G.number_of_nodes()} nodes cached, {failed} failed"
          + (" (rerun to retry them)" if failed else ""), flush=True)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
