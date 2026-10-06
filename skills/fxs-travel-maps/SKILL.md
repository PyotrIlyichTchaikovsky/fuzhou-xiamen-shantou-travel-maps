---
name: fxs-travel-maps
description: Maintain the existing 2026 福州—厦门—汕头 Notion itinerary and its GitHub Pages daily and city route maps. Use for changes to stops, order, transport, coordinates, map popups, or trip-day text for this trip; do not apply to the separate 江西 trip.
---

# 福州—厦门—汕头路线维护

This trip's existing Notion guide is `https://app.notion.com/p/3ee23b5de1fd812091e8f645e8400eaf?pvs=204`. Its thirteen daily maps (2026-10-11 through 2026-10-23) and three city maps are embedded from `https://pyotrilyichtchaikovsky.github.io/fuzhou-xiamen-shantou-travel-maps/travel/fuzhou-xiamen-shantou/embed-v2/`. The GitHub repository is `PyotrIlyichTchaikovsky/fuzhou-xiamen-shantou-travel-maps`. Local sources are in `H:\MyWork\Misc`.

The map is a static interactive MapLibre webpage, not a generated image. The permanent `embed-v2/*.html` pages load live daily route JSON from `travel/fuzhou-xiamen-shantou/routes/YYYY-MM-DD.json`. City maps load the same daily JSON. A routine route edit publishes only the affected JSON file; do not rebuild HTML, publish a new embed URL, or replace Notion embeds. `build_maps.py` and the original HTML files are legacy snapshots, not the source for future route edits.

## Routine route change

1. Fetch the existing Notion guide and read the requested date's detailed text. Run `fast_fxs_maps.py --show YYYY-MM-DD` for a compact stop, coordinate, and transport summary; inspect neighboring days only if needed. Honor an explicit request to propose a change before editing; stop after the proposal until the user approves.
2. Confirm the visit order and any fixed train, ferry, museum, or hotel commitments. For a new or moved stop, verify its actual entrance/observation point against reliable map and official sources. In JSON, coordinates are WGS84 `[longitude, latitude]`; convert GCJ-02 map coordinates before saving. Preserve `source` and `datum`. Avoid a broad area's center point when the visit is to a specific entrance or viewpoint.
3. Edit only `travel/fuzhou-xiamen-shantou/routes/YYYY-MM-DD.json`: `title`, `note`, ordered `points` (`name`, `coord`, `what`, `stay`, `source`, `datum`), and `modes`. Keep genuine alternatives optional. Run `fast_fxs_maps.py --date YYYY-MM-DD` from `H:\MyWork\Misc` to preserve unchanged route geometries and calculate only changed driving legs. The script must fail visibly if a new road leg cannot be routed; do not silently publish a straight driving line.
4. Run `fast_fxs_maps.py --check-all`, then check point order, named locations, each route segment's start/end proximity, and visual map fit. Inspect the date's live map at mobile width when the stop layout or route shape changed. Particular risk points: 福州烟台山、演武大桥观景平台、环岛路具体观景点、集美学村与鳌园.
5. Publish only that changed JSON with the GitHub connector: fetch its current file/blob SHA, then update the file on `main` with the verified UTF-8 JSON. Avoid force-moving refs. Confirm the public JSON and embedded daily map load; allow for GitHub Pages caching and reload the embed when checking. The city map reads this JSON automatically.
6. Use Notion's targeted content update for the affected day's text, transportation notes, and overview summary only where the itinerary actually changed. Preserve existing links, children, background colors, weather guidance, and city index. The fixed embedded map URLs stay as they are.

## UI or hosting change

Only when the map interface itself changes, edit `create_fast_fxs_shells.py` or the map templates, generate shells, and update the affected permanent `embed-v2/*.html` files. This is a rare bootstrap/UI operation, not part of routine route maintenance. Never put access tokens or passwords in public files. If publishing or login access is unavailable, prepare the exact local output and ask the user to complete browser login rather than requesting credentials in chat.

The separate Jiangxi itinerary is outside this skill and the user's current maintenance scope.
