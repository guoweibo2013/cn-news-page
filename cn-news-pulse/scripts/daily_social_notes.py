#!/usr/bin/env python3
"""Generate two daily Xiaohongshu cards and place them in iCloud Notes."""

from __future__ import annotations

import argparse
import html
import os
import plistlib
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import news_pulse as pulse  # noqa: E402


FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"
WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
METRIC_RE = re.compile(
    r"(?<![\d.-])([+\-]?\d+(?:\.\d+)?\s*(?:万亿元|亿元|万个|万|亿|%|公里|倍|个|人|户))"
)


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def text_width(value: str) -> float:
    return sum(0.56 if ord(char) < 128 else 1.0 for char in value)


def wrap_text(value: str, max_width: float, max_lines: int) -> list[str]:
    text = pulse.clean_text(value, 1000)
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    current_width = 0.0
    for char in text:
        width = 0.56 if ord(char) < 128 else 1.0
        if current and current_width + width > max_width:
            lines.append(current.rstrip())
            current = char
            current_width = width
            if len(lines) >= max_lines:
                break
        else:
            current += char
            current_width += width
    if len(lines) < max_lines and current:
        lines.append(current.rstrip())
    return lines[:max_lines]


def text_block(
    lines: Iterable[str],
    x: int,
    y: int,
    *,
    size: int,
    color: str,
    weight: int = 400,
    line_height: int | None = None,
    anchor: str = "start",
) -> str:
    step = line_height or int(size * 1.45)
    return "".join(
        f'<text x="{x}" y="{y + index * step}" text-anchor="{anchor}" '
        f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}">{esc(line)}</text>'
        for index, line in enumerate(lines)
    )


def event_metric(event: dict) -> str:
    title = event.get("title") or ""
    summary = event.get("summary") or ""
    matches = METRIC_RE.findall(title)
    if not matches:
        matches = METRIC_RE.findall(summary[:180])
    if not matches:
        return "重点"
    value = matches[-1].replace(" ", "")
    if "增长" in title and not value.startswith(("+", "-")):
        value = "+" + value
    return value


def select_number_events(events: list[dict], count: int = 3) -> list[dict]:
    ranked: list[tuple[float, dict]] = []
    for event in events:
        metric = event_metric(event)
        if metric == "重点":
            continue
        text = f"{event.get('title') or ''} {metric}"
        score = float(event.get("score") or 0)
        if metric.endswith("%"):
            score += 12
        if "万亿元" in metric:
            score += 20
        elif "亿元" in metric:
            score += 10
        if "公里" in metric:
            score += 15
        elif "万" in metric:
            score += 7
        if any(term in text for term in ("增长", "突破", "累计", "首次", "全国", "我国")):
            score += 8
        if any(term in text for term in ("高铁", "铁路", "隧道", "公路", "核电", "能源")):
            score += 20
        if any(
            term in text
            for term in (
                "上市",
                "售价",
                "预售",
                "销量",
                "个股",
                "涨幅",
                "涨停",
                "彩票",
                "汽车",
                "车型",
                "停产",
                "官宣",
            )
        ):
            score -= 24
        if "国家统计局" in text or "工信部" in text:
            score += 12
        if any(term in text for term in ("下降", "同比降", "下滑", "亏损")):
            score -= 8
        ranked.append((score, event))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict] = []
    seen_topics: set[str] = set()
    for _, event in ranked:
        text = f"{event.get('title') or ''} {event.get('summary') or ''}"
        topic = "其他"
        if any(term in text for term in ("电信", "5G", "基站", "宽带")):
            topic = "通信"
        elif any(term in text for term in ("高铁", "铁路", "隧道", "公路", "航运")):
            topic = "交通"
        elif any(term in text for term in ("工业企业", "制造业", "工业利润")):
            topic = "产业"
        elif any(term in text for term in ("人工智能", "AI", "大模型", "芯片")):
            topic = "科技"
        elif any(term in text for term in ("核电", "能源", "电力")):
            topic = "能源"
        if topic == "其他":
            continue
        if topic in seen_topics:
            continue
        selected.append(event)
        seen_topics.add(topic)
        if len(selected) >= count:
            break
    if len(selected) < count:
        for _, event in ranked:
            if event not in selected:
                selected.append(event)
            if len(selected) >= count:
                break
    return selected or events[:count]


def metric_font_size(value: str) -> int:
    width = text_width(value)
    if width > 7:
        return 54
    if width > 5:
        return 64
    return 74


def short_metric_label(event: dict, metric: str) -> str:
    title = pulse.clean_text(event.get("title") or "", 240)
    if "5G" in title and "基站" in title:
        return "5G 基站总数"
    if "电信业务收入" in title:
        return "电信业务收入"
    if "工业企业利润" in title:
        return "规上工业企业利润增长"
    if "高铁" in title and "里程" in title:
        return "长三角高铁营业里程"
    if "核电" in title:
        return "核电建设取得新进展"
    if "隧道" in title:
        return "重大交通工程新进展"
    value = title.split("：", 1)[-1]
    value = value.replace(metric, "")
    value = re.sub(r"^(今年前|1[—\-]\d+月份|全国|我国)", "", value)
    value = value.replace("突破", "").replace("达到", "").replace("达", "")
    value = re.split(r"[，,；;]", value)[-1].strip(" ，。；")
    return value[:18].strip(" ，。；") or "今日重要进展"


def first_complete_sentence(value: str, limit: int = 180) -> str:
    text = pulse.clean_text(value, 600)
    text = re.sub(r"(?:…|\.\.\.)+\s*$", "", text).strip()
    parts = re.split(r"(?<=[。！？!?])", text)
    for part in parts:
        part = part.strip()
        if part:
            return part[:limit].rstrip("，；、 ").strip()
    return text[:limit].strip()


def source_line(event: dict) -> str:
    publishers = event.get("publishers") or []
    return "来源：" + (" / ".join(publishers[:3]) if publishers else "公开信息")


def clean_commentary(event: dict) -> str:
    value = pulse.clean_text(event.get("summary") or "", 260)
    value = re.sub(r"^(时评|人民锐评)\s*[｜|]\s*", "", value)
    return re.sub(r"(?:…|\.\.\.)+\s*$", "", value).strip()


def complete_copy_text(value: object) -> str:
    text = pulse.clean_text(value, 2000)
    text = re.sub(r"(?:…|\.\.\.)+\s*$", "", text)
    return text.strip()


def short_complete_sentence(value: object) -> str:
    text = complete_copy_text(value)
    sentences = [
        part.strip().lstrip("”’」』】）) ")
        for part in re.split(r"(?<=[。！？!?])", text)
        if part.strip() and re.search(r"[。！？!?]$", part.strip())
    ]
    if not sentences:
        return text
    for sentence in sentences:
        if 18 <= len(sentence) <= 100:
            return sentence
    return sentences[0]


def visible_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def fit_paragraph(parts: list[str], limit: int = 150) -> str:
    output = ""
    for part in parts:
        part = complete_copy_text(part)
        if not part:
            continue
        candidate = output + part
        if visible_length(candidate) <= limit:
            output = candidate
    return output


def metric_sentence(event: dict) -> str:
    metric = event_metric(event)
    label = short_metric_label(event, metric)
    if "%" in metric or label.endswith("增长"):
        return f"{label}{metric}"
    if "里程" in label:
        return f"{label}突破{metric}"
    if "收入" in label or "总数" in label:
        return f"{label}达到{metric}"
    return f"{label}为{metric}"


def commentary_topic(event: dict) -> str:
    title = complete_copy_text(event.get("title"))
    mappings = (
        ("家校", "家校关系"),
        ("半天学", "教育评价"),
        ("学校", "教育治理"),
        ("体育", "体育消费"),
        ("招聘", "AI招聘"),
        ("食品", "食品安全"),
        ("差评", "平台信用"),
        ("中欧", "经贸规则"),
        ("关税", "全球贸易"),
        ("水资源", "公共治理"),
    )
    for keyword, topic in mappings:
        if keyword in title:
            return topic
    value = re.split(r"[，,：:；;]", title)[0].strip("“”\"' ")
    return value[:10].strip("，。；、 ")


def build_numbers_svg(
    generated_at: datetime,
    events: list[dict],
    commentary: list[dict],
) -> str:
    date_text = generated_at.strftime("%Y年%m月%d日")
    weekday = WEEKDAYS[generated_at.weekday()]
    cards = []
    y_positions = (430, 684, 938)
    card_colors = ("#3C7E75", "#E4564A", "#1A2A46")
    for index, (event, y, accent) in enumerate(zip(events[:3], y_positions, card_colors), 1):
        dark = index == 3
        card_fill = "#1A2A46" if dark else "#FFFFFF"
        text_color = "#FFFFFF" if dark else "#243650"
        body_color = "#C6D3E5" if dark else "#556277"
        muted_color = "#93A8C4" if dark else "#929CAB"
        metric = event_metric(event)
        label_lines = wrap_text(short_metric_label(event, metric), 18, 2)
        source = source_line(event)
        metric_size = metric_font_size(metric)
        cards.append(
            f"""
  <rect x="72" y="{y}" width="936" height="238" rx="28" fill="{card_fill}" filter="url(#shadow)"/>
  <rect x="72" y="{y}" width="8" height="238" rx="4" fill="{accent}"/>
  <text x="112" y="{y + 48}" font-family="{FONT}" font-size="20" font-weight="700" fill="{'#B6C6DC' if dark else '#6D798B'}">{index:02d}</text>
  <text x="980" y="{y + 48}" text-anchor="end" font-family="{FONT}" font-size="17" fill="{muted_color}">{date_text}</text>
  <text x="112" y="{y + 149}" font-family="Avenir Next, PingFang SC, sans-serif" font-size="{metric_size}" font-weight="700" fill="{text_color}">{esc(metric)}</text>
  {text_block(label_lines, 510, y + 105, size=31, color=text_color, weight=700, line_height=42)}
  <text x="112" y="{y + 211}" font-family="{FONT}" font-size="16" fill="{muted_color}">{esc(source)}</text>
"""
        )

    quote = commentary[0] if commentary else None
    quote_title = pulse.clean_text(quote.get("title") if quote else "公开信息整理", 36)
    quote_sources = (
        "观点摘编：" + " / ".join(quote.get("publishers") or [])
        if quote
        else "公开信息整理"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">
  <defs>
    <linearGradient id="hero" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#14213B"/>
      <stop offset="0.68" stop-color="#20345B"/>
      <stop offset="1" stop-color="#294A78"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#263550" flood-opacity="0.10"/>
    </filter>
  </defs>
  <rect width="1080" height="1440" fill="#F4EFE5"/>
  <rect y="0" width="1080" height="390" fill="url(#hero)"/>
  <circle cx="905" cy="55" r="245" fill="#FFFFFF" opacity="0.05"/>
  <circle cx="1020" cy="360" r="220" fill="#E4564A" opacity="0.14"/>
  <text x="72" y="76" font-family="{FONT}" font-size="22" font-weight="700" letter-spacing="4" fill="#FFB5A9">DAILY BRIEF · {generated_at.strftime('%m.%d')}</text>
  <text x="1008" y="76" text-anchor="end" font-family="{FONT}" font-size="20" fill="#B8C7DB">{date_text} · {weekday}</text>
  <text x="72" y="184" font-family="{FONT}" font-size="68" font-weight="700" fill="#FFFFFF">今天，</text>
  <text x="72" y="264" font-family="{FONT}" font-size="68" font-weight="700" fill="#FFFFFF">三个数字看趋势</text>
  <text x="74" y="322" font-family="{FONT}" font-size="27" fill="#CBD8E9">基础设施 · 产业升级 · 区域连接</text>
  {''.join(cards)}
  <rect x="72" y="1225" width="936" height="134" rx="24" fill="#FFE8DF"/>
  <rect x="100" y="1255" width="78" height="30" rx="15" fill="#E4564A"/>
  <text x="139" y="1276" text-anchor="middle" font-family="{FONT}" font-size="15" font-weight="700" fill="#FFFFFF">今日观点</text>
  <text x="198" y="1275" font-family="{FONT}" font-size="28" font-weight="700" fill="#8B3B33">{esc(wrap_text(quote_title, 26, 1)[0])}</text>
  <text x="198" y="1312" font-family="{FONT}" font-size="18" fill="#9B5A4E">{esc(quote_sources)}</text>
  <text x="72" y="1398" font-family="{FONT}" font-size="15" fill="#8A7F73">公开信息整理 · AI辅助生成 · 事实与观点均请以原文为准</text>
  <text x="1008" y="1398" text-anchor="end" font-family="{FONT}" font-size="15" fill="#8A7F73">完整来源与时间线：cn-news-page</text>
</svg>
"""


def build_opinion_svg(
    generated_at: datetime,
    fact_event: dict | None,
    commentary: list[dict],
) -> str:
    date_text = generated_at.strftime("%Y年%m月%d日")
    weekday = WEEKDAYS[generated_at.weekday()]
    main = commentary[0] if commentary else None
    second = commentary[1] if len(commentary) > 1 else None
    third = commentary[2] if len(commentary) > 2 else None

    main_title = wrap_text(main.get("title") if main else "今天，听见不同观点", 17, 2)
    main_excerpt = wrap_text(
        first_complete_sentence(clean_commentary(main), 180) if main else "",
        27,
        4,
    )
    main_source = " / ".join(main.get("publishers") or []) if main else "公开信息"

    def small_card(event: dict | None, x: int) -> str:
        if not event:
            return ""
        title = wrap_text(event.get("title") or "", 14, 2)
        source = " / ".join(event.get("publishers") or [])
        return f"""
  <rect x="{x}" y="1020" width="456" height="250" rx="24" fill="#FFFFFF" filter="url(#shadow)"/>
  <text x="{x + 28}" y="1057" font-family="{FONT}" font-size="15" font-weight="700" fill="#E4564A">观点</text>
  {text_block(title, x + 28, 1102, size=29, color="#1A2A46", weight=700, line_height=40)}
  <text x="{x + 28}" y="1248" font-family="{FONT}" font-size="14" fill="#929CAB">{esc(source)}</text>
"""

    fact_title = pulse.clean_text(fact_event.get("title") if fact_event else "今日公开新闻", 100)
    fact_lines = wrap_text(fact_title, 32, 2)
    fact_source = " / ".join((fact_event or {}).get("publishers") or [])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1440" viewBox="0 0 1080 1440">
  <defs>
    <linearGradient id="hero" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6F2E32"/>
      <stop offset="0.55" stop-color="#A64747"/>
      <stop offset="1" stop-color="#D06C5D"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="#263550" flood-opacity="0.10"/>
    </filter>
  </defs>
  <rect width="1080" height="1440" fill="#F7F0E7"/>
  <rect y="0" width="1080" height="410" fill="url(#hero)"/>
  <circle cx="910" cy="30" r="250" fill="#FFFFFF" opacity="0.06"/>
  <circle cx="1060" cy="390" r="250" fill="#2A2031" opacity="0.17"/>
  <text x="72" y="76" font-family="{FONT}" font-size="22" font-weight="700" letter-spacing="4" fill="#FFD7CF">VIEWPOINT · {generated_at.strftime('%m.%d')}</text>
  <text x="1008" y="76" text-anchor="end" font-family="{FONT}" font-size="20" fill="#F0D8D3">{date_text} · {weekday}</text>
  <text x="72" y="184" font-family="{FONT}" font-size="64" font-weight="700" fill="#FFFFFF">今天，</text>
  <text x="72" y="262" font-family="{FONT}" font-size="64" font-weight="700" fill="#FFFFFF">听见三种观点</text>
  <text x="74" y="315" font-family="{FONT}" font-size="24" fill="#F5DAD5">从新闻事实出发，看看主流报刊在讨论什么。</text>

  <rect x="72" y="440" width="936" height="140" rx="24" fill="#FFF8F0" filter="url(#shadow)"/>
  <text x="102" y="478" font-family="{FONT}" font-size="16" font-weight="700" fill="#A44742">今日事实</text>
  {text_block(fact_lines, 102, 516, size=24, color="#25334A", weight=700, line_height=31)}
  <text x="102" y="562" font-family="{FONT}" font-size="14" fill="#8F7E7E">来源：{esc(fact_source or '公开信息')}</text>

  <rect x="72" y="610" width="936" height="390" rx="28" fill="#1A2A46" filter="url(#shadow)"/>
  <text x="110" y="654" font-family="{FONT}" font-size="17" font-weight="700" fill="#8FA5C3">今日主观点</text>
  <text x="974" y="654" text-anchor="end" font-family="{FONT}" font-size="15" fill="#8FA5C3">评论节选</text>
  {text_block(main_title, 110, 716, size=38, color="#FFFFFF", weight=700, line_height=49)}
  {text_block(main_excerpt, 110, 826, size=25, color="#D1DCEC", weight=400, line_height=38)}
  <text x="110" y="962" font-family="{FONT}" font-size="16" fill="#91A6C2">观点来源：{esc(main_source)}</text>

  {small_card(second, 72)}
  {small_card(third, 552)}

  <text x="72" y="1310" font-family="{FONT}" font-size="16" fill="#7D6E68">报刊观点仅供阅读与检索参考。节选不代表完整原文，请回到原报刊阅读全文。</text>
  <text x="72" y="1398" font-family="{FONT}" font-size="15" fill="#8A7F73">公开信息整理 · AI辅助生成 · 评论观点不代表本账号立场</text>
  <text x="1008" y="1398" text-anchor="end" font-family="{FONT}" font-size="15" fill="#8A7F73">更多来源：cn-news-page</text>
</svg>
"""


def svg_to_png(svg_path: Path, png_path: Path) -> None:
    result = subprocess.run(
        ["/usr/bin/sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not png_path.exists():
        raise RuntimeError(f"sips failed: {result.stderr or result.stdout}")


def note_html(body: str, hashtags: str) -> str:
    paragraphs = "".join(
        f"<p>{esc(line)}</p>" for line in body.splitlines() if line.strip()
    )
    return (
        f"{paragraphs}"
        f"<p>{esc(hashtags)}</p>"
    )


NOTE_APPLESCRIPT = """
on run argv
  set noteName to item 1 of argv
  set noteBody to item 2 of argv
  set imagePath to item 3 of argv
  set imageData to do shell script "/usr/bin/base64 -i " & quoted form of imagePath
  set htmlBody to noteBody & "<div><img style=\\"max-width:100%;max-height:100%;\\" src=\\"data:image/png;base64," & imageData & "\\"></div>"
  tell application "Notes"
    tell account "iCloud"
      if not (exists folder "时事简报日更") then
        make new folder at it with properties {name:"时事简报日更"}
      end if
      set targetFolder to folder "时事简报日更"
      set oldNotes to every note of targetFolder whose name is noteName
      repeat with oldNote in oldNotes
        delete oldNote
      end repeat
      set newNote to make new note at targetFolder with properties {name:noteName, body:htmlBody}
      return id of newNote
    end tell
  end tell
end run
"""


def write_note(name: str, body: str, image_path: Path) -> str:
    result = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            NOTE_APPLESCRIPT,
            "--",
            name,
            body,
            str(image_path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def load_daily_events(timeout: int) -> tuple[datetime, list[dict], list[dict]]:
    now = pulse.now_cn()
    cutoff = now - timedelta(hours=72)
    news, _ = pulse.load_feeds([], timeout, cutoff, 200)
    site_news, _ = pulse.load_site_news(timeout, cutoff, max_items_per_site=10)
    news.extend(site_news)
    commentary_items, commentary_status = pulse.load_commentary_sources(
        timeout,
        cutoff,
        max_items_per_source=8,
    )
    if not commentary_items or not any(row.ok for row in commentary_status):
        raise RuntimeError("报刊时评抓取失败")

    news_items = [item for item in news if item.published_at is None or item.published_at >= now - timedelta(hours=24)]
    news_events, _ = pulse.build_events(news_items, [], "", 24, now)
    news_dicts = [pulse.event_to_dict(event) for event in news_events]
    news_dicts = [event for event in news_dicts if not event.get("is_commentary")]

    commentary_events, _ = pulse.build_events(
        commentary_items,
        [],
        "",
        72,
        now,
        category="commentary",
    )
    commentary_dicts = [pulse.event_to_dict(event) for event in commentary_events]
    if len(news_dicts) < 3:
        raise RuntimeError("可用新闻不足三条")
    if len(commentary_dicts) < 3:
        raise RuntimeError("可用报刊评论不足三条")
    return now, news_dicts, commentary_dicts


def numbers_caption(events: list[dict], generated_at: datetime) -> tuple[str, str, str]:
    title = f"{generated_at.month}月{generated_at.day}日时事速览｜三个数字看懂今天"
    facts = "，".join(metric_sentence(event) for event in events[:3])
    body = fit_paragraph(
        [
            f"今天三个数字值得关注：{facts}。",
            "这些数字覆盖交通、产业和通信基础设施，也提示观察经济不能只看规模，还要看效率与需求能否同步改善。",
        ]
    )
    tags = "#时事热点 #新闻简报 #经济观察 #每天三分钟"
    return title, body, tags


def opinion_caption(comments: list[dict], generated_at: datetime) -> tuple[str, str, str]:
    title = f"{generated_at.month}月{generated_at.day}日观点卡｜今天，听见三种观点"
    topics = list(dict.fromkeys(commentary_topic(event) for event in comments[:3]))
    main_excerpt = short_complete_sentence(clean_commentary(comments[0]))
    body = fit_paragraph(
        [
            f"今天的报刊评论关注{'、'.join(topics)}。",
            main_excerpt,
            "这些讨论共同指向一个判断：回应公众关切，既要解释规则，也要把具体服务做到位。",
        ]
    )
    tags = "#今日观点 #媒体评论 #时事观察 #热点解读"
    return title, body, tags


def install_schedule(script_path: Path, run_time: str) -> Path:
    hour_text, minute_text = run_time.split(":", 1)
    hour, minute = int(hour_text), int(minute_text)
    label = "com.guoweibo.cn-news-pulse.daily-notes"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = SKILL_DIR / ".cache" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": label,
        "ProgramArguments": [
            "/usr/bin/python3",
            str(script_path),
        ],
        "WorkingDirectory": str(SKILL_DIR),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_dir / "daily-notes.out.log"),
        "StandardErrorPath": str(log_dir / "daily-notes.err.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
    }
    plist_path.write_bytes(plistlib.dumps(payload))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], capture_output=True)
    result = subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return plist_path


def main() -> int:
    parser = argparse.ArgumentParser(description="生成两张小红书每日卡片并写入 iCloud 备忘录。")
    parser.add_argument("--output-root", default=str(SKILL_DIR / ".cache" / "social"))
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--install-schedule", action="store_true")
    parser.add_argument("--run-time", default="07:30")
    parser.add_argument(
        "--no-notes",
        action="store_true",
        help="只生成图片，不写入备忘录",
    )
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    if args.install_schedule:
        plist = install_schedule(script_path, args.run_time)
        print(f"scheduled: {plist}")
        return 0

    generated_at, events, commentary = load_daily_events(args.timeout)
    number_events = select_number_events(events, 3)
    day_dir = Path(args.output_root) / generated_at.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    numbers_svg = day_dir / "01-numbers.svg"
    numbers_png = day_dir / "01-numbers.png"
    opinion_svg = day_dir / "02-opinion.svg"
    opinion_png = day_dir / "02-opinion.png"
    numbers_svg.write_text(build_numbers_svg(generated_at, number_events, commentary), encoding="utf-8")
    opinion_svg.write_text(build_opinion_svg(generated_at, events[0], commentary), encoding="utf-8")
    svg_to_png(numbers_svg, numbers_png)
    svg_to_png(opinion_svg, opinion_png)

    if not args.no_notes:
        number_title, number_body, number_tags = numbers_caption(number_events, generated_at)
        opinion_title, opinion_body, opinion_tags = opinion_caption(commentary, generated_at)
        note1 = write_note(
            number_title,
            note_html(number_body, number_tags),
            numbers_png,
        )
        note2 = write_note(
            opinion_title,
            note_html(opinion_body, opinion_tags),
            opinion_png,
        )
        print(f"notes: {note1} | {note2}")
    print(f"images: {numbers_png} | {opinion_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
