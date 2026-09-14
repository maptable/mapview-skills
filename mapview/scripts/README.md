# 地图视图 CLI


零依赖的 Python 3 脚本，通过 地图视图 的 MCP 端点（`/mcp/`，无状态 JSON-RPC）把数据构建成地图——这是驱动 地图视图 的默认方式。（文件上传保留专用 multipart 端点；登录与词表保留 REST 端点。）`python3 mapview_cli.py tools` 打印实时工具目录——权威清单，包括比本脚本更新的工具。

## 准备

1. **连接（引导式）**——不带参数运行 `login`：它打印一个登录链接，你在浏览器里完成（登录、注册、选择工作区都与官网操作完全一致），token 自动保存。
   ```bash
   python3 mapview_cli.py login
   ```
   想用手动 token？在 地图视图 UI 生成一个（**Settings → Access Token**，以 `mapview_pat_` 开头）并保存：
   ```bash
   python3 mapview_cli.py login --token "mapview_pat_xxx"
   ```

2. **token 存储**（一次性、按用户——后续每个命令自动读取；先运行 `python3 mapview_cli.py status` 检查是否已存有）：`login` 写入平台按用户隔离的配置目录——`~/.config/mapview/tokens.json`（Linux 与 macOS；设置了该变量时为 `$XDG_CONFIG_HOME/mapview/tokens.json`）、`%APPDATA%\mapview\tokens.json`（Windows）。多主机、多工作区共存于其中——`switch` 只替换本地活动 token；原工作区的 token 在服务端仍然有效。

3. **运行**（Python 3.9+，仅标准库——无需 `pip install`）：
   ```bash
   python3 mapview_cli.py <command> [options]
   ```

## 命令

### login
把本机连接到 地图视图。不带参数时运行引导式浏览器登录：发起登录请求、打印 URL、轮询直到你在浏览器完成，并保存下发的 token。带 `--token <value>` 时只保存该 token；`--token -` 从 stdin 读取（显式要求——隐式读 stdin 在 agent 的开放管道下会永久挂起）。替换已有 token 时会给出提示。
```bash
python3 mapview_cli.py login                # 引导式浏览器登录
python3 mapview_cli.py login --token "mapview_pat_xxx"
```

### switch
连接到另一个工作区：重新运行引导式浏览器登录并保存新 token。登录链接带 pick 标志，浏览器会要求你选择工作区，而不是自动进入当前那个。原工作区的 token 在服务端仍然有效——PAT 按组织共存；只有本地活动 token 被替换。
```bash
python3 mapview_cli.py switch
```

### status
显示是否已配置 access token 及其来源，加上生效主机与其上所有已存工作区槽位。纯本地检查——token 是否有效要到第一次 API 调用才见分晓。未配置 token 时非零退出。
```bash
python3 mapview_cli.py status
```

### tools
列出服务器的**实时工具目录**——每个工具的权威清单，包括比本 CLI 更新的工具。不带参数时每工具打印一行（名称 + 简述）；带工具名时打印该工具的完整描述与输入 schema。当专用子命令不存在、或调用报未知工具/参数错误时，先查它。
```bash
python3 mapview_cli.py tools
python3 mapview_cli.py tools update_slicers
```

### call
用 JSON payload 调用**任意**工具——通用逃生通道，让每个服务端工具在没有专用子命令时也可用。payload 可以是内联 JSON（`--json`）或文件/stdin（`--input`）。参数名与类型来自工具的 schema（`tools <name>`）。
```bash
python3 mapview_cli.py call get_map --json '{"mapId": 123}'
python3 mapview_cli.py call some_new_tool --input payload.json
```

### create_map
创建新地图。返回 `{mapId, shareUrl}`。
```bash
python3 mapview_cli.py create_map --name "Sales by Province" --desc "Q3 2026"
```

### add_layer
向地图添加数据图层。payload（mapId、layerType、columns、rows、fieldMappings、styleValues）从 JSON 文件或 stdin 读入。
```bash
python3 mapview_cli.py add_layer --input layer.json
# 或经 stdin：
cat layer.json | python3 mapview_cli.py add_layer
```
payload 示例形状见下方 `layer.json` 示例。

### upload
把图片文件上传到地图，用于 **attachment 列**（信息窗口封面图）。每张图打印一行——`fileID  fileName`——可直接粘进 attachment 单元格。限额：每次 ≤20 个文件、每个 ≤5MB、总量 ≤100MB；仅图片类型（jpg、jpeg、png、gif、webp——不含 bmp/svg）。每张唯一图片**只上传一次**，fileID 跨行复用——每次上传都会存一个新对象。`--name` 重命名存储文件（仅单文件）。（没有 CLI 的 agent 客户端可以用 JSON POST 同一端点：`{mapId, data: <标准 base64>, name}`。）
```bash
python3 mapview_cli.py upload 123 photo1.jpg photo2.png
python3 mapview_cli.py upload 123 tmp8f3c.png --name "Store front.jpg"
```

### upload_html
把**自包含 HTML 文件**托管到地图上并获取公开访问 URL——任何拿到链接的人浏览器直接打开，无需登录，与地图的分享开关无关。文件必须完全自包含（内联 CSS/JS、data: URI 图片；≤5MB）。`--name` 记录文档名；`--type` 选择 URL 打开的前端页面（目前只有 `report`）。打印 `htmlId  url`——url 原样转达。没有原地更新：重新托管会得到新 URL；替换时用 `delete_html` 删旧的。`get_map` 在 `hostedHtml` 下列出地图的托管页面。
```bash
python3 mapview_cli.py upload_html 123 report.html --name "Q3 sales report"
```

### delete_html
传回公开 URL 删除托管 HTML 页面——即 `upload_html` 打印过或 `get_map` 列出的那个确切 url。链接立即失效。需要编辑权限。
```bash
python3 mapview_cli.py delete_html "https://…/project/123/report?reportID=…"
```

### list_maps
列出工作区所有活跃地图。返回 `[{mapId, name, desc, layerCount, updateTime}, ...]`。
```bash
python3 mapview_cli.py list_maps
```

### get_map
获取单张地图的完整状态 + 图层列表。返回 `{mapId, name, desc, shareUrl, baseMap, center, zoomLevel, layers: [{layerId, name, layerType, rowCount}, ...]}`。
```bash
python3 mapview_cli.py get_map --map-id 123
```

### update_layer
原地更新图层——数据（`--mode replace|append|upsert`）、可视化、名称、comparison 或顺序。只改你传入的部分。数据更新只对经 add_layer 创建的图层有效。
```bash
# 重设样式：在已有图层上换配色 + 分级
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" \
  --input style.json          # {"styleValues": {"colors": [...], "fillMethod": "quantile"}}

# 追加新行（增量列可选）
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" --mode append --input rows.json

# 按 id 修行：传入字段覆盖，未提字段存活
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" --mode upsert --input fixes.json

# 仅改名
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" --name "Q4 Sales"

# 调整图层顺序（top 画在其他图层之上；bottom 是比较组默认展示位）/ 切换 comparison 成员
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" --order top
python3 mapview_cli.py update_layer --map-id 123 --layer-id "abc123" --comparison true
```

### get_layer_data
读回图层存储的 columns + rows（分页、可投影、可按行 id 过滤）。用于验证写入、或 append 后找回自动生成的行 id。`--formatted` 为每行附加 `displayText`——展示就绪字符串（`2024/03/01`、`¥1,234.56`、`15%`），用于汇报。
```bash
python3 mapview_cli.py get_layer_data --map-id 123 --layer-id "abc123" --limit 100
python3 mapview_cli.py get_layer_data --map-id 123 --layer-id "abc123" --columns province sales
python3 mapview_cli.py get_layer_data --map-id 123 --layer-id "abc123" --ids row-1 row-2
python3 mapview_cli.py get_layer_data --map-id 123 --layer-id "abc123" --formatted
```

### update_map
更新地图级设置：名称、描述、底图、视口、分享链接或分享密码。只改你传入的部分。
```bash
python3 mapview_cli.py update_map --map-id 123 --name "Q3 Sales" --base-map dark --center "116.4,39.9" --zoom 4

# 分享链接：发布未分享的地图（如网页编辑器里建的——create_map 建的默认已分享）或取消发布；
# 响应报告 shared + shareUrl
python3 mapview_cli.py update_map --map-id 123 --share on

# 分享密码：服务端生成随机值，明文返回
# （--password on 在未给 --share 时也会开启分享；--password off 只撤密码，绝不开启分享）
python3 mapview_cli.py update_map --map-id 123 --password on
python3 mapview_cli.py update_map --map-id 123 --reset-password
```

### delete_layer
从地图彻底删除图层（含数据文件）。修正优先 update_layer；只有图层不该存在时才删。
```bash
python3 mapview_cli.py delete_layer --map-id 123 --layer-id "abc123"
```

### get_quota
只读配额状态：geocode 用量、地图数、每图层数/行数限额。
```bash
python3 mapview_cli.py get_quota
```

### list_slicers
列出地图的切片器——地图与分享页上的交互筛选控件。返回每个切片器的 id、name、kind、`(layerId, columnId)` sources 与默认筛选。
```bash
python3 mapview_cli.py list_slicers --map-id 123
```

### update_slicers
添加、更新（按 id 整体替换）、删除或重排地图的切片器。复杂 payload 从 `--input <file>` 或 stdin 读入。
```bash
# 添加普通切片器，筛选一列，默认 equals "Guangdong"
cat <<'EOF' | python3 mapview_cli.py update_slicers --map-id 123 --mode add
{"name": "Province", "sources": [{"layerId": "abc", "columnId": "col_prov"}],
 "operator": "equals", "value": "Guangdong"}
EOF

# 添加滚动窗口 datetime 默认值（近一个月）
cat <<'EOF' | python3 mapview_cli.py update_slicers --map-id 123 --mode add
{"name": "Updated", "sources": [{"layerId": "abc", "columnId": "col_date"}],
 "datetimeRange": {"type": "last", "duration": "P1M"}}
EOF

# 添加级联切片器（省 → 市下钻）
cat <<'EOF' | python3 mapview_cli.py update_slicers --map-id 123 --mode add
{"name": "Region", "kind": "cascading", "levels": [
  {"name": "Province", "sources": [{"layerId": "abc", "columnId": "col_prov"}]},
  {"name": "City", "sources": [{"layerId": "abc", "columnId": "col_city"}]}]}
EOF

python3 mapview_cli.py update_slicers --map-id 123 --mode remove --slicer-id <slicerId>

# replace 重建完整列表；数组顺序 = 显示顺序
cat <<'EOF' | python3 mapview_cli.py update_slicers --map-id 123 --mode replace
[{"id": "<keep-first>", "name": "Province", "sources": [{"layerId": "abc", "columnId": "col_prov"}]},
 {"id": "<keep-second>", "name": "Category", "sources": [{"layerId": "abc", "columnId": "col_cat"}]}]
EOF
```

### geocode
批量把地址解析为经纬度（每次 ≤100 条）。每次调用消耗工作区的 geocode 配额，未命中也算——会话内第一次调用前先告知用户；`get_quota` 查余额。
```bash
python3 mapview_cli.py geocode --addresses "北京市朝阳区" "上海市浦东新区" --country CN
```

### region_match
把行政层级 / 坐标匹配为区域 UID（每次 ≤100 条）。每个区域名放进其层级的 adminN 字段（`admin1` 省、`admin2` 市、`admin0` 国家）——不接受自由文本 `address`。
```bash
python3 mapview_cli.py region_match --input items.json
```

## 本地 payload 构建器（fmt-*）

纯本地命令，把 agent 侧数据变成写入 API 要求的规范 columns/rows JSON——不发请求、不需要 token。输出到 stdout；在这里喂给 `add_layer`/`update_layer`，或直接粘作 MCP 工具参数。Column id **永远来自你的输入**（数据源字段 id、序号或唯一列名）并原样透传——保持数据源与列的对应是你的责任；工具绝不生成或映射 id。

提交前在本地校验：结构性错误（缺失/重复 id、未知 row key、参差 CSV 行）以及对照脚本内置词表快照的词汇检查（不发请求；服务端拒绝时其报错会列出可接受的值）。未声明类型保守推断（`multiLineText` 是安全兜底；报告打到 stderr）。

### fmt-columns
宽松列定义 → 规范 columns JSON。
```bash
echo '[{"id": "fldA1", "name": "销售额", "type": "number"},
       {"id": "0", "name": "门店", "type": "singleChoice",
        "typeOptions": {"choices": [{"name": "高", "color": "redLight"}, {"name": "中"}]}}]' \
  | python3 mapview_cli.py fmt-columns > columns.json
```
- `id` 必填并原样透传；`name` 缺省取 `id`。
- `type` 可省略 → 从 `--rows records.json`（样本）推断，否则 `multiLineText`；`--strict` 则拒绝未声明类型。
- 选项颜色是色板名（`redLight`、`blueDark`……）——hex 会被拒。

### fmt-rows
records → 规范 rows JSON（cells 按 column id 为键）。
```bash
echo '[{"id": "row-7", "fldA1": 6573, "0": "朝阳店"}, {"fldA1": 99}]' \
  | python3 mapview_cli.py fmt-rows --columns columns.json > rows.json
```
- record 的键必须是 column id（未知键报错并列出声明的 id 清单）；行 `id` 原样透传，无 id 的行保持无 id（append 时服务端分配）。若某个声明的列恰好叫 `id`，扁平 record 的 `id` 值归入该列——要传行 id 用嵌套形式 `{"id": ..., "cells": {...}}`。
- `--columns` 接受 columns 数组、`fmt-csv` 输出、或整个 `get_layer_data` 响应——最后一种可为已有图层格式化新行，用于 append/upsert。

### fmt-csv
一步：CSV 文件 → `{columns, rows}`。
```bash
python3 mapview_cli.py fmt-csv --file data.csv --id index
python3 mapview_cli.py fmt-csv --file data.csv --id name --typed-header
```
- `--id index`（默认）：列位置（`"0"`、`"1"`……）作为 id——列顺序不变就稳定。
- `--id name`：表头名作为 id，必须唯一。**边界**：日后改列名（网页编辑器里）只改变 `get_layer_data` 里看到的名字，存储的 id 永不变——对会持续更新的数据源，优先用数据源原生 id 或 `--id index`；`--id name` 适合一次性导入。
- `--typed-header`：表头单元格携带内联类型（`销售额:number,开业日期:datetime`）。
- 无名的表头单元格（行尾逗号、导出的无名列）会按列位置报错——给列起名或删掉它。
- 全空列（声明的列在每个数据行都是空）在本地按列名报错——服务端会以同样方式拒绝同一写入；删掉该列或修好丢失数值的导出。
- 数值原样透传（日期/金额作为字符串没问题——服务端按声明类型转换）；空单元格变 `null`；参差行按行号报错。

## 坐标转换（convert-coords）

地图只存储和渲染 **WGS84**。中文表格类应用的地理位置字段——飞书多维表格（Feishu Bitable）、钉钉（DingTalk）、企业微信（WeCom）、腾讯文档/腾讯表格（Tencent Docs/Sheets）——以及任何高德/Amap/腾讯来源的坐标是 **GCJ-02**；百度的是 **BD-09**。直接提交，国内偏 100–700 m 且无报错——数字看起来完全合法。`add_layer`/`update_layer` 前（以及 `update_map --center` 前）先转换。纯本地计算（与服务端数据源连接器同算法）：不发请求、不需要 token。

```bash
# 单点
python3 mapview_cli.py convert-coords --from gcj02 --lng 116.410244 --lat 39.916405

# 原地改写 records/rows 文件的两列（--out 可以等于 --input）
python3 mapview_cli.py convert-coords --from gcj02 --input records.json --lng-col lng --lat-col lat --out records.json

# 坐标在同一个 "lng,lat" 字符串列（保留字符串形状）
python3 mapview_cli.py convert-coords --from bd09 --input records.json --coord-col location --out records.json
```

- `--input` 接受扁平 records 数组、规范 rows（`[{"cells": {...}}]`，如 `fmt-rows` 输出）、或带 `rows` 数组的对象（`get_layer_data` 响应）。
- 单元格可以是数字或数字字符串；输出四舍五入到 6 位小数（约 0.1 m）。
- 缺失/非数字坐标的行被计数并原样保留（汇总打到 stderr）；中国境外的点不改——GCJ-02 偏移在那里不适用。
- GCJ-02 偏移公式是保密的；这里用公开的克拉索夫斯基椭球近似（与 eviltransform / wandergis-coordtransform 同族，与服务端 `pkg/ewkt/coordtransform` 一致），精度约 1–2 m——远低于 marker 级语义。官方地图 API（高德/百度）只能转换**到** GCJ-02/BD-09，不能反向。
- **适用范围**：本规则针对**地理位置字段**和已知 GCJ-02/BD-09 的来源——系统确定的场合。来源不明的纯经纬度 number 列两种可能都有——问用户坐标从哪来，或按 WGS84 提交并说明该假设；绝不盲目转换。
- `geocode` 输出**已是 WGS84**——绝不要再转。

## layer.json 示例（add_layer payload）

```json
{
  "mapId": 123,
  "layerType": "region",
  "columns": [
    {"id": "region", "name": "City", "type": "multiLineText"},
    {"id": "sales",  "name": "Sales", "type": "number"}
  ],
  "rows": [
    {"cells": {"region": "rg:cn.guangdong.shenzhen", "sales": 6573}},
    {"cells": {"region": "rg:cn.guangdong.guangzhou", "sales": 1274}},
    {"cells": {"region": "rg:cn.guangdong.dongguan", "sales": 211}}
  ],
  "fieldMappings": {"regionColumn": "region", "colorColumn": "sales"},
  "styleValues": {
    "aggregateMethod": "sum",
    "fillMethod": "quantile",
    "colors": ["#eff3ff","#c6dbef","#9ecae1","#6baed6","#4292c6","#2171b5","#084594"],
    "regionLevel": "admin2",
    "regionId": "rg:cn.guangdong"
  }
}
```

styleValues 说明（完整清单见 [layer-types.md](../references/layer-types.md)）：
- `regionLevel` 设总览层级——这里是 admin2（市级图）。它可以比 UID 粗：同一批市级匹配的行设 admin1 会渲染省级图，点击可下钻到市。
- `regionId` 把图层聚焦到某个省/市（如 `"rg:cn.guangdong"` 聚焦广东）——视口自动适配到该区域。省略则全国视野。
- `icons`（与 `colors` 对齐的数组）在 `icon` 图层上给每个色档配自己的 marker。

## items.json 示例（region_match payload）

```json
{
  "items": [
    {"admin1": "广东省", "country": "CN"},
    {"admin0": "China", "admin1": "Beijing"},
    {"longitude": 116.4, "latitude": 39.9}
  ]
}
```

## 输出

每个命令把 API 响应 JSON 打到 **stdout**（便于管道/解析）。
错误打到 **stderr** 并以非零码退出。

## 分享链接

`create_map`、`add_layer`、`update_layer`、`update_map` 的响应都带 `shareUrl`——由服务端按部署的前端源构建的完整查看链接。原样呈现；绝不拼装或硬编码主机名。唯一需要的凭据是 access token。
