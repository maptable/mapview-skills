# Field types: mapping data columns to 地图视图 column types

How to declare `columns` in `add_layer` / `update_layer` so the data renders and filters well. The mapping below is stable — same source field semantics always map to the same column type.

## Mapping table

| Source field | Column type | typeOptions | Notes |
|---|---|---|---|
| Category / enum (province, city, category, status, tier, brand) | `singleChoice` | — (derived) | The whole point of singleChoice: server derives options from the cell values, viewers filter from a dropdown instead of typing text. See below. |
| Money (sales, revenue, price, budget) | `number` | `{"format": "currency", "currency": "CNY", "precision": 2}` | Replace `CNY` with the actual currency (ISO code). When omitted, options are inferred: `¥` values → CNY currency format, precision floored at 2; `format: "currency"` without a code defaults to CNY. |
| Percentage stored as a fraction (0.15) | `number` | `{"format": "percentage", "precision": 0}` | Display multiplies by 100 (`0.15` → `15%`). Keep the stored value as the fraction. Values written as `"15%"` strings auto-convert to `0.15` and the format is inferred. |
| Big counts (population, sales volume, downloads) | `number` | `{"format": "commaNumber"}` | Thousands separators. Add `precision` if fractional. |
| Plain quantity / ratio / coordinate value | `number` | optional `{"precision": N}` | Precision is inferred from the data (max seen decimals) when omitted. |
| Date / timestamp | `datetime` | optional `{"dateFormat": "year/month/day", "timeFormat": "hidden"}` | Pass epoch ms numbers or date strings — ISO 8601 and common layouts (`2024-03-01`, `2024/03/01 10:30`, `March 1, 2024`, day-first `25/03/2024`) auto-convert to epoch; year-less strings (`3/1`) fill the current year. Timezone: bare strings (no offset) parse in the workspace timezone (the org's setting; Asia/Shanghai on this deployment); explicit ISO offsets (`...+09:00`) always win, as does a ` (GMT ±HH:MM)` display suffix. `dateFormat`: `year/month/day` (default) \| `month/day/year` \| `detail`; `timeFormat`: `hidden` (default) \| `24-hour-clock` \| `12-hour-clock`. Layouts are inferred from string dates; numeric epoch cells carry no shape signal, so pass `typeOptions` explicitly if you need non-default layouts. Datetime columns also unlock the datetime slicer (last N months, etc.). |
| True/false flag | `boolean` | — | Cells are JSON `true`/`false`; `"true"/"false"/"yes"/"no"/"是"/"否"` strings auto-convert. |
| URL | `hyperlink` | — | Cell is the URL string, or `{link, text}` (aliases `{url, name}`) when the link has a display name — rendered as a clickable link that shows `text` and opens `link`; stored as the bare string when no name is given or the name equals the URL. |
| Uploaded image files (store/product photos for popup covers) | `attachment` | — | Cells are arrays of fileID strings from the CLI `upload` command or the `upload_file` tool (base64 `data`; `{fileID, fileName}` objects are accepted too), max 5 per cell. The server expands each fileID into the stored attachment record; see the Skill's **Attachments & cover images** section. |
| Name, title, description, free text | `multiLineText` | — | The default for text. |
| Longitude / latitude | two `number` columns | — | Not a column type — declare both columns and map them via `fieldMappings.longitudeColumn` / `latitudeColumn`. A legacy `coordinate` declaration (older skill docs advertised it) is accepted and stored as `multiLineText`. |

## singleChoice: when and why

Any **low-cardinality categorical text column** (values repeat a lot — typically ≤ 50 distinct values; hard ceiling 100, enforced server-side) should be `singleChoice` instead of `multiLineText`:

- **Options are derived automatically** from the distinct cell values (first-seen order); option id = name = the cell text, colors auto-assigned. Nothing to pass — declare the type and write the readable value in each cell.
- Filters and slicers become **dropdowns** (pick "广东") instead of a text input (type and hope).
- Slicer defaults on such columns take the option name itself — the same text as the cell values, no id lookup needed.
- Works well as a `colorColumn` with `fillMethod: "ordinal"` — one color per category.
- Appending new values later (`update_layer` append/upsert) extends the option list automatically; existing options keep their order and colors.

High-cardinality text (IDs, sentences, names of many distinct entities) stays `multiLineText` — more than 100 distinct values is rejected outright.

**Pinning option order**: pass `typeOptions: {"choices": ["广东", "浙江"]}` to fix the leading options (plain names, order = display order). Values appearing in the data but not in your list are appended after, in first-seen order; ids and colors are filled automatically. Full `{id, name, color}` objects are accepted too but rarely worth it — their `id` must equal `name` (cells carry the name), and `color` must be a platform color name or omitted; anything else is rejected.

**Choice color names** (the complete valid list, for the rare case you set `color` explicitly — omit it and each option gets a stable auto-assigned color cycling the light set):

- Light (20, used by auto-assignment): `redLight` `redLighter` `salmonLight` `salmonLighter` `orangeLight` `orangeLighter` `yellowLight` `yellowLighter` `greenLight` `greenLighter` `cyanLight` `cyanLighter` `blueLight` `blueLighter` `purpleLight` `purpleLighter` `lilacLight` `lilacLighter` `greyLight` `greyLighter`
- Dark (10): `redDark` `salmonDark` `orangeDark` `yellowDark` `greenDark` `cyanDark` `blueDark` `purpleDark` `lilacDark` `greyDark`

Hex values (`#ff0000`) and any other name are rejected — these map to the frontend's fixed palette, not raw colors.

## Updating options on an existing layer

`update_layer` keeps stored options in sync with the data:

- **append / upsert** — new cell values extend the option list automatically; existing options keep their order and colors. A same-id column in the `columns` array may refresh its `typeOptions` (display format, pinned choice order — the whole typeOptions object is replaced); the column's type and name never change.
- **replace** — options are re-derived from the new data (ids stay stable because id = value). Web-editor customizations to the old option list are dropped; re-pin them via `choices` if needed.
- Changing a column's **type** (e.g. `multiLineText` → `singleChoice`) is a replace — append/upsert never redefine an existing column.

## Currency codes

`USD` `EUR` `GBP` `CNY` `JPY` `KRW` `AUD` `CAD` `CHF` `HKD` `SGD` `TWD` `INR` `THB` `VND` `MYR` `PHP` `AED` `MXN` `PLN` `RUB`

`format: "currency"` without `currency` defaults to **CNY** — pass the code explicitly for non-CNY money.

## Gotchas

- **String cells auto-convert to the declared type.** `"¥1,234.5"` / `"15%"` / `"1,234"` → number, ISO/common date strings → datetime, `"true"/"是"` → boolean. A value that cannot convert fails the write with the column and value — declare the column `multiLineText` if the data is really text.
- **Display options are inferred when omitted, explicit declarations always win.** Inferred: currency symbols → currency code (`¥` → CNY), `%` suffix → percentage format, max seen decimals → precision (currency floors at 2), date shapes → layouts.
- **percentage multiplies by 100 at display time.** Store the fraction (`0.15`), not the percentage number (`15`).
- Supported column types are exactly: `multiLineText`, `hyperlink`, `number`, `datetime`, `singleChoice`, `boolean`, `attachment` — anything else is rejected.
- **Attachment fileIDs must come from the same map's upload.** Each map's files live under its own path; a fileID uploaded to another map cannot resolve and the write fails, naming the row, column, and fileID. Upload the file to THIS map first (`python3 mapview_cli.py upload <mapId> <file...>`), then reference it.
- **Upload identical files once.** Every upload stores a new object and returns a new fileID — there is no dedupe. Upload each unique image a single time and reuse its fileID in every row that shows it (≤5 per cell).
- `typeOptions` is only consumed on `number` and `datetime` columns (plus the derived `singleChoice` options) — passing it elsewhere is rejected.
- Column type is decided when the layer is created; `update_layer` replace swaps the whole schema, append/upsert keep it. Changing a column from `multiLineText` to `singleChoice` later means a replace.
