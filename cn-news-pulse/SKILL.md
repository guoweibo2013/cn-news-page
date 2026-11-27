---
name: cn-news-pulse
description: 汇总国内公开新闻与热榜线索，按事件去重、核实并生成带来源的时事简报；适用于今日新闻、事件追踪和国内热点核查，不用于代替人工事实核查。
---

# 国内时事简报

使用随附脚本聚合公开新闻 RSS、政府与中央媒体要闻、主流报刊时评、百度热搜和B站热榜，输出事件级简报。脚本负责抓取、去重、聚类、排序和渲染；你负责检查输出、解释不确定性，并在需要时补充网页核验。

## 基本流程

1. 确定时间窗口。用户没有指定时默认最近24小时；常见窗口为6、24、72小时或7天。
2. 执行：

```bash
python3 "$SKILL_DIR/scripts/news_pulse.py" --hours 24 --limit 12 --emit markdown
```

3. 用户给出主题、人物或产品名时，把主题作为第一个位置参数：

```bash
python3 "$SKILL_DIR/scripts/news_pulse.py" "神舟二十四号" --hours 72 --emit markdown
```

4. 需要机器可读结果时使用 `--emit json`。需要可浏览的独立页面时使用 `--emit html --output /absolute/path/brief.html`。
5. 原样保留新闻链接、发布时间、来源状态和不确定性提示。不要补写脚本没有返回的事实、引语、数字或链接。

需要把“今日要闻、报刊时评、神舟二十四号、6小时科技”合成一个可离线打开、可切换和搜索的页面时：

```bash
python3 "$SKILL_DIR/scripts/build_standalone.py" \
  --output /absolute/path/index.html \
  --cache-dir "$SKILL_DIR/.cache" \
  --fail-if-empty
```

该页面包含事件详情、时间线、来源对比、官方来源标签、新事件/更新状态、关键词关注、阅读记录、分享链接、PWA安装和15分钟自动刷新。页面目录还会生成：

- `manifest.webmanifest` 和 `sw.js`：安装与离线缓存
- `digest.md`：当日摘要
- `digest.xml`：可订阅的 Atom 日报

`--cache-dir` 保存跨运行事件状态和来源健康历史；省略时仍会生成页面，但无法识别“新事件/刚刚更新”。`--fail-if-empty` 用于云端发布，避免用空页面覆盖上一份成功结果。

报刊时评使用独立分类，不混入普通新闻主榜：

```bash
python3 "$SKILL_DIR/scripts/news_pulse.py" --category commentary --hours 72 --emit markdown
```

时评来源目前包括人民日报观点、光明网时评和新京报评论/快评。页面仅展示短节选、报刊名称和原文链接，不复制完整文章。

用户要求科技、财经、时政等分类新闻时，使用 `--category`，不要把“科技”等分类词简单当作关键词：

```bash
python3 "$SKILL_DIR/scripts/news_pulse.py" --category tech --hours 6 --emit markdown
```

需要每天生成两张小红书竖版图并写入 iCloud 备忘录时：

```bash
python3 "$SKILL_DIR/scripts/daily_social_notes.py"
```

安装每天 07:30 的本机定时任务：

```bash
python3 "$SKILL_DIR/scripts/daily_social_notes.py" --install-schedule --run-time 07:30
```

每天生成“今日数字速览”和“今日观点卡”两条备忘录，每条包含 1080×1440 图片和可复制的小红书文案。本机需保持登录、联网，并在 iCloud 备忘录中启用同步。

## 输出原则

- 新闻RSS是事实候选来源；百度热搜和B站热榜只是注意力线索，不能单独证明事件属实。
- 中国政府网、新华网和权威媒体的直接来源优先于聚合热榜。
- 报刊时评属于观点内容，应与事实新闻分开呈现；节选不得替代原文或暗示平台立场。
- “单源报道”不是假新闻的同义词，但应明确提示尚缺独立印证。
- 时效、来源等级、独立来源数量、热榜关注度共同决定排序；点赞和热搜不能压过来源质量。
- 突发事件应写明首次出现时间、最近更新时间以及仍未确认的部分。
- 如果脚本报告某个来源失败，保留简报并说明覆盖不完整。
- 用户要求“核实真假”时，先用本Skill找出原始报道，再使用当前会话可用的网页搜索核对官方通报或其他独立来源；不得仅凭热榜下结论。

## 参考

- 需要调整来源、评分或判断规则时，读取 [references/editorial-rules.md](references/editorial-rules.md)。
- 需要增加新的新闻RSS时，优先通过脚本的 `--rss "名称=URL"` 参数验证，再考虑写入默认源列表。
