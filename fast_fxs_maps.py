"""Fast, single-day updates for the 福州—厦门—汕头 route maps.

One-time migration (no network):
    python fast_fxs_maps.py --bootstrap

After that, edit only travel/fuzhou-xiamen-shantou/routes/YYYY-MM-DD.json,
then run:
    python fast_fxs_maps.py --date YYYY-MM-DD

The HTML shells can fetch these JSON files. Unchanged legs retain their exact
geometry. Previously seen driving legs use the local cache; only new driving
legs call OSRM. A failed route request is an error, never a straight-line
fallback. This script does not rewrite HTML, Notion, or the legacy builder.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


BASE = Path(__file__).resolve().parent / "travel" / "fuzhou-xiamen-shantou"
ROUTES = BASE / "routes"
CACHE = ROUTES / "_geometry_cache.json"
EXPECTED_DATES = [
    (dt.date(2026, 10, 11) + dt.timedelta(days=n)).isoformat()
    for n in range(13)
]
ROUTE_DATA_RE = re.compile(
    r'<script\s+id="route-data"\s+type="application/json">(.*?)</script>',
    re.DOTALL,
)
DRIVING_RE = re.compile(r"打车|包车|景区车|驾车|自驾|网约车|出租车")


class RouteError(Exception):
    pass


def fail(message: str) -> None:
    raise RouteError(message)


def is_coord(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in value)
        and 73 <= value[0] <= 135
        and 18 <= value[1] <= 54
    )


def validate_geometry(coords: object, where: str) -> None:
    if not isinstance(coords, list) or len(coords) < 2 or not all(is_coord(c) for c in coords):
        fail(f"{where}: invalid geometry; expected at least two WGS84 [lon, lat] pairs")


def leg_key(a: list[float], b: list[float]) -> str:
    return f"{a[0]:.6f},{a[1]:.6f}>{b[0]:.6f},{b[1]:.6f}"


def is_driving(mode: str) -> bool:
    return bool(DRIVING_RE.search(mode))


def leg_specs(data: dict) -> list[dict]:
    points = data["points"]
    modes = data["modes"]
    legs = [
        dict(mode=mode, key=leg_key(points[i]["coord"], points[i + 1]["coord"]),
             start=points[i]["coord"], end=points[i + 1]["coord"])
        for i, mode in enumerate(modes)
    ]
    if data.get("loop"):
        mode = data.get("loop_mode", "包车／回到起点")
        legs.append(dict(mode=mode, key=leg_key(points[-1]["coord"], points[0]["coord"]),
                         start=points[-1]["coord"], end=points[0]["coord"]))
    return legs


def validate_data(data: object, day: str, *, require_segments: bool) -> list[dict]:
    if not isinstance(data, dict):
        fail(f"{day}: route data must be a JSON object")
    if data.get("date", day) != day:
        fail(f"{day}: embedded date {data.get('date')!r} does not match filename")
    for field in ("title", "city", "note"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            fail(f"{day}: missing nonempty {field}")
    points = data.get("points")
    modes = data.get("modes")
    if not isinstance(points, list) or len(points) < 1:
        fail(f"{day}: points must contain at least one stop")
    if not isinstance(modes, list) or len(modes) != len(points) - 1:
        fail(f"{day}: {len(points)} points require {len(points)-1} modes")
    for i, point in enumerate(points, 1):
        if not isinstance(point, dict) or not is_coord(point.get("coord")):
            fail(f"{day} point {i}: missing or invalid WGS84 coordinate")
        for field in ("name", "what", "stay", "source"):
            if not isinstance(point.get(field), str) or not point[field].strip():
                fail(f"{day} point {i}: missing nonempty {field}")
    if not all(isinstance(mode, str) and mode.strip() for mode in modes):
        fail(f"{day}: every mode must be nonempty text")
    if data.get("loop") and (not isinstance(data.get("loop_mode"), str) or not data["loop_mode"].strip()):
        fail(f"{day}: loop=true requires a nonempty loop_mode")
    alternatives = data.get("alternatives", [])
    if not isinstance(alternatives, list):
        fail(f"{day}: alternatives must be a list")
    for alt_i, alt in enumerate(alternatives, 1):
        if not isinstance(alt, dict) or not isinstance(alt.get("label"), str) or not isinstance(alt.get("points"), list):
            fail(f"{day}: alternative {alt_i} has invalid structure")
        for point_i, point in enumerate(alt["points"], 1):
            if not isinstance(point, dict) or not is_coord(point.get("coord")):
                fail(f"{day}: alternative {alt_i} point {point_i} has invalid coordinate")
    specs = leg_specs(data)
    segments = data.get("segments")
    if require_segments and (not isinstance(segments, list) or len(segments) != len(specs)):
        fail(f"{day}: {len(specs)} legs require exactly {len(specs)} segments")
    if isinstance(segments, list):
        if len(segments) != len(specs):
            fail(f"{day}: segment count differs from route legs")
        for i, (segment, spec) in enumerate(zip(segments, specs), 1):
            if not isinstance(segment, dict) or segment.get("mode") != spec["mode"]:
                fail(f"{day} leg {i}: segment mode does not match current mode")
            validate_geometry(segment.get("coords"), f"{day} leg {i}")
    return specs


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read {path}: {exc}")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(spec: dict) -> dict:
    return {"mode": spec["mode"], "key": spec["key"]}


def bootstrap() -> None:
    existing = list(ROUTES.glob("*.json")) if ROUTES.exists() else []
    if existing:
        fail(f"{ROUTES} already has JSON files; bootstrap will not overwrite edited routes")
    files = sorted(BASE.glob("2026-10-*.html"))
    found = [path.stem for path in files]
    if found != EXPECTED_DATES:
        fail(f"HTML date mismatch. Expected {EXPECTED_DATES}; found {found}")
    days: dict[str, dict] = {}
    roads: dict[str, list] = {}
    manifest: dict[str, list] = {}
    short_roads: list[str] = []
    for path in files:
        day = path.stem
        html = path.read_text(encoding="utf-8")
        matches = ROUTE_DATA_RE.findall(html)
        if len(matches) != 1:
            fail(f"{path}: expected exactly one embedded route-data script, found {len(matches)}")
        try:
            data = json.loads(matches[0])
        except json.JSONDecodeError as exc:
            fail(f"{path}: invalid embedded JSON: {exc}")
        if data.get("loop"):
            data["loop_mode"] = data["segments"][-1]["mode"]
        data["date"] = day
        specs = validate_data(data, day, require_segments=True)
        for i, (segment, spec) in enumerate(zip(data["segments"], specs), 1):
            if is_driving(spec["mode"]):
                geometry = segment["coords"]
                if len(geometry) > 2:
                    old = roads.get(spec["key"])
                    if old is not None and old != geometry:
                        fail(f"{day} leg {i}: same endpoints have conflicting cached road geometries")
                    roads[spec["key"]] = geometry
                else:
                    short_roads.append(f"{day} leg {i}")
        days[day] = data
        manifest[day] = [fingerprint(spec) for spec in specs]
    cache = {"version": 1, "roads": roads, "days": manifest}
    ROUTES.mkdir(parents=True, exist_ok=True)
    for day, data in days.items():
        atomic_json(ROUTES / f"{day}.json", data)
    atomic_json(CACHE, cache)
    print(f"Bootstrapped {len(days)} day files, {len(roads)} detailed driving legs; no network used.")
    if short_roads:
        print("Existing two-point driving segments preserved but not cached: " + ", ".join(short_roads))


def osrm_route(start: list[float], end: list[float]) -> list[list[float]]:
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{start[0]},{start[1]};{end[0]},{end[1]}"
        "?overview=full&geometries=geojson"
    )
    failures: list[str] = []
    for attempt in range(2):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PersonalTravelMaps/2.0"})
            with urllib.request.urlopen(request, timeout=8) as response:
                result = json.load(response)
            if result.get("code") != "Ok" or not result.get("routes"):
                fail(f"OSRM response code {result.get('code')!r}")
            first = result["routes"][0]
            if first.get("distance", float("inf")) > 100_000:
                fail(f"OSRM road distance {first['distance']/1000:.1f} km exceeds 100 km guard")
            geometry = first["geometry"]["coordinates"]
            validate_geometry(geometry, "OSRM response")
            step = max(1, len(geometry) // 350)
            sampled = [
                [round(lon, 6), round(lat, 6)] for lon, lat in geometry[::step]
            ]
            last = [round(n, 6) for n in geometry[-1]]
            if sampled[-1] != last:
                sampled.append(last)
            return sampled
        except (RouteError, KeyError, TypeError, ValueError, OSError, urllib.error.URLError) as exc:
            failures.append(str(exc))
            if attempt == 0:
                time.sleep(0.3)
    fail("OSRM failed after 2 attempts of at most 8 seconds each: " + " | ".join(failures))


def update_day(day: str) -> None:
    if day not in EXPECTED_DATES:
        fail(f"{day}: not one of the 13 trip dates ({EXPECTED_DATES[0]} to {EXPECTED_DATES[-1]})")
    path = ROUTES / f"{day}.json"
    data = read_json(path)
    cache = read_json(CACHE)
    if cache.get("version") != 1 or not isinstance(cache.get("roads"), dict) or not isinstance(cache.get("days"), dict):
        fail(f"{CACHE}: unsupported or invalid cache schema")
    previous = cache["days"].get(day)
    if not isinstance(previous, list):
        fail(f"{day}: missing prior leg fingerprints; run bootstrap first")
    # Edited points/modes may invalidate old segments. Validate the source fields
    # independently, then compare old segment shapes to the prior manifest.
    old_segments = data.pop("segments", None)
    specs = validate_data(data, day, require_segments=False)
    data["segments"] = old_segments
    if not isinstance(old_segments, list) or len(old_segments) != len(previous):
        fail(f"{day}: old segment count differs from recorded leg count; restore segments before updating")
    for i, segment in enumerate(old_segments, 1):
        if not isinstance(segment, dict) or not isinstance(segment.get("mode"), str):
            fail(f"{day} old leg {i}: invalid segment structure")
        validate_geometry(segment.get("coords"), f"{day} old leg {i}")
    roads = cache["roads"]
    output: list[dict | None] = [None] * len(specs)
    pending: dict[str, tuple[list[float], list[float]]] = {}
    pending_indexes: dict[str, list[int]] = {}
    counts = {"unchanged": 0, "cached": 0, "direct": 0, "fetched": 0}
    for i, spec in enumerate(specs):
        prior = previous[i] if i < len(previous) else None
        if prior == fingerprint(spec):
            output[i] = {"mode": spec["mode"], "coords": old_segments[i]["coords"]}
            counts["unchanged"] += 1
            continue
        if not is_driving(spec["mode"]):
            output[i] = {"mode": spec["mode"], "coords": [spec["start"], spec["end"]]}
            counts["direct"] += 1
            continue
        key = spec["key"]
        if key in roads:
            validate_geometry(roads[key], f"cached road {key}")
            output[i] = {"mode": spec["mode"], "coords": roads[key]}
            counts["cached"] += 1
        else:
            pending[key] = (spec["start"], spec["end"])
            pending_indexes.setdefault(key, []).append(i)
    if pending:
        errors: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_to_key = {
                pool.submit(osrm_route, start, end): key
                for key, (start, end) in pending.items()
            }
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    geometry = future.result()
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    continue
                roads[key] = geometry
                for i in pending_indexes[key]:
                    output[i] = {"mode": specs[i]["mode"], "coords": geometry}
                    counts["fetched"] += 1
        if errors:
            fail(f"{day}: cannot update road legs; no files changed. " + "; ".join(errors))
    if any(segment is None for segment in output):
        fail(f"{day}: internal error, incomplete segment list")
    data["segments"] = output
    validate_data(data, day, require_segments=True)
    cache["days"][day] = [fingerprint(spec) for spec in specs]
    # Write the route first; the next run can rebuild a stale manifest if the
    # cache write is interrupted, and both files are atomically replaced.
    atomic_json(path, data)
    atomic_json(CACHE, cache)
    print(
        f"Updated {day}: {counts['unchanged']} unchanged, {counts['cached']} cached road, "
        f"{counts['direct']} direct, {counts['fetched']} newly routed."
    )


def show_day(day: str) -> None:
    if day not in EXPECTED_DATES:
        fail(f"{day}: not one of the 13 trip dates")
    data = read_json(ROUTES / f"{day}.json")
    validate_data(data, day, require_segments=True)
    print(f"{day}  {data['title']}")
    for i, point in enumerate(data["points"]):
        print(f"{i + 1}. {point['name']}  {point['coord']}  停留 {point['stay']}")
        print(f"   看点：{point['what']}；坐标来源：{point['source']}")
        if i < len(data["modes"]):
            print(f"   → {data['modes'][i]}")


def check_all() -> None:
    for day in EXPECTED_DATES:
        validate_data(read_json(ROUTES / f"{day}.json"), day, require_segments=True)
    print(f"Validated {len(EXPECTED_DATES)} daily route files.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--bootstrap", action="store_true", help="Extract all 13 existing HTML maps without network")
    action.add_argument("--date", metavar="YYYY-MM-DD", help="Refresh one edited route JSON")
    action.add_argument("--show", metavar="YYYY-MM-DD", help="Show one day's stops and transport without dumping geometry")
    action.add_argument("--check-all", action="store_true", help="Validate all existing daily route files")
    args = parser.parse_args()
    try:
        if args.bootstrap:
            bootstrap()
        elif args.show:
            show_day(args.show)
        elif args.check_all:
            check_all()
        else:
            update_day(args.date)
    except RouteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
