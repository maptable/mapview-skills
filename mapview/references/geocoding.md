# Geocoding

`geocode` resolves street addresses to lng/lat coordinates. Use this **before** `add_layer` when your data has address text but no coordinates, and the target `layerType` is `point` / `icon` / `heatmap`. Region layers do not need geocoding — they use region UIDs from `region_match`.

## Behavior

- **Quota-metered — tell the user first.** Every call consumes the workspace's geocoding quota, including calls that resolve nothing. Before the first geocode of a session (and when resuming a large multi-batch job), say so to the user — `get_quota` shows the remaining balance.
- **Map API only, no AI fallback.** The server calls the mapping service (amap for domestic/CN, Mapbox otherwise) and returns what it resolves. There is no LLM rescue step. A `null` result is a definitive miss from the Map API.
- Up to **100 addresses** per call. Split larger batches; merge results by index.
- Returns one `{lng, lat}` per input, in input order. `null`/`null` where unresolved. **Output is already WGS84** — feed it into `add_layer` without conversion.
- `usage` reports `{success, failed, overQuota, remaining, limit}`.

## When to geocode vs not

| Data has | Action |
|---|---|
| lng + lat columns | Skip geocode — but settle the coordinate system first, by **where the values live**. **Geolocation fields** (飞书多维表格/钉钉/企业微信/腾讯文档 地理位置 fields) and Amap/Tencent data are GCJ-02, Baidu's is BD-09 — convert with `python3 mapview_cli.py convert-coords` or points land 100–700 m off. **Plain number columns** of unknown origin could be either system — ask the user where the coordinates came from, or submit them as WGS84 and state that assumption; never convert blindly. |
| Street addresses | geocode → write lng/lat into number columns |
| Region names only | Don't geocode. Use `region_match` → region layer. |
| Region names + you want points | geocode the region names (returns a representative point) — but a region layer is usually better. |

## Address formatting

The Map API is tolerant, but precision helps:

- **Include hierarchy:** "广东省深圳市罗湖区宝安南路2014号" beats "宝安南路2014号".
- **Local language preferred:** Chinese addresses in Chinese, Japanese in Japanese. English transliteration reduces accuracy.
- **Avoid noise:** strip store names, marketing copy, transit directions in parentheses unless they disambiguate. "广东深圳罗湖宝安南路2014号振业大厦A座13A" is fine; the landmark helps.
- **Punctuation:** standard address punctuation is fine. Don't URL-encode.

## Country code

Pass `country` (ISO alpha-2) when you know it. It is forwarded as a `country=` filter to **Mapbox v6** only, which scopes the search and improves precision. The **amap** engine (used for CN deployments) ignores it — amap infers scope from the address text itself.

| Value | Effect |
|---|---|
| `"CN"` | amap ignores it; Mapbox scopes to China |
| `"US"` | Mapbox scopes to United States |
| `"JP"` | Mapbox scopes to Japan |
| (omit) | Mapbox searches globally — slower and less precise |

The engine is chosen by the deployment platform (地图视图 domestic → amap; international → Mapbox v6), not by the `country` value. You don't pick the engine.

## Handling nulls

A `null` means the Map API could not resolve the address. **Do not retry the same string** — the result is deterministic. Options, in order of preference:

1. **Tighten the address:** add province/city/district if missing, fix typos, remove non-address tokens.
2. **Try a coarser form:** if a full address fails, the district/city alone often resolves and still gives a usable point.
3. **Drop the row** if the location is unimportant, or **ask the user** if it is.

After geocoding, write the resolved `{lng, lat}` into two number columns in your rows (e.g. `lng` and `lat`), then map them in `add_layer` via `longitudeColumn` / `latitudeColumn`.

## Quota

Each geocode call consumes the workspace's geocoding quota (charged per call, including unresolved addresses). `usage.overQuota: true` means the org is over limit — subsequent calls may be rejected. Surface this to the user; don't silently retry.
