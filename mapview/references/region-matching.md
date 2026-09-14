# Region matching

`region_match` resolves region names (by admin level) and coordinates to region UIDs. Pure programmatic matching (name rules + spatial index); no AI inference. Up to 100 items per call.

## UID format

```
rg:<country_iso>.<admin1>.<admin2>.<admin3>
```

Examples:

| UID | Level | Meaning |
|---|---|---|
| `rg:cn` | 0 | China (country root) |
| `rg:cn.beijing` | 1 | Beijing (province/municipality) |
| `rg:cn.beijing.beijing` | 2 | Beijing city |
| `rg:cn.beijing.beijing.chaoyang` | 3 | Chaoyang district |
| `rg:us.california` | 1 | California (state) |
| `rg:us.california.los-angeles` | 2 | Los Angeles County |
| `rg:de.bavaria` | 1 | Bavaria |

Level depth varies by country — not all countries publish all admin levels.

## Input fields

Each item combines any of these fields. At least one must be non-empty.

| Field | Bound level | Behavior |
|---|---|---|
| `admin0` | 0 | Country name (e.g. "China", "United States"). |
| `admin1` | 1 | State/province (e.g. "California", "广东省"). |
| `admin2` | 2 | County/city (e.g. "深圳市", "Los Angeles County"). |
| `admin3` | 3 | Sub-city/district name (区县, e.g. "罗湖区", "朝阳区"). |
| `country` | — | Optional ISO alpha-2 code (CN, US) to disambiguate. Inferred when omitted. |
| `longitude` + `latitude` | — | Point-in-region. Resolves to the most granular region containing the point. |

**`address` (free text) is NOT accepted.** Level-blind matching misresolves bare names — e.g. "河北省" fuzzy-matches Tianjin's 河北区 instead of Hebei province. Put every region name into the `adminN` field of its level (that binding is what makes the match precise); you decide the level, not the matcher. Street addresses ("北京市朝阳区望京街1号") belong to the `geocode` tool, not here.

## Field choice governs granularity

This is the most important decision. Pick fields by what you know and how precise the target is:

| You know | Recommended input | Why |
|---|---|---|
| A country name only | `admin0` | Lands at level 0. |
| A state/province | `admin1` + `country` | Lands at level 1. `country` disambiguates (e.g. "Georgia" the state vs the country). |
| A city/county | `admin2` + `admin0` or `country` | Lands at level 2. Provide parent context. |
| A district/neighborhood (区县) | `admin3` + `admin1`/`admin2` context | Level 3 needs an explicit `admin3`. `admin2` alone will **not** reach level 3. |
| Province + city + district columns (a multi-level table — Chinese tables: 省份 → `admin1`, 城市 → `admin2`, 区县 → `admin3`) | `admin1` + `admin2` + `admin3` together (+ `admin0`/`country` when present) | Pass **every** level the table carries, even when the requested view is coarser ("按省聚合"): parent context sharpens the match, and the finer UIDs stay drillable / level-switchable in the editor. The view level is `regionLevel` at add_layer — not a match decision. If you cannot tell whether the finer columns are matchable (mixed or messy values), ask the user whether to include them for drill instead of quietly dropping them. |
| A name whose level you're unsure of | Classify it yourself from context, then use that `adminN` field | The level binding is the precision mechanism — that judgment is yours to make. Full street addresses → `geocode`. |
| Coordinates | `longitude` + `latitude` | Resolves to the deepest available region containing the point. |

**Critical:** when matching Chinese districts/counties (level 3), put the district name in `admin3`, with province/city in `admin1`/`admin2` as context. Relying on `admin2` alone drops the district and resolves at the city level.

## Render granularity limit (region layers)

`add_layer` region layers support `regionLevel: admin0` (country), `admin1` (province/state, default), `admin2` (city/county), and `admin3` (district — where the data resolved at level 3). `regionLevel` is the **overview** level: UIDs are truncated to it for the initial render, but the layer drills down on click to whatever granularity its UIDs carry. Therefore:

- Global map → set `regionLevel: "admin0"`.
- Province map → `admin1` (default). Matching to districts (L3) or cities (L2) instead of provinces still renders a province map (展示到省 ≠ 只传省数据 — the map truncates the fine UIDs for the overview) — and makes each province drillable down to the matched level; province-matched rows can never drill.
- City map → match to city (L2) and set `regionLevel: "admin2"`.
- District map → match to district (L3) and set `regionLevel: "admin3"` (level-3 boundaries are country-dependent — check the region_match results).
- Match to the finest granularity the data actually carries — even when the user asks to aggregate by a coarser level (that is what `regionLevel` is for): coarser matches lose the drill detail; a `regionLevel` finer than the match adds nothing. A coarse-only match while finer columns exist is not the preferred default — when you cannot decide whether they are matchable, ask the user (offer the drill).
- Each row keeps a single UID: the deepest level its match resolved. UIDs are self-contained — `rg:cn.guangdong.shenzhen.luohu` already encodes its city and province, and the map truncates it for coarser views — so parent-level UIDs stored alongside add nothing.
- If the user wants district-level but the districts did not resolve at L3 (level-3 boundaries are country-dependent), fall back to a point layer (geocode the district name → point) or render at `admin2`.

## Result fields

| Field | Meaning | Action |
|---|---|---|
| `uid` | Resolved UID. Empty string = no match. | Empty → retry with more context, drop the row, or ask the user. |
| `level` | Admin level of the match (0–3). | Verify it matches the granularity you expected. |
| `boundaryAvailable` | Whether the region has boundary geometry. | `false` → cannot render on a region map; treat as unmatchable. |
| `ambiguous` | Multiple regions tied at equal strength. | `true` → `uid` is the best guess; **verify before use** (re-run with more admin context, or confirm with the user). |

## Per-country admin level support

The geo index covers the world at level 0 (country). Deeper levels vary. Common patterns:

| Country (ISO) | Typical max level | Notes |
|---|---|---|
| CN | 3 | Full province → city → district hierarchy. |
| US | 2 | State → county. |
| DE / IT / BR / JP / TH / MX / ID / MY / PH | 2 | ADM1 + ADM2. |
| GB / FR / ES / NL / BE / SE / FI / PL / PT / VN / CA / AT / EG / BD / PK | 2 | ADM2. |
| GR | 3 | ADM3 (municipalities/local islands). |
| SG | 1 | City-state. |

**About level fallback:** coordinates search within the country's deepest available level (over-depth auto-falls-back). But **structured `admin0`–`admin3` fields do NOT fall back** — an admin field whose bound level exceeds the country's maxLevel is dropped entirely, which may yield an empty match. Always check the returned `level` to confirm actual granularity.

## China admin1 (province) UID reference

China's 34 province-level UIDs (slug = pinyin of the Chinese name, no ADM codes). Use these to pin `styleValues.regionId` (e.g. `"rg:cn.hebei"` for a Hebei-focused map) or to sanity-check `region_match` output:

| UID | Province | UID | Province |
|---|---|---|---|
| `rg:cn.anhui` | 安徽省 | `rg:cn.liaoning` | 辽宁省 |
| `rg:cn.aomen` | 澳门特别行政区 | `rg:cn.neimenggu` | 内蒙古自治区 |
| `rg:cn.beijing` | 北京市 | `rg:cn.ningxia` | 宁夏回族自治区 |
| `rg:cn.chongqing` | 重庆市 | `rg:cn.qinghai` | 青海省 |
| `rg:cn.fujian` | 福建省 | `rg:cn.shaanxi` | 陕西省 |
| `rg:cn.gansu` | 甘肃省 | `rg:cn.shandong` | 山东省 |
| `rg:cn.guangdong` | 广东省 | `rg:cn.shanghai` | 上海市 |
| `rg:cn.guangxi` | 广西壮族自治区 | `rg:cn.shanxi` | 山西省 |
| `rg:cn.guizhou` | 贵州省 | `rg:cn.sichuan` | 四川省 |
| `rg:cn.hainan` | 海南省 | `rg:cn.taiwan` | 台湾省 |
| `rg:cn.hebei` | 河北省 | `rg:cn.tianjin` | 天津市 |
| `rg:cn.heilongjiang` | 黑龙江省 | `rg:cn.xinjiang` | 新疆维吾尔自治区 |
| `rg:cn.henan` | 河南省 | `rg:cn.xizang` | 西藏自治区 |
| `rg:cn.hongkong` | 香港特别行政区 | `rg:cn.yunnan` | 云南省 |
| `rg:cn.hubei` | 湖北省 | `rg:cn.zhejiang` | 浙江省 |
| `rg:cn.hunan` | 湖南省 | | |
| `rg:cn.jiangsu` | 江苏省 | | |
| `rg:cn.jiangxi` | 江西省 | | |
| `rg:cn.jilin` | 吉林省 | | |

City UIDs append the city slug: `rg:cn.guangdong.shenzhen`, `rg:cn.hebei.shijiazhuang`. District UIDs append one more: `rg:cn.guangdong.shenzhen.luohu`.

## Worked input examples

```
# Country
{"admin0": "China"}                              → rg:cn                       L0

# State/province with country context
{"admin0": "China", "admin1": "广东省"}            → rg:cn.guangdong             L1
{"admin1": "California", "country": "US"}         → rg:us.california            L1

# City/county with parent context
{"admin0": "China", "admin1": "广东省", "admin2": "深圳市"}
                                                 → rg:cn.guangdong.shenzhen    L2

# District (level 3) — always admin3
{"admin0": "China", "admin1": "广东省", "admin2": "深圳市", "admin3": "罗湖区"}
                                                 → rg:cn.guangdong.shenzhen.luohu   L3
{"admin1": "北京市", "admin2": "北京市", "admin3": "朝阳区"}
                                                 → rg:cn.beijing.beijing.chaoyang   L3

# Coordinates
{"longitude": 116.4074, "latitude": 39.9042}     → rg:cn.beijing.beijing.dongcheng  L3
{"longitude": -118.2437, "latitude": 34.0522}    → rg:us.california.los-angeles     L2

# Rejected — free text goes level-blind ("河北省" would match a district);
# put the name in the adminN field of its level
{"address": "河北省"}                             → error: address is not accepted

# Ambiguous (verify before use)
# Genuine ties are rare — the matcher usually tie-breaks deterministically.
# When you do get ambiguous: true, re-run the item with more admin context.
{"admin2": "<a name shared by two counties at equal strength>", "admin1": "<state>"}
                                                 → ambiguous: true (verify before use)

# No match — an adminN value the index cannot latch onto returns empty
{"admin2": "qqqqqqqqqqqq", "admin1": "广东省"}     → uid: "", level: 0
```
