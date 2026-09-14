# mapview-skills

[地图视图（MapView）](https://mapview.site) Agent Skill —— 把表格数据（CSV / Excel / 多维表格）变成**可分享的交互地图**：区域统计图、点图层、热力图，内置地理编码与区域匹配，支持中国省 / 市 / 区下钻。地图通过一个链接分享，查看者无需账号。

## 安装

需要 Python 3.9+（仅标准库，无需安装任何依赖）。

**skills.sh**（推荐）：

```bash
npx skills add maptable/mapview-skills
```

**手动安装**：把 [`mapview/`](mapview/) 目录整体拷贝到所用 agent 的 skills 目录。

全局安装（跨项目生效）：

```bash
cp -r mapview/ ~/.trae/skills/     # Trae
cp -r mapview/ ~/.zcode/skills/    # ZCode
cp -r mapview/ ~/.claude/skills/   # Claude Code
```

项目内安装（仅当前项目生效）：

```bash
cp -r mapview/ .codebuddy/skills/  # CodeBuddy
cp -r mapview/ .agents/skills/     # 其他兼容 Agent Skills 规范目录的 agent
```

## 使用

安装后直接在对话里让 agent 建图，例如「把这份数据按省做成区域统计图」或「给这批地址建个点地图」。连接、登录、地理编码等步骤均由 agent 自动完成，最终返回可分享的地图链接。

## License

[Apache-2.0](LICENSE)
