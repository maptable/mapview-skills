# Visualization design guide

Default maps work but are usually ugly — single color, no hierarchy. To make a map **expressive and readable**, the Agent must make three decisions based on data semantics: **color palette**, **classification method**, and **step count**. This file gives ready-to-use options by data type.

## Core principles

1. **Palette matches data type** — sequential data uses single-hue ramps; data with a midpoint uses diverging; categorical uses qualitative. A mismatch misleads the reader.
2. **Classification matches distribution** — skewed data uses quantile; uniform uses quantize. A mismatch crams most regions into one band.
3. **Step count ≤ 9, and 7 is usually best** — 9 is the hard upper bound of human color discrimination; above it nobody can tell bands apart.

## Step 1: identify the data type

| Data trait | Type | Example | Palette direction |
|---|---|---|---|
| Has natural order, more=darker | sequential | sales, population, temperature | single-hue ramp (Blues/Greens/Oranges) |
| Revolves around a meaningful midpoint, deviates both ways | diverging | growth rate (0 as midpoint), satisfaction (neutral as midpoint) | diverging palette (RdYlBu/Spectral) |
| Unordered categories, mutually independent | qualitative | store type, industry | qualitative palette (Set1/Set2) |
| Only present/absent | binary | has store / no store | 2-step single color |

**How to decide:** numeric and "more=stronger" → sequential; numeric but with a clear midpoint (0, average, pass mark) → diverging; text categories → qualitative.

## Step 2: pick a palette (hex arrays for styleValues.colors)

`styleValues.colors` takes a hex string array; array length = step count. Below are **7-step** actual hex values for common palettes — copy them directly. For other step counts, take the first/last N values from the palette.

### Sequential palettes (most common)

For: sales, population, density, counts — "more = darker" metrics.

| Palette | hex (7 steps, light→dark) | Tone |
|---|---|---|
| **Blues** | `["#eff3ff","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#084594"]` | Blue, neutral professional. **General default.** |
| **Greens** | `["#edf8e9","#c7e9c0","#a1d99b","#74c476","#41ab5d","#238b45","#005a32"]` | Green, for growth/environment/positive metrics. |
| **Oranges** | `["#feedde","#fdd0a2","#fdae6b","#fd8d3c","#f16913","#d94801","#8c2d04"]` | Orange, warm, for alerts/heat. |
| **Reds** | `["#fee5d9","#fcbba1","#fc9272","#fb6a4a","#ef3b2c","#cb181d","#99000d"]` | Red, to emphasize high risk/density. |
| **Purples** | `["#f2f0f7","#dadaeb","#bcbddc","#9e9ac8","#807dba","#6a51a3","#4a1486"]` | Purple, for population/density metrics. |

> The 地图视图 region-layer default is `["#59eefb","#4dd6ef","#40bde3","#34a4d7","#278bca","#4566c4","#5a3fbe"]` (maptableBlue1). You can keep it or swap per the table above.

### Diverging palettes

For: metrics deviating from a midpoint — growth rate (0 as midpoint), temperature anomaly (multi-year average as midpoint), net inflow/outflow.

| Palette | hex (7 steps, low→mid→high) | Use |
|---|---|---|
| **RdYlBu** | `["#d73027","#fc8d59","#fee090","#ffffbf","#e0f3f8","#91bfdb","#4575b4"]` | red (low)→yellow (mid)→blue (high). Most general diverging palette. |
| **RdYlGn** | `["#d73027","#fc8d59","#fee08b","#ffffbf","#d9ef8b","#91cf60","#1a9850"]` | red (bad)→yellow (mid)→green (good). For performance/satisfaction. |
| **Spectral** | `["#d53e4f","#fc8d59","#fee08b","#ffffbf","#e6f598","#99d594","#3288bd"]` | colorful diverging, strong visual impact. |

**When using a diverging palette, align the midpoint with the data's semantic midpoint** (0, average, pass mark), or the color direction misleads.

### Qualitative palettes

For: unordered categories — store type, industry, carrier. Each category gets an independent color with no order implied.

| Palette | hex (7 steps) | Use |
|---|---|---|
| **Set2** | `["#66c2a5","#fc8d62","#8da0cb","#e78ac3","#a6d854","#ffd92f","#e5c494"]` | Soft multi-color, for categorical regions/points. **Qualitative default.** |
| **Set1** | `["#e41a1c","#377eb8","#4daf4a","#984ea3","#ff7f00","#ffff33","#a65628"]` | High contrast, for few categories needing emphasis. |
| **Dark2** | `["#1b9e77","#d95f02","#7570b3","#e7298a","#66a61e","#e6ab02","#a6761d"]` | Dark, high contrast on white background. |

> Use qualitative palettes with `fillMethod: "ordinal"`. Above 8 categories colors become hard to distinguish — consider merging minor categories or switching chart type.

### Single value / point & icon layers

Point/icon layers default to a single color `["#0065ff"]`. To color markers by category, point `colorColumn` at the category column and use a qualitative palette for colors.

## Step 3: pick a classification method (fillMethod)

| fillMethod | Algorithm | When |
|---|---|---|
| `quantile` (default) | equal-count groups, each band has ~same number of regions | **Skewed data (most real metrics).** Prevents one band filling up while others are empty. |
| `quantize` | equal-range linear, splits by value range | **Uniform data.** On skewed data, extremes monopolize one band and the rest crowd together. |
| `ordinal` | one-to-one by category | **Qualitative data (text categories).** Pairs with a qualitative palette. |
| `customize` | manual breakpoints | When you know business thresholds (pass mark, alert levels). Pass the cut points via `styleValues.thresholds` — exactly `len(colors)-1` values, and send `colors` in the same call (or inherit a palette whose length matches). |

**Rule of thumb:** when unsure, use `quantile`. It's the safe choice for skewed data, and real business data (sales, population, revenue) is almost always skewed — a few very high, most medium-low.

**Quick skew check:** look at the ratio of max to median — if max >> median (e.g. 10x+), it's skewed, use `quantile`; if max ≈ median (within 2x), the distribution is fairly uniform, `quantize` works. Without stats, default `quantile` is safest.

## Step 4: pick a step count

- **7 steps** — default recommendation. Eye-distinguishable, sufficient granularity.
- **5 steps** — few regions (<30), or to emphasize big-class differences.
- **9 steps** — many regions (>100), need fine granularity. Upper bound.
- **3–4 steps** — only want high/medium/low.
- **> 9 steps** — nobody can distinguish; drop to 7.

Step count = `colors` array length. Change the array to change step count.

## Per-scenario recommended combos

| Scenario | Data type | colors | fillMethod | aggregateMethod |
|---|---|---|---|---|
| Sales by province | sequential, skewed | Blues 7-step | quantile | sum |
| Population density by province | sequential, skewed | Purples 7-step | quantile | mean |
| GDP growth rate by province | diverging, 0 as midpoint | RdYlBu 7-step | quantile | mean |
| Store count by province | sequential, skewed count | Greens 7-step | quantile | count |
| Store type distribution | qualitative | Set2 7-step | ordinal | uniqueValues |
| Satisfaction by province | diverging, 50% as midpoint | RdYlGn 7-step | quantile | mean |
| Air quality by city | sequential, has alert thresholds | Oranges 7-step | quantize | mean |

## Icon selection (`icon` layers)

For `layerType: "icon"`, pick the marker shape from the 40 built-in icons (see [layer-types.md](layer-types.md)) by what each row represents. The right icon makes a map readable at a glance; a wrong one is no worse than the default.

| What the point represents | Recommended icon |
|---|---|
| Generic place, store, branch, office | `location` (default — safe for almost anything) |
| Restaurant / dining | `restaurant`, `cafe`, `bar`, `bakery` |
| Transport vehicle / hub | `bus`, `car`, `bicycle`, `rail`, `airport`, `racetrack` |
| Road / access / logistics | `entrance`, `barrier`, `construction`, `warehouse` |
| Fuel / parking / vehicle service | `fuel`, `parking` |
| Health / medicine | `pharmacy` |
| Tourism / culture / landmarks | `attraction`, `museum`, `bridge` |
| Education | `college` |
| Business / retail category | `office`, `building`, `commercial`, `clothing`, `grocery`, `hairdresser`, `suitcase` |
| Highlight / favorite / award | `star`, `flag` |
| Abstract / no semantic match | `circle`, `square`, `diamond`, `triangle`, `cross`, `plus`, `love` |

When unsure, use `location`. To show the **density** of the same points instead of individual markers, switch to `heatmap` with `radius` ~20.

**Per-category markers:** when points fall into categories (store type, cuisine, vehicle kind), give each category its own icon via `styleValues.icons` (array, aligned with `colors`) instead of one shared `icon` — pair with `colorColumn` + `fillMethod: "ordinal"`. Match the icon to the category's meaning (dining → `restaurant`/`cafe`/`bar`; transport → `bus`/`car`/`bicycle`), so color and shape reinforce each other.

## Common mistakes

- **Using a qualitative palette for sequential data** — region colors look random; readers can't tell high from low. Sequential data must use a single-hue ramp.
- **Using quantize for skewed data** — 90% of regions cram into the lowest band while a few extremes monopolize the top. Skewed data needs quantile.
- **Diverging palette not aligned to midpoint** — the midpoint must be the data's semantic midpoint (0, average, pass mark), or the red/green direction misleads.
- **Too many steps** — above 9 the colors are indistinguishable noise. Drop to 7.
- **Multi-color heatmap** — heatmaps usually use a single-hue ramp (dark = dense). Multi-color heatmaps only when there's a clear density-segment need.
- **Not setting styleValues** — defaults work but are usually not great. The Agent should proactively pick colors by data semantics.

## Tweaking after the fact

All style decisions on this page can be applied (or changed) **after** a layer exists via `update_layer` with `styleValues` — same vocabulary as `add_layer`, only the fields you pass change; everything else keeps its current value. Typical fixes:

```
update_layer {mapId, layerId, styleValues: {colors: ["#...","#...","#..."], fillMethod: "quantile"}}
update_layer {mapId, layerId, styleValues: {colors: ["#59eefb","#f6ce5b","#ea5b89"], thresholds: [100, 500], fillMethod: "customize"}}
update_layer {mapId, layerId, styleValues: {thresholds: []}}        // drop custom breakpoints (back to fillMethod-driven bands)
update_layer {mapId, layerId, fieldMappings: {labelColumn: ""}}   // clear labels: pass an empty string
update_layer {mapId, layerId, styleValues: {regionLevel: "admin2"}}
```

Thresholds only take effect with `fillMethod: "customize"` and must count exactly `len(colors)-1`, strictly ascending; pass `"thresholds": []` to clear them (a plain recolor of a customize layer otherwise requires matching thresholds).

Map-level looks (basemap style, viewport) change via `update_map` — see the cookbook. Note: to invert a palette, reverse the `colors` array — there is no reverse switch.
