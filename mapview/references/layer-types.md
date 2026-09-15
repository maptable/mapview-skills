# Layer types, field mappings, and styles

How to pick `layerType`, fill `fieldMappings`, and choose `styleValues` for `add_layer`.

## Choose layerType

| Data shape | User wants | layerType | Geometry prep |
|---|---|---|---|
| lng/lat per row | individual markers (clearer) | `icon` | none |
| lng/lat per row | individual points (plain circles) | `point` | none |
| Street addresses | individual markers/points | `icon` / `point` | `geocode` first |
| Many points, show density | heat/intensity areas | `heatmap` | `geocode` if addresses |
| Region names/UIDs, aggregate a metric | colored regions (choropleth) | `region` | `region_match` first |
| Existing GeoJSON point geometry | points | `point` | parse coordinates → lng/lat columns |

**Prefer `icon` over `point`** — marker shapes (location pin, bus, cafe…) are far more legible than plain dots. `point` (plain circles) is the fallback when no icon fits.

**One layer = one geometry kind (and typically one metric).** For a map with both points and regions — or several metrics/indicators of the same data — create multiple layers on the same mapId rather than separate maps. Layers stack in call order (later layers render on top), and the viewer can show/hide each in the share page's layer panel.

## Recognizing column roles

When you receive data, identify each column's role by name/content. Common column-name keywords:

| Role | Common name keywords | Column type |
|---|---|---|
| Longitude | lng, lon, longitude, x | number |
| Latitude | lat, latitude, y | number |
| Geolocation field (Chinese table apps' 地理位置 field) | location, 地理位置, 坐标, coordinate | multiLineText (cells hold a `"lng,lat"` string) |
| Address | address, addr, location* | multiLineText |
| Region name | province, city, state, region, country, district, county, 区县, 行政区划 | multiLineText |
| Numeric metric | sales, amount, count, total, revenue, gdp, population | number |
| Category | type, category, industry | `singleChoice` (low-cardinality) |
| Label | name, title | multiLineText |

\* "location" is ambiguous by name alone — **check the cell content**: a `lng,lat` number pair is a geolocation field (coordinates), street text is an address. A geolocation field from a Chinese table app is **GCJ-02** — run `convert-coords --coord-col <col>` (or `--lng-col`/`--lat-col` after splitting) BEFORE add_layer, per the Skill's WGS84 rule; never send it to geocode.

**Conflict resolution:**
- Both lng/lat columns AND an address column → prefer lng/lat (more precise), unless the user explicitly wants address geocoding.
- A "location"/地理位置 column whose cells are `lng,lat` pairs → treat as coordinates (convert-coords → two number columns), not as an address for geocoding.
- Multiple region columns (province/city/district — Chinese tables: 省份 → admin1, 城市 → admin2, 区县 → admin3) → pass **all of them** to `region_match` (each name in its `adminN` field — the finer ones also serve as disambiguating context), then declare per-level UID columns via `fieldMappings.regionColumns`. Match at the finest granularity the data carries even when the requested view is coarser: the requested aggregation level is a `regionLevel` (view) setting, never a reason to drop finer columns — drill and editor level switching run on the finer UIDs.
- Unsure if address vs region name → check content: street/house numbers = address; only province/city/country names = region name.
- Numeric vs category → check content: all numbers = numeric; limited discrete text = category.

## fieldMappings by layerType

`fieldMappings` maps your column IDs to layer roles. Every referenced column ID must exist in `columns`.

### point / icon

`point` and `icon` share identical fieldMappings (lng/lat required). `point` renders plain circles; `icon` renders built-in marker shapes — usually clearer. Pick the marker via `styleValues.icon`.

| Field | Required | Role |
|---|---|---|
| `longitudeColumn` | yes | Longitude number column |
| `latitudeColumn` | yes | Latitude number column |
| `colorColumn` | no | Column driving marker fill color |
| `labelColumn` | no | Column shown as label (non-empty enables labels) |

### heatmap

| Field | Required | Role |
|---|---|---|
| `longitudeColumn` | yes | Longitude numbers |
| `latitudeColumn` | yes | Latitude numbers |
| `weightColumn` | yes | Column driving heat intensity |
| `labelColumn` | no | Column shown as label |

### region

| Field | Required | Role |
|---|---|---|
| `regionColumn` | yes | **Must hold region UIDs** (from `region_match`), not names — ONE UID per row, the deepest level its match resolved (a UID is self-contained: its parents are recovered by truncation, so don't also store the same region's parent UIDs; mixed depths across rows are fine). This column is what resolves, renders and drills every row. |
| `regionColumns` | no | Per-level **ORIGINAL name columns** `{admin1?, admin2?, admin3?}` for tables that carry one column per level — the 省份 column as `admin1`, 城市 as `admin2`, 区县 as `admin3`. Declare **every level the table carries, no more** (a province-only table declares just admin1; never fabricated, and never dropped just because the requested view is coarser). They never hold UIDs and take no part in aggregation, rendering or matching — display and filter wiring only: they populate the web editor's region-panel column configuration and are the columns slicers bind to, while resolution, aggregation and drill run on `regionColumn` alone. |
| `colorColumn` | no | Column driving per-region fill statistic (aggregated by `aggregateMethod`). Omit for a count-of-rows map. |
| `labelColumn` | no | Column shown as label |

Every row written to a region layer (add_layer, update_layer append/upsert/replace) must resolve to a UID through these columns — a row that resolves to none renders nowhere, so the write is **rejected with the row ids named**. On upserts the check runs on the merged row: omitting the region columns is fine when the stored row already carries them. `get_layer_data` reads each row back with its resolved `regionUid`. The coordinate column behind placement is server-internal; declaring it or writing its cell is rejected as reserved.

## styleValues

Optional, but usually worth setting for a meaningful map. Omit entirely to use defaults.

### aggregateMethod — how rows in the same group combine

Pick by **data semantics**, not by layer type:

| Metric meaning | aggregateMethod | Example |
|---|---|---|
| Totals (sum of values) | `sum` | total sales per province |
| Averages / rates | `mean` or `median` | avg income, population density |
| Extremes | `max` or `min` | peak temperature, lowest price |
| Occurrences / counts | `count` | number of stores per region |
| Non-empty values | `nonEmptyCount` | filled responses per region |
| Distinct text values | `uniqueValues` | categories present per region |

Notes:
- `point` / `icon` / `heatmap` support `sum`/`mean`/`median`/`max`/`min`. Count-like values fall back to `sum`.
- `region` supports the full list. When `colorColumn` is omitted on a region layer, `count` is forced (rows per region).
- **How to tell total vs rate:** column name/unit contains rate/density/per-capita/%/avg → `mean`/`median`; contains amount/total/sales/count → `sum`; just occurrence count → `count`.

### regionLevel — region layer render granularity (region only)

| regionLevel | Granularity | Notes |
|---|---|---|
| `admin0` | country | UIDs truncated to country level. For global choropleth (one color per country). |
| `admin1` (default) | province/state | UIDs truncated to province/state. For province-level maps. |
| `admin2` | city/county | UIDs truncated to city/county. For city-level maps. |
| `admin3` | district | UIDs truncated to district. For district-level maps. Level-3 boundaries are country-dependent — `region_match` reports whether each district resolved; rows without a level-3 UID stay empty. |

UIDs are truncated to regionLevel before rendering, so regionLevel sets the **overview** level: it may equal or be coarser than your `region_match` granularity, never finer. City-matched UIDs + `admin2` → city map; the same UIDs + `admin1` → province map; district-matched UIDs + `admin3` → district map.

**The requested aggregation level is a view setting, not a data-prep decision — a province VIEW never means province-only DATA (展示到省 ≠ 只传省数据): district/city rows uploaded as-is still render the province overview (the map truncates their UIDs), and they are what makes it drillable.** When the user asks for a province map ("按省聚合") from data that also carries city/district columns, do NOT re-match at province level — match every level the table carries (admin1+admin2+admin3 together), upload the per-level UID columns, and set `regionLevel: "admin1"`. Rendering rolls the fine UIDs up to the overview automatically, while the finer UIDs stay available for drill and for switching the display level in the web editor; a province-only match permanently loses both. That full-granularity match is the high-priority default whenever the table carries finer columns — and when you cannot tell whether they are matchable, ask the user whether to include them for drill instead of quietly building the coarse-only layer.

**Drill down replaces extra layers.** A region layer drills down to the granularity its UIDs carry: render city-matched UIDs at `admin1` and clicking a province drills into its cities; the breadcrumb drills back up. The prerequisite is the match: province-matched UIDs never drill into cities — if city-level detail is wanted, the rows must carry admin2 UIDs from `region_match`. So "province overview with city detail on demand" is **one layer** — match to the finest granularity the data has, set `regionLevel` to the overview level, and let the user drill. Don't stack a second finer-grained layer for the detail: it draws both levels at once, duplicates rows, and competes with the drill instead of feeding it.

### regionId — focus a sub-country region (region only, admin1/admin2)

Optional. Defaults to the country inferred from the rows (whole-country view). Pass a **UID from `region_match`** to focus the layer on one region:

| Value | Effect |
|---|---|
| `"rg:cn"` | Whole China (same as default for Chinese rows) |
| `"rg:cn.hebei"` | Province-level focus: viewport opens on Hebei; admin2 city layers filter to Hebei's cities |
| `"china"` | Plain country name — only use it when the rows ARE that country: it fixes the boundary source without pinning a region. Rows from a different country will not match any boundary (empty render). Prefer the `rg:` form. |

The country is derived from the UID prefix (so `rg:us.california` implies `usa`). The map's initial viewport auto-fits to the region's bbox, so a single-province layer opens on that province, not all of China. Useful when rows are sparse or when you want one province/city of a country. See [region-matching.md](region-matching.md) for the China province UID list.

### fillMethod — how values map to colors

| fillMethod | When to use |
|---|---|
| `quantile` (default) | Skewed data (most real-world metrics). Equal-count groups → each color band has roughly the same number of regions. |
| `quantize` | Uniformly distributed data. Equal-range linear splits. |
| `ordinal` | Categorical data (text categories, discrete classes). |
| `customize` | Manual-threshold mode — pass the cut points via `styleValues.thresholds` (exactly `len(colors)-1` values, with a matching `colors` array). |

### colors

Hex string array, e.g. `["#0065ff"]` for points or `["#59eefb","#4dd6ef","#40bde3","#34a4d7","#278bca","#4566c4","#5a3fbe"]` for a region ramp. Omit to use the default palette for the layer type.

- **point/heatmap:** single color or small ramp.
- **region:** ordered ramp (light → dark) for sequential metrics; diverging palette only when the metric has a meaningful midpoint.

### icon — marker shape (`icon` layer only; default `location`)

Picks the built-in marker shape for `layerType: "icon"`. Pass the icon name string. Ignored for `point`/`region`/`heatmap`. 40 built-in icons across four families:

| Family | Icons |
|---|---|
| Basic | location, circle, square, diamond, triangle, cross, plus, flag, star, love |
| Transportation | airport, barrier, bicycle, bus, car, construction, entrance, racetrack, rail, warehouse |
| Facility | attraction, bridge, office, building, college, fuel, hardware, museum, parking, pharmacy |
| Commerce | bakery, bar, cafe, clothing, commercial, grocery, hairdresser, restaurant, square-star, suitcase |

Pick by data semantics (see [visualization.md](visualization.md)). Default `location` fits most place-based data (stores, offices, branches). Custom uploaded icons are not exposed via MCP/REST.

Only these 40 names render — an unknown name (e.g. a guessed `"pin"`) leaves the layer's markers blank on the map, so it is never stored: add_layer/update_layer replace it with `location` and report the repair in the response `warnings` (the CLI's local pre-flight warns and fixes it before the call too). Pick a real name from the table above instead of guessing one.

**Per-category icons:** to give each color band its own marker, pass `styleValues.icons` (an array aligned with `colors`) instead of a single `icon`. Pair it with a `colorColumn` (e.g. store type) + `fillMethod: "ordinal"` so each category lands a distinct color + icon. The frontend reads `icons[colorIndex]`, so `icons[i]` corresponds to `colors[i]`. Example: `colors: ["#e41a1c","#377eb8","#4daf3a"]` + `icons: ["restaurant","cafe","bar"]` → red restaurants, blue cafes, green bars. When `icons` is set it overrides `icon`. Unknown names in the array are replaced with `location` per entry (same warning mechanism as `icon`).

### radius — marker/heat size (`point`/`icon`/`heatmap`)

Circle radius, **0–100 px** by default. Defaults (match the frontend): `point` **10**, `icon` **20**, `heatmap` **20**. The frontend renders icon markers at radius × 1.6, so icons need a larger radius than plain circles to look comparable. If a heatmap looks faint or a point set looks crowded, adjust `radius`. Heatmap is always pixel-based (no meter mode).

**Meter mode (`point`/`icon` only):** pass `fixedToMeter: true` to interpret `radius` in meters on the ground (**0–5000**) — circles keep their real-world size while zooming instead of shrinking with the zoom level. Use it when the circle stands for a real distance (service radius, coverage, blast area), e.g. `radius: 500` + `fixedToMeter: true` for a 500 m catchment.

**Per-feature size by field (`point`/`icon`):** pair `fieldMappings.radiusColumn` (a number column) with `radiusRange` — the column's min/max values map linearly onto this `[min, max]` range. Pixels `0 < min < max ≤ 100` by default; meters `0 ≤ min < max ≤ 5000` with `fixedToMeter: true` (e.g. a sales column drives 100–2000 m circles). Default `[4, 40]`.

## Region-layer recipes — pick the layer, prep the data

The single most common decision: the user says "show me the data for Guangdong" — do you build a **region** layer or a **point** layer? Decide by what the data actually contains, then by what the user wants to see:

| The data has | User wants to see | Use |
|---|---|---|
| Region names (province/city/country) + a metric column (sales, population…) | Which region is high vs low — a comparison | **`region`** (choropleth) — match names to UIDs, no coordinates needed |
| Region names only, no metric | How many rows fall in each region (counts) | **`region`** with `colorColumn` omitted → per-region `count` |
| lng/lat or addresses per row | Where the individual places are | **`point`** / **`icon`** (markers) |
| lng/lat or addresses, many overlapping points | Density of activity | **`heatmap`** |
| Region names at district (L3) level | District-level (区县级) colors | **`region`** — match to `admin3` + `regionLevel: "admin3"`; level-3 boundaries are country-dependent, so geocode to a point only the districts that did not resolve |

**If the data has region names and no coordinates, a region layer is the only option** — do not invent coordinates to force a point layer. Conversely, if the data has lng/lat, prefer `point`/`icon`/`heatmap`; a region layer would discard the precise positions.

### Recipe: one province's cities ("show me Guangdong data")

1. **match** each city name → UID with `region_match` (`admin1: "广东省"` + `admin2: "深圳市"` → `rg:cn.guangdong.shenzhen`, L2).
2. **add_layer**: `layerType: "region"`, `regionColumn` = the UID column, `colorColumn` = the metric.
3. **styleValues**: `regionLevel: "admin2"` (the ask is a city map — `admin1` would roll cities up into a drillable province overview, coarser than requested), `regionId: "rg:cn.guangdong"` (focus — the viewport auto-fits to Guangdong), `aggregateMethod` per metric semantics (`sum` for totals, `mean` for rates).
4. If rows repeat the same city, leave them as-is — the map groups by UID and applies `aggregateMethod` at render time (pre-aggregate only near the 10000-row quota, and then at the finest matched grain).

### Recipe: whole-country provinces or global countries

1. Match to the finest granularity the data carries — provinces → L1, countries → L0 — even when the overview will be coarser.
2. Set `regionLevel` to the overview level: equal to or coarser than the match (city-matched UIDs at `admin1` render provinces and drill into cities on click). Finer than the match adds nothing.
3. Omit `regionId` for the whole-country view (the country is inferred from the rows).

### Optimization checklist (region layers)

- **Always go through `region_match`** — hand-typed UIDs are silently dropped, and names do not render. Verify no `ambiguous: true` / empty `uid` / `boundaryAvailable: false` results before `add_layer`. Read [region-matching.md](region-matching.md) for field choice and the China province UID list.
- **The map does the aggregation — don't pre-group rows yourself.** When a region repeats (same city in many rows), upload the rows as they are: the renderer groups them by their UID (truncated to the render level) and applies `aggregateMethod`. "按省聚合" is `regionLevel` + `aggregateMethod`, never agent-side computation — a self-aggregated province table can no longer drill into its cities, and duplicates the map's own rollup. The only reason to pre-aggregate is size: near the 10000-row/org-quota limit, aggregate at the grain you matched (the finest, never the overview level) — rendering still rolls the values up to coarser levels.
- **One layer covers multiple levels via drill.** Match to the finest granularity the data has and set `regionLevel` to the overview level — clicking a region drills into its sub-regions down to the UIDs' granularity. No second layer needed for the finer level. That is levels of the *same* metric; a *different* metric is a separate layer on the same map, not a separate map.
- **Use `regionId` to focus** a province/city when the data is sparse or regional — the initial viewport opens on that region instead of the whole country.
- **Pick `aggregateMethod` by metric semantics**, not by layer type: totals → `sum`, rates/averages → `mean`/`median`, extremes → `max`/`min`. Omit `colorColumn` only when you want row counts.
- **District (L3, 区县) ask → region layer at admin3.** Match to `admin3` and set `regionLevel: "admin3"` — level-3 boundaries are country-dependent, so check what region_match resolved; geocode the unresolved districts to a point layer (or render at `admin2`) only when they did not resolve.
- **One layer = one geometry kind.** A "stores as points + sales by province" view is two layers on the same mapId, not one mixed layer — and several indicators of the same regions (e.g. sales volume and store count by province) are also separate layers on one map, not separate maps.

## Limits

- ≤ **100 columns**, ≤ **10000 rows** per `add_layer` call (hard limits). Also subject to the org plan's per-map row quota, which may be much smaller; over-quota errors require aggregation or splitting maps.
- `rows[].id` is optional, auto-generated as a UUID when omitted. Ids let you target rows later — `update_layer` (`append`/`upsert` modes) adds or merges rows by id, and `get_layer_data` reads them back.
