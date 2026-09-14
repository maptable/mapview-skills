# Cookbook — end-to-end examples

Complete pipelines for common map tasks. Each example shows **both** the CLI commands (`scripts/mapview_cli.py`) and the equivalent MCP tool calls. Assume an access token is configured (MCP client or an earlier `login`).

## 1. Region choropleth — total sales by province (admin1)

User: "Make a map of total sales by province from this CSV."

Data: `province` (text, Chinese), `sales` (number).

**MCP:**
```
1. region_match
   items: [{admin1: "<province>", country: "CN"} for each province]
   → collect UIDs (watch for ambiguous/empty)

2. Build columns (the ORIGINAL column rides alongside the derived UID column —
   it feeds fieldMappings.regionColumns, slicers and popup cards):
   - {id: "province", name: "省份", type: "singleChoice"}         // original
   - {id: "region", name: "Province UID", type: "multiLineText"} // derived, holds UIDs
   - {id: "sales", name: "Sales", type: "number"}

3. Build rows: one per data row
   - {cells: {province: "<name>", region: "<uid>", sales: <value>}}
   // repeated provinces are fine — the map sums them via aggregateMethod
   // at render time; don't group/total the data yourself

4. create_map {name: "Sales by Province"}  → mapId, shareUrl

5. add_layer {
     mapId, layerType: "region",
     columns, rows,
     fieldMappings: {regionColumn: "region", regionColumns: {admin1: "province"}, colorColumn: "sales"},
     styleValues: {
       aggregateMethod: "sum",
       fillMethod: "quantile",
       colors: ["#eff3ff","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#084594"],
       regionLevel: "admin1"
     }
   }  → layerId

6. Return the share link: the `shareUrl` field from the tool response (server-derived)
   (when the host client supports inline web-page display, the share URL can
   also be embedded directly instead of a bare link)
```

**CLI:**
```bash
# 1. region_match (save items to items.json: {"items":[{"admin1":"广东省","country":"CN"},...]})
python3 mapview_cli.py region_match --input items.json > uids.json

# 4. create_map
python3 mapview_cli.py create_map --name "Sales by Province" > map.json
# extract mapId from map.json

# 5. add_layer (build layer.json per the structure above + styleValues)
python3 mapview_cli.py add_layer --input layer.json
```

> **Table also carries 城市/区县 columns? Keep them — even for this province view** (展示到省 ≠ 只传省数据): put them in the same region_match items (admin2/admin3) and upload the rows as they are, keeping `regionLevel: "admin1"`. The overview looks identical — the map truncates the fine UIDs itself — but every province now drills into its cities/districts; province-only rows can never drill. (City-map recipe: example 4. Swap colors per visualization.md.)

## 2. Region choropleth — global metric by country (admin0)

User: "Make a map of GDP by country."

Data: `country` (country name), `gdp` (number).

```
1. region_match
   items: [{admin0: "<country>"}]
   → country-level UIDs (L0, e.g. rg:cn, rg:us)

2. columns:
   - {id: "region", name: "Country", type: "multiLineText"}
   - {id: "gdp", name: "GDP", type: "number"}

3. rows: one per data row {cells: {region: "<uid>", gdp: <value>}}

4. create_map → mapId

5. add_layer {
     mapId, layerType: "region",
     columns, rows,
     fieldMappings: {regionColumn: "region", colorColumn: "gdp"},
     styleValues: {
       aggregateMethod: "sum",
       fillMethod: "quantile",
       colors: ["#eff3ff","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#084594"],
       regionLevel: "admin0"
     }
   }
```

**CLI:** same pattern as example 1 — `region_match --input items.json`, `create_map`, `add_layer --input layer.json` (with `regionLevel: "admin0"`).

Mixed countries or unrecognized names in the rows? The map infers the dominant country itself and falls back to a world (admin0) overview when no country dominates — upload the rows as they are; never force a phantom admin1.

## 3. Region choropleth — store count per province (no metric column)

User: "Show how many stores we have in each province."

Data: only `province` names, one row per store.

```
1. region_match → UIDs (one per store row; repeated provinces are fine —
   the map counts them at render time)

2. columns:
   - {id: "region", name: "Province", type: "multiLineText"}

3. rows: one per store, {cells: {region: "<uid>"}}

4. create_map → mapId

5. add_layer {
     mapId, layerType: "region",
     columns, rows,
     fieldMappings: {regionColumn: "region"}   // no colorColumn
   }
   // count is forced; each region colors by store count
```

## 4. Region choropleth — one province's cities (regionId focus)

User: "Show me Guangdong's city-level sales." — a region focus inside one province.

Data: `city` (Chinese names), `sales` (number). No coordinates.

```
1. region_match
   items: [{admin1: "广东省", admin2: "<city>", country: "CN"}]
   → city-level UIDs (L2, e.g. rg:cn.guangdong.shenzhen)

2. columns:
   - {id: "city", name: "City", type: "singleChoice"}         // original → regionColumns.admin2
   - {id: "region", name: "City UID", type: "multiLineText"}  // derived, holds UIDs
   - {id: "sales", name: "Sales", type: "number"}

3. rows: one per data row {cells: {city: "<name>", region: "<uid>", sales: <value>}}
   (repeated cities are fine as separate rows — the map sums them at render
   time via aggregateMethod; pre-aggregate only near the row quota)

4. create_map → mapId

5. add_layer {
     mapId, layerType: "region",
     columns, rows,
     fieldMappings: {regionColumn: "region", regionColumns: {admin2: "city"}, colorColumn: "sales"},
     styleValues: {
       aggregateMethod: "sum",
       fillMethod: "quantile",
       colors: ["#eff3ff","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#084594"],
       regionLevel: "admin2",
       regionId: "rg:cn.guangdong"
     }
   }
   // the ask is a city map → render at admin2 (admin1 would roll cities up
   // into a drillable province overview, coarser than requested);
   // regionId focuses the layer on Guangdong —
   // the viewport auto-fits to it, so the map opens on the province, not China.
```

**CLI:** same pattern as example 1 — `region_match --input items.json`, `create_map`, `add_layer --input layer.json` (with `regionLevel: "admin2"` + `regionId`).

## 5. Region choropleth — district level (区县级, admin3)

Same pipeline as example 1 — only the match input and `regionLevel` change:

1. `region_match` items carry every admin column the table has (省份 → `admin1`, 城市 → `admin2`, 区县 → `admin3`):
   `[{admin1: "广东省", admin2: "深圳市", admin3: "罗湖区", country: "CN"}, ...]`
   → one L3 UID per row (`rg:cn.guangdong.shenzhen.luohu` — a UID is self-contained, it already carries its city and province).
2. `add_layer` exactly as example 1, but with `regionColumns: {admin1: "province", admin2: "city", admin3: "district"}` (declare every level the table carries) and `regionLevel: "admin3"`.

The same L3 rows serve coarser asks too: `regionLevel: "admin1"`/`"admin2"` renders the province/city overview, and clicking a region drills back down to 区县.

## 6. Point map — store locations with addresses

User: "Plot all our stores on a map."

Data: `name`, `address` (street text), no coordinates.

```
1. geocode {addresses: [<address per store>], country: "CN"}   // quota-metered, misses included: one heads-up to the user per session
   // (get_quota shows the balance)
   → [{lng, lat}, ...]; handle nulls (tighten address or drop)

2. Build columns:
   - {id: "name", name: "Store", type: "multiLineText"}
   - {id: "lng", name: "Longitude", type: "number"}
   - {id: "lat", name: "Latitude", type: "number"}

3. Build rows: one per store
   - {cells: {name: "<name>", lng: <lng>, lat: <lat>}}

4. create_map {name: "Store Locations"}  → mapId

5. add_layer {
     mapId, layerType: "icon",          // "icon" = marker shapes; "point" = plain circles
     columns, rows,
     fieldMappings: {
       longitudeColumn: "lng",
       latitudeColumn: "lat",
       labelColumn: "name"
     },
     styleValues: { icon: "location", radius: 20 }   // icon default is 20 (renders ×1.6 ≈ 32px)
   }  → layerId
```

**CLI:**
```bash
python3 mapview_cli.py geocode --addresses "addr1" "addr2" --country CN > geocoded.json
python3 mapview_cli.py create_map --name "Store Locations" > map.json
python3 mapview_cli.py add_layer --input layer.json
```

**Variant — the table already carries coordinates** (skip geocode, but check the coordinate system). The map renders WGS84 only; geolocation fields from 飞书多维表格 / 钉钉 / 企业微信 / 腾讯文档 (and Amap/Tencent data) are GCJ-02, Baidu's is BD-09 — submitted raw, every point lands 100–700 m off with no error. Convert locally first (no API call, no token):

```bash
# records.json carries the two number columns lng/lat (numbers or numeric strings)
python3 mapview_cli.py convert-coords --from gcj02 --input records.json --lng-col lng --lat-col lat
# one combined "lng,lat" string column keeps its string shape
python3 mapview_cli.py convert-coords --from bd09 --input records.json --coord-col location
# single point (e.g. before update_map --center)
python3 mapview_cli.py convert-coords --from gcj02 --lng 116.410244 --lat 39.916405
```

Then build rows from the converted file as usual. `geocode` output is already WGS84 — never convert it again. One boundary: the conversion rule is certain only for **geolocation fields** and known map-service sources; plain lng/lat number columns of unknown origin could be either system — ask the user where they came from, or submit as WGS84 and state that assumption, rather than converting blindly.

## 7. Heatmap — incident density

User: "Show where incidents are concentrated."

Data: many rows with lng/lat (or addresses), no per-point metric.

```
1. If addresses: geocode first → lng/lat columns.
   If already have lng/lat: skip.

2. columns:
   - {id: "lng", name: "Longitude", type: "number"}
   - {id: "lat", name: "Latitude", type: "number"}
   - {id: "weight", name: "Weight", type: "number"}   // all 1 for pure density

3. rows: one per incident
   - {cells: {lng, lat, weight: 1}}

4. create_map {name: "Incident Density"}  → mapId

5. add_layer {
     mapId, layerType: "heatmap",
     columns, rows,
     fieldMappings: {
       longitudeColumn: "lng",
       latitudeColumn: "lat",
       weightColumn: "weight"
     },
     styleValues: { radius: 35 }     // default 20; raise if the heat looks faint
   }  → layerId
```

## 8. Multi-layer map — stores (points) + sales (regions)

User: "Show store locations and regional sales on one map."

```
1. Prep both geometries:
   - geocode store addresses → lng/lat
   - region_match province names → UIDs

2. create_map {name: "Stores and Regional Sales"}  → mapId

3. add_layer (layer 1: regions)
   layerType: "region", fieldMappings: {regionColumn, colorColumn: "sales"},
   styleValues: {aggregateMethod: "sum"}

4. add_layer (layer 2: points, same mapId)
   layerType: "icon",
   fieldMappings: {longitudeColumn, latitudeColumn, labelColumn: "name"},
   styleValues: { icon: "location" }
```

Two layers, one map. The server appends each layer to the same map; later layers render on top.

Complementary geometries like this stack well. But several indicators of the SAME regions (e.g. sales, store count, and population — all by-province choropleths) are alternatives, not complements: stacked, the top one just hides the rest. Create those with `comparison: true` on each layer (at add_layer, or later via update_layer) — they become a single-select group (单选): the viewer sees one at a time and switches between them in the legend.

## 9. Managing maps — list, inspect, update, delete

User: "What maps do I have?" / "Show me the layers on map 42." / "The layer I just added is wrong — fix it." / "Add the October rows to the sales layer." / "Switch the basemap to dark."

These tools need no geometry prep — they operate on maps that already exist. Which map to write into is a scope decision, not a habit: within one conversation keep adding layers to the same map; on a fresh request check `list_maps` first — nothing related → create a new map, a related map found → ask the user whether to add to it or to create a new one (a name match alone is not permission to write).

**list_maps** — discover your maps and their layer counts:
```
list_maps  → [{mapId, name, desc, layerCount, updateTime}, ...]
```
CLI: `python3 mapview_cli.py list_maps`

**get_map** — inspect one map (recover share link, layer list with types + row counts, current basemap/viewport):
```
get_map {mapId: 42}
  → {mapId, name, desc, shared, shareUrl, baseMap, center, zoomLevel, layers: [{layerId, name, layerType, rowCount}, ...]}
```
CLI: `python3 mapview_cli.py get_map --map-id 42`

**update_map** — map-level settings, including the share link:
```
// publish a map that is not shared yet — web-editor maps default to unshared
// (create_map maps are shared from the start); the response reports shared + shareUrl
update_map {mapId: 42, share: true}
```
CLI: `python3 mapview_cli.py update_map --map-id 42 --share on`

**update_layer** — fix or extend a layer in place. Six independent concerns; pass only what changes:
```
// restyle only (same vocabulary as add_layer; unmentioned fields keep their values)
update_layer {mapId: 42, layerId: "<id>", styleValues: {colors: ["#...","#...","#..."], fillMethod: "quantile"}}

// append incremental rows (id-less rows get generated ids — read them back via get_layer_data).
// fieldMappings is optional on add_layer-created layers (they remember their recorded mapping —
// get_map shows it); only layers created before recorded mappings existed need it re-passed,
// e.g. fieldMappings: {regionColumn: "region"} on legacy region layers:
update_layer {mapId: 42, layerId: "<id>", mode: "append", rows: [{cells: {...}}, ...]}

// upsert by row id: provided fields overwrite, unmentioned fields survive
update_layer {mapId: 42, layerId: "<id>", mode: "upsert", rows: [{id: "row-7", cells: {sales: 999}}]}

// full reload (style is inherited; pass styleValues to change it)
update_layer {mapId: 42, layerId: "<id>", mode: "replace", columns: [...], rows: [...], fieldMappings: {...}}

// rename
update_layer {mapId: 42, layerId: "<id>", name: "Q4 Sales"}

// move within the layer order (top renders above the other layers; the bottom
// position is the default view for comparison groups)
update_layer {mapId: 42, layerId: "<id>", order: "top"}
```
CLI: `python3 mapview_cli.py update_layer --map-id 42 --layer-id "<id>" --mode upsert --input fixes.json`

**get_layer_data** — read stored rows back (verify writes, recover generated ids, fetch full rows before an upsert):
```
get_layer_data {mapId: 42, layerId: "<id>", ids: ["row-7", "row-8"]}
  → {columns, rows: [{id, cells}], total, offset, limit}
```
CLI: `python3 mapview_cli.py get_layer_data --map-id 42 --layer-id "<id>" --ids row-7 row-8`

**update_map** — map-level settings (name/desc/basemap/viewport):
```
update_map {mapId: 42, baseMap: "dark", center: "116.4,39.9", zoom: 4}
  → full map state (same shape as get_map)
```
CLI: `python3 mapview_cli.py update_map --map-id 42 --base-map dark --zoom 4`

**delete_layer** — remove a layer entirely (data files included). Prefer update_layer for corrections; delete only when the layer should not exist at all:
```
delete_layer {mapId: 42, layerId: "<id>"}  → {deleted: true, layerId, remainingLayers: N}
```
CLI: `python3 mapview_cli.py delete_layer --map-id 42 --layer-id "<id>"`

## 10. Point layer with photo covers

User: "Plot my stores on a map and show a photo of each store in the popup."

Data: a CSV of stores (`name`, `address`) plus image files on disk. Many rows, few unique images — several stores share the same chain photo, so **dedupe first**: the pattern is collect unique images → upload once → reuse fileIDs across rows.

**MCP:** (local-file upload works from either side — the CLI `upload` command, or `upload_file` with base64 `data` scripted from bash; the example keeps the CLI)
```
1. geocode {addresses: [...], country: "CN"}  → lng/lat per store

2. create_map {name: "Stores"}  → mapId

3. Collect the UNIQUE images from the CSV's photo column (same file referenced
   by many rows = ONE upload). Upload them once, batched:
   CLI: python3 mapview_cli.py upload <mapId> store-a.jpg store-b.png
   → one fileID per file; build a  filename → fileID  mapping
   (every upload stores a NEW object — re-uploading the same image per row
   wastes storage and cannot be deduped)

4. columns:
   - {id: "name", name: "Store", type: "multiLineText"}
   - {id: "lng", name: "Longitude", type: "number"}
   - {id: "lat", name: "Latitude", type: "number"}
   - {id: "photo", name: "Photo", type: "attachment"}

5. rows: one per store; rows sharing an image reuse the SAME fileID
   (≤5 per cell):
   - {cells: {name: "朝阳店", lng: 116.4, lat: 39.9, photo: ["<fileID-a>"]}}
   - {cells: {name: "海淀店", lng: 116.3, lat: 40.0, photo: ["<fileID-a>"]}}   // same image
   - {cells: {name: "浦东店", lng: 121.5, lat: 31.2, photo: ["<fileID-b>"]}}

6. add_layer {
     mapId, layerType: "icon",
     columns, rows,
     fieldMappings: {longitudeColumn: "lng", latitudeColumn: "lat"}
   }  → layerId

7. update_layer {
     mapId, layerId,
     infoWindow: {coverColumn: "photo", titleColumn: "name", visibleColumns: ["photo"]}
   }  → shareUrl
   // coverColumn must be an attachment column; visibleColumns must not
   // include titleColumn. Point/icon layers only — region popups aggregate
   // rows and carry no attachments.
```

**CLI:**
```bash
python3 mapview_cli.py geocode --addresses "addr1" "addr2" --country CN > geo.json
python3 mapview_cli.py create_map --name "Stores" > map.json
python3 mapview_cli.py upload 123 store-a.jpg store-b.png    # unique images only, once
python3 mapview_cli.py add_layer --input layer.json
python3 mapview_cli.py update_layer --map-id 123 --layer-id "<id>" --input card.json
# card.json: {"infoWindow": {"coverColumn": "photo", "titleColumn": "name", "visibleColumns": ["photo"]}}
```

Verify or reconfigure the card later — `get_map` (per layer) and `get_layer_data` read back the current `infoWindow` (coverColumn, titleColumn, visibleColumns).

## Building payloads with the local formatters

Hand-assembling columns + rows JSON is the error-prone step — use the CLI's local builders instead (no request, no token; output is the canonical JSON every channel accepts):

```bash
# CSV in hand → whole payload body in one shot
python3 mapview_cli.py fmt-csv --file stores.csv --id index > body.json

# Structured datasource (e.g. Bitable fields carry their own ids)
echo '[{"id": "fldSales", "name": "销售额", "type": "number"},
       {"id": "fldName",  "name": "门店"}]' | python3 mapview_cli.py fmt-columns > columns.json
echo '[{"id": "row-1", "fldName": "朝阳店", "fldSales": 6573}]' \
  | python3 mapview_cli.py fmt-rows --columns columns.json > rows.json

# Appending to an existing layer: the stored columns are the baseline
python3 mapview_cli.py get_layer_data --map-id 42 --layer-id "<id>" > stored.json
echo '[{"id": "row-1", "<stored column id>": 9999}]' \
  | python3 mapview_cli.py fmt-rows --columns stored.json   # → canonical upsert rows

# GCJ-02/BD-09 coordinates (Chinese table apps' geolocation fields) → WGS84, locally
python3 mapview_cli.py convert-coords --from gcj02 --input records.json --lng-col lng --lat-col lat
```

Column ids come from your data and pass through verbatim (datasource id, index, or unique name — the builders never invent ids, so datasource↔column matching survives every update). Structural mistakes (unknown row keys, duplicate ids, ragged CSV lines) and vocabulary violations (unknown types, hex choice colors) fail locally with actionable messages, before anything is submitted.

## Handling problems mid-pipeline

| Problem | Fix |
|---|---|
| Some region_match UIDs are empty | Retry those items with more admin context; if still empty, drop the row or ask the user. Don't send empty UIDs to `add_layer` — they render as blank regions. |
| Some region_match results are `ambiguous: true` | Verify the UID against the user's intent; re-run with `admin0`–`admin3` context to disambiguate. |
| Some geocode results are null | Tighten the address, try a coarser form, or drop the row. Don't retry the identical string. |
| Points land 100–700 m off in China | The source coordinates are GCJ-02 (Chinese table apps' geolocation fields, Amap/Tencent) or BD-09 (Baidu) — convert to WGS84 with `convert-coords` before submitting. No server error flags this; judge by the data source. |
| `boundaryAvailable: false` on a region | That region has no geometry; it can't render. Drop it or find an alternative (e.g. parent region). |
| More than 10000 rows | Aggregate first (sum/mean by region), or split into multiple layers. |
| `create_map` name-duplicate concern | None — duplicate names are allowed; maps are addressed by `mapId`. Add a suffix only if the user asks. |
| Over-quota error on rows | Aggregate by region, or split into multiple maps. |
| Mixed point + region data in one sheet | Split into two `add_layer` calls on the same mapId (see example 8). |
| A layer rendered wrong (bad data/mapping) | `get_map` to find its `layerId`, then `update_layer` — restyle in place, `mode: upsert` to fix rows by id, or `mode: replace` to reload the data (style is inherited). `delete_layer` only when the layer should not exist. |
| Forgot a mapId or share link | `list_maps` to see all maps, or `get_map {mapId}` to recover the `shareUrl`. |
| Changes not visible in the open web editor | The editor does not live-refresh from external writes — reload the page. The share link always shows the latest state. |
