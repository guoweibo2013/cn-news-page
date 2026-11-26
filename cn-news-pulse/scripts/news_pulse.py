#!/usr/bin/env python3
"""Aggregate public Chinese news feeds and hot-list clues into event briefs."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import html
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin


CN_TZ = timezone(timedelta(hours=8))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36 "
    "cn-news-pulse/0.1"
)
DEFAULT_TIMEOUT = 18


@dataclass(frozen=True)
class NewsFeed:
    name: str
    publisher: str
    url: str
    authority: float
    category: str = "综合"


DEFAULT_FEEDS = (
    NewsFeed(
        "中国新闻网·即时",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/scroll-news.xml",
        0.88,
        "综合",
    ),
    NewsFeed(
        "中国新闻网·时政",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/china.xml",
        0.88,
        "时政",
    ),
    NewsFeed(
        "中国新闻网·财经",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/finance.xml",
        0.88,
        "财经",
    ),
    NewsFeed(
        "中国新闻网·国际",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/world.xml",
        0.88,
        "国际",
    ),
    NewsFeed(
        "中国新闻网·社会",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/society.xml",
        0.88,
        "社会",
    ),
    NewsFeed(
        "中国新闻网·健康",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/health.xml",
        0.88,
        "健康",
    ),
    NewsFeed(
        "中国新闻网·教育",
        "中国新闻网",
        "https://www.chinanews.com.cn/rss/edu.xml",
        0.88,
        "教育",
    ),
    NewsFeed(
        "IT之家",
        "IT之家",
        "https://www.ithome.com/rss/",
        0.70,
        "科技",
    ),
)


IMPACT_TERMS = (
    "发布",
    "政策",
    "决定",
    "通过",
    "签署",
    "批准",
    "启动",
    "通知",
    "通报",
    "回应",
    "预警",
    "事故",
    "突发",
    "重大",
    "首次",
    "成功",
    "暂停",
    "恢复",
    "调整",
    "调查",
    "处罚",
    "上涨",
    "下降",
)

TECH_TERMS = (
    "人工智能",
    "ai",
    "大模型",
    "模型",
    "芯片",
    "半导体",
    "算力",
    "数据中心",
    "服务器",
    "机器人",
    "自动驾驶",
    "软件",
    "操作系统",
    "互联网",
    "物联网",
    "通信",
    "5g",
    "6g",
    "卫星",
    "火箭",
    "航天",
    "空间站",
    "神舟",
    "量子",
    "电池",
    "新能源",
    "脑机",
    "数智",
    "数字化",
    "科技",
)

CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass
class NewsItem:
    source_id: str
    source: str
    publisher: str
    category: str
    authority: float
    title: str
    url: str
    summary: str
    published_at: Optional[datetime]
    source_kind: str = "news"


@dataclass
class HotClue:
    source_id: str
    source: str
    rank: int
    title: str
    summary: str
    url: str
    hot_value: Optional[int] = None
    category: str = ""


@dataclass
class Event:
    title: str
    summary: str
    items: list[NewsItem] = field(default_factory=list)
    hot_clues: list[HotClue] = field(default_factory=list)
    relevance: float = 1.0
    score: float = 0.0
    confidence: int = 0
    status: str = ""
    first_seen: Optional[datetime] = None
    last_updated: Optional[datetime] = None


@dataclass
class SourceStatus:
    name: str
    kind: str
    ok: bool
    items: int = 0
    detail: str = ""
    url: str = ""


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def clean_text(value: object, max_chars: int = 600) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def xml_clean(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def parse_datetime(value: str) -> Optional[datetime]:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(
        r"^(\d{4}-\d{2}-\d{2})-(\d{2}:\d{2}(?::\d{2})?)$",
        r"\1 \2",
        text,
    )
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = None
    if dt is None:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            pass
    if dt is None:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN_TZ)
    return dt.astimezone(CN_TZ)


def iso_time(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat(timespec="minutes") if value else None


def display_time(value: Optional[datetime]) -> str:
    return value.strftime("%m-%d %H:%M") if value else "时间未知"


def fetch_bytes(
    url: str,
    timeout: int,
    extra_headers: Optional[dict[str, str]] = None,
) -> tuple[bytes, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, "
        "text/xml, application/json, text/html;q=0.8, */*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.4",
        "Accept-Encoding": "identity",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        content_encoding = (response.headers.get("Content-Encoding") or "").lower()
        data = response.read(3_000_000)
        try:
            if "gzip" in content_encoding:
                data = gzip.decompress(data)
            elif "deflate" in content_encoding:
                data = zlib.decompress(data)
        except (OSError, EOFError, zlib.error):
            pass
        return data, content_type


def decode_response(data: bytes, content_type: str) -> str:
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in encodings:
        try:
            return data.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def canonicalize_simple_numeral(value: str) -> str:
    if not value:
        return value
    if "十" not in value:
        return "".join(str(CN_DIGITS[char]) for char in value)
    tens_text, _, ones_text = value.partition("十")
    tens = CN_DIGITS.get(tens_text[-1], 1) if tens_text else 1
    ones = CN_DIGITS.get(ones_text[0], 0) if ones_text else 0
    return str(tens * 10 + ones)


def normalize_title(value: str) -> str:
    text = clean_text(value, 300).lower()
    text = re.sub(
        r"[零〇一二两三四五六七八九十]+",
        lambda match: canonicalize_simple_numeral(match.group(0)),
        text,
    )
    text = re.sub(r"[""''《》【】\[\]（）()：:，,。.!！?？、|｜—\-]", "", text)
    text = re.sub(
        r"(视频|图文|直播|快讯|最新|独家|消息|新闻|记者|报道|正式|今日|今日要闻)",
        "",
        text,
    )
    text = text.replace("神舟", "神").replace("载人飞船", "飞船")
    text = text.replace("航天员", "航天").replace("乘组", "")
    text = text.replace("号", "") if "神" in text else text
    return re.sub(r"\s+", "", text)


def char_bigrams(value: str) -> set[str]:
    text = normalize_title(value)
    chunks = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text)
    grams: set[str] = set()
    for chunk in chunks:
        if len(chunk) == 1:
            grams.add(chunk)
        else:
            grams.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return grams


def longest_common_substring(left: str, right: str) -> int:
    a = normalize_title(left)
    b = normalize_title(right)
    if not a or not b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    previous = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        current = [0] * (len(b) + 1)
        for index, cb in enumerate(b, 1):
            if ca == cb:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def title_similarity(left: str, right: str) -> tuple[float, int]:
    a = normalize_title(left)
    b = normalize_title(right)
    if not a or not b:
        return 0.0, 0
    if a == b:
        return 1.0, min(len(a), len(b))
    sequence = SequenceMatcher(None, a, b).ratio()
    grams_a = char_bigrams(a)
    grams_b = char_bigrams(b)
    union = grams_a | grams_b
    jaccard = len(grams_a & grams_b) / len(union) if union else 0.0
    common = longest_common_substring(a, b)
    containment = (
        min(len(a), len(b)) / max(len(a), len(b))
        if (a in b or b in a)
        else 0.0
    )
    combined = max(sequence, jaccard, containment)
    return combined, common


def entity_keys(value: str) -> set[str]:
    text = normalize_title(value)
    keys: set[str] = set()
    patterns = (
        r"神[0-9]{1,4}",
        r"[A-Za-z][A-Za-z0-9.+-]{2,20}",
        r"[\u4e00-\u9fff]{2,10}(?:省|市|区|县|大学|公司|集团|银行|法院|检察院|委员会|管理局)",
        r"\d{1,2}月\d{1,2}日",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text):
            if (match.startswith("神") and re.search(r"\d", match)) or len(match) >= 4:
                keys.add(match)
    return keys


def is_same_event(left: str, right: str) -> bool:
    similarity, common = title_similarity(left, right)
    if similarity >= 0.62:
        return True
    shared_entities = entity_keys(left) & entity_keys(right)
    if shared_entities:
        return True
    if common >= 8 and similarity >= 0.32:
        return True
    return common >= 6 and similarity >= 0.46


def query_relevance(query: str, title: str, summary: str) -> float:
    if not query.strip():
        return 1.0
    needle = normalize_title(query)
    haystack = normalize_title(f"{title} {summary}")
    if not needle or not haystack:
        return 0.0
    if needle in haystack:
        return 1.0
    query_terms = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+|\d+", needle)
    if len(query_terms) > 1:
        term_coverage = sum(1 for term in query_terms if term in haystack) / len(query_terms)
        if term_coverage < 1.0:
            return min(0.20, term_coverage * 0.20)
    query_grams = char_bigrams(needle)
    if not query_grams:
        return 0.0
    overlap = len(query_grams & char_bigrams(haystack)) / len(query_grams)
    common_ratio = longest_common_substring(needle, haystack) / max(1, len(needle))
    return min(1.0, max(overlap, common_ratio * 0.60))


def parse_rss(
    text: str,
    feed: NewsFeed,
    cutoff: datetime,
    max_items: int,
) -> list[NewsItem]:
    if not text.lstrip().startswith("<"):
        raise ValueError("response is not XML/RSS")
    root = ET.fromstring(xml_clean(text))
    atoms = {"a": "http://www.w3.org/2005/Atom"}
    items: list[NewsItem] = []

    rss_items = root.findall(".//item")
    if not rss_items:
        rss_items = root.findall(".//a:entry", atoms)

    for node in rss_items[: max_items * 3]:
        if node.tag.endswith("entry"):
            title = clean_text(node.findtext("a:title", default="", namespaces=atoms), 240)
            link_node = node.find("a:link", atoms)
            url = link_node.get("href", "") if link_node is not None else ""
            summary = clean_text(
                node.findtext("a:summary", default="", namespaces=atoms)
                or node.findtext("a:content", default="", namespaces=atoms),
                700,
            )
            date_text = (
                node.findtext("a:published", default="", namespaces=atoms)
                or node.findtext("a:updated", default="", namespaces=atoms)
            )
        else:
            title = clean_text(node.findtext("title", default=""), 240)
            url = clean_text(node.findtext("link", default=""), 800)
            summary = clean_text(
                node.findtext("description", default="")
                or node.findtext("summary", default=""),
                700,
            )
            date_text = (
                node.findtext("pubDate", default="")
                or node.findtext("published", default="")
                or node.findtext("updated", default="")
            )

        if not title:
            continue
        published_at = parse_datetime(date_text)
        if published_at and published_at < cutoff:
            continue
        items.append(
            NewsItem(
                source_id=fed_id(feed.name),
                source=feed.name,
                publisher=feed.publisher,
                category=feed.category,
                authority=feed.authority,
                title=title,
                url=url,
                summary=summary or title,
                published_at=published_at,
            )
        )
        if len(items) >= max_items:
            break
    return items


def fed_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or sha1(value)


def parse_baidu_hot(text: str) -> list[HotClue]:
    match = re.search(r"<!--s-data:(.*?)-->", text, re.S)
    if not match:
        raise ValueError("embedded Baidu hot-board data not found")
    payload = json.loads(match.group(1))
    cards = ((payload.get("data") or {}).get("cards") or [])
    rows: list[dict] = []
    for card in cards:
        if card.get("component") == "hotList":
            rows = card.get("content") or []
            break
    clues: list[HotClue] = []
    for index, row in enumerate(rows[:60]):
        title = clean_text(row.get("word") or row.get("query"), 180)
        if not title:
            continue
        hot_score = row.get("hotScore")
        try:
            hot_value = int(hot_score) if hot_score is not None else None
        except (TypeError, ValueError):
            hot_value = None
        clues.append(
            HotClue(
                source_id="baidu_hot",
                source="百度热搜",
                rank=index + 1,
                title=title,
                summary=clean_text(row.get("desc"), 500),
                url=clean_text(row.get("url") or row.get("appUrl") or row.get("rawUrl"), 900),
                hot_value=hot_value,
                category="热榜",
            )
        )
    return clues


def parse_bilibili_hot(text: str) -> list[HotClue]:
    payload = json.loads(text)
    if payload.get("code") != 0:
        raise ValueError(f"Bilibili API error: {payload.get('message') or payload.get('code')}")
    rows = ((payload.get("data") or {}).get("list") or [])
    clues: list[HotClue] = []
    for index, row in enumerate(rows[:30]):
        title = clean_text(row.get("title"), 180)
        if not title:
            continue
        bvid = clean_text(row.get("bvid"), 40)
        owner = clean_text((row.get("owner") or {}).get("name"), 80)
        stats = row.get("stat") or {}
        views = stats.get("view")
        summary_parts = [part for part in (row.get("desc"), owner) if part]
        if views:
            summary_parts.append(f"{views} 播放")
        clues.append(
            HotClue(
                source_id="bilibili_hot",
                source="B站热门",
                rank=index + 1,
                title=title,
                summary=clean_text(" · ".join(summary_parts), 400),
                url=f"https://www.bilibili.com/video/{bvid}" if bvid else "",
                hot_value=int(views) if isinstance(views, int) else None,
                category=clean_text(row.get("tname") or row.get("tname"), 40),
            )
        )
    return clues


def load_feeds(
    extra_feeds: list[str],
    timeout: int,
    cutoff: datetime,
    max_items_per_feed: int,
) -> tuple[list[NewsItem], list[SourceStatus]]:
    feeds = list(DEFAULT_FEEDS)
    for spec in extra_feeds:
        if "=" not in spec:
            raise ValueError(f"--rss expects NAME=URL, got {spec!r}")
        name, url = spec.split("=", 1)
        feeds.append(NewsFeed(name.strip() or "自定义RSS", name.strip() or "自定义RSS", url.strip(), 0.75))

    all_items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    for feed in feeds:
        try:
            data, content_type = fetch_bytes(feed.url, timeout)
            text = decode_response(data, content_type)
            items = parse_rss(text, feed, cutoff, max_items_per_feed)
            all_items.extend(items)
            statuses.append(
                SourceStatus(feed.name, "news", True, len(items), "RSS解析正常", feed.url)
            )
        except Exception as exc:
            statuses.append(
                SourceStatus(feed.name, "news", False, 0, f"{type(exc).__name__}: {exc}", feed.url)
            )
    return all_items, statuses


def meta_value(markup: str, name: str) -> str:
    wanted = name.lower()
    for tag in re.findall(r"<meta\b[^>]*>", markup, re.I):
        name_match = re.search(
            r"""(?:name|property)\s*=\s*["']([^"']+)["']""",
            tag,
            re.I,
        )
        if not name_match or name_match.group(1).lower() != wanted:
            continue
        content_match = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
        if content_match:
            return html.unescape(content_match.group(1)).strip()
    return ""


def first_article_paragraph(markup: str) -> str:
    candidates = []
    for value in re.findall(r"<p\b[^>]*>(.*?)</p>", markup, re.I | re.S):
        text = clean_text(value, 700)
        if len(text) >= 25:
            candidates.append(text)
    if not candidates:
        return ""
    preferred = [
        text
        for text in candidates
        if not text.startswith(("责任编辑", "分享", "相关阅读", "新华网"))
    ]
    return (preferred or candidates)[0]


def fetch_html_article(
    link: str,
    title_hint: str,
    source_name: str,
    publisher: str,
    category: str,
    authority: float,
    timeout: int,
) -> Optional[NewsItem]:
    try:
        data, content_type = fetch_bytes(link, timeout)
        markup = decode_response(data, content_type)
    except Exception:
        return None

    title = (
        clean_text(meta_value(markup, "og:title"), 240)
        or clean_text(title_hint, 240)
    )
    if not title:
        return None

    time_text = (
        meta_value(markup, "firstpublishedtime")
        or meta_value(markup, "publishdate")
    )
    if not time_text or not re.search(r"\d{2}:\d{2}", time_text):
        match = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})", markup)
        if match:
            time_text = f"{match.group(1)} {match.group(2)}"
    published_at = parse_datetime(time_text)

    summary = (
        clean_text(meta_value(markup, "description"), 700)
        or first_article_paragraph(markup)
        or title
    )
    return NewsItem(
        source_id=fed_id(source_name),
        source=source_name,
        publisher=publisher,
        category=category,
        authority=authority,
        title=title,
        url=link,
        summary=summary,
        published_at=published_at,
    )


def extract_site_links(
    homepage: str,
    base_url: str,
    pattern: str,
    limit: int,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, title in re.findall(pattern, homepage, re.I | re.S):
        url = urljoin(base_url, html.unescape(href))
        title = clean_text(title, 200)
        if not title or len(title) < 6 or url in seen:
            continue
        seen.add(url)
        rows.append((url, title))
        if len(rows) >= limit:
            break
    return rows


def load_site_news(
    timeout: int,
    cutoff: datetime,
    max_items_per_site: int = 10,
) -> tuple[list[NewsItem], list[SourceStatus]]:
    sites = (
        {
            "name": "中国政府网·要闻",
            "publisher": "中国政府网",
            "home": "https://www.gov.cn/",
            "base": "https://www.gov.cn/",
            "pattern": r"""href=["'](https://www\.gov\.cn/yaowen/liebiao/\d{6}/content_\d+\.htm)["'][^>]*>\s*([^<]{6,160})""",
            "category": "时政",
            "authority": 0.96,
        },
        {
            "name": "新华网·要闻",
            "publisher": "新华网",
            "home": "https://www.news.cn/",
            "base": "https://www.news.cn/",
            "pattern": r"""href=["']((?:https?://www\.news\.cn)?/?[^"']*?\d{8}/[0-9a-f]{32}/c\.html)["'][^>]*>\s*([^<]{6,160})""",
            "category": "综合",
            "authority": 0.93,
        },
    )
    items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    for site in sites:
        try:
            data, content_type = fetch_bytes(site["home"], timeout)
            homepage = decode_response(data, content_type)
            links = extract_site_links(
                homepage,
                site["base"],
                site["pattern"],
                max_items_per_site,
            )
            if not links:
                raise ValueError("no article links found on homepage")
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(
                        fetch_html_article,
                        url,
                        title,
                        site["name"],
                        site["publisher"],
                        site["category"],
                        site["authority"],
                        timeout,
                    )
                    for url, title in links
                ]
                fetched = [future.result() for future in futures]
            parsed = [
                item
                for item in fetched
                if item is not None
                and (item.published_at is None or item.published_at >= cutoff)
            ]
            items.extend(parsed)
            statuses.append(
                SourceStatus(
                    site["name"],
                    "news",
                    bool(parsed),
                    len(parsed),
                    "首页文章解析正常" if parsed else "首页文章不在时间窗口内",
                    site["home"],
                )
            )
        except Exception as exc:
            statuses.append(
                SourceStatus(
                    site["name"],
                    "news",
                    False,
                    0,
                    f"{type(exc).__name__}: {exc}",
                    site["home"],
                )
            )
    return items, statuses


def extract_anchor_links(
    homepage: str,
    base_url: str,
    limit: int,
    mode: str,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for attrs, inner in re.findall(r"<a\b([^>]*)>(.*?)</a>", homepage, re.I | re.S):
        href_match = re.search(r"""href\s*=\s*["']([^"']+)["']""", attrs, re.I)
        if not href_match:
            continue
        url = urljoin(base_url, html.unescape(href_match.group(1)))
        title_match = re.search(r"""title\s*=\s*["']([^"']+)["']""", attrs, re.I)
        title = clean_text(
            title_match.group(1) if title_match else inner,
            220,
        )
        if not title or len(title) < 6 or url in seen:
            continue
        if mode == "people":
            allowed = re.search(
                r"^https?://opinion\.people\.com\.cn/n1/\d{4}/\d{4}/[^/]+\.html",
                url,
            )
        elif mode == "guangming":
            allowed = (
                "guancha.gmw.cn/" in url
                and re.search(r"/\d{4}-\d{2}/\d{2}/content_\d+\.htm$", url)
            )
        elif mode == "bjnews":
            allowed = (
                "bjnews.com.cn/detail/" in url
                and any(term in title for term in ("快评", "社论", "专栏", "评论"))
            )
        else:
            allowed = False
        if not allowed:
            continue
        seen.add(url)
        rows.append((url, title))
    if mode == "people":
        def link_date_key(row: tuple[str, str]) -> tuple[int, int, int]:
            match = re.search(r"/n1/(\d{4})/(\d{2})(\d{2})/", row[0])
            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            ) if match else (0, 0, 0)
        rows.sort(key=link_date_key, reverse=True)
    elif mode == "guangming":
        def link_date_key(row: tuple[str, str]) -> tuple[int, int, int]:
            match = re.search(r"/(\d{4})-(\d{2})/(\d{2})/", row[0])
            return (
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            ) if match else (0, 0, 0)
        rows.sort(key=link_date_key, reverse=True)
    return rows[:limit]


def commentary_column(title: str) -> str:
    for term in (
        "人民锐评",
        "壹时评",
        "光明时评",
        "光明观察",
        "评论员",
        "新京报社论",
        "新京报快评",
        "新京报专栏",
        "社论",
        "快评",
        "专栏",
    ):
        if term in title:
            return term.replace("新京报", "")
    return "时评"


def fetch_commentary_article(
    url: str,
    title_hint: str,
    source_name: str,
    publisher: str,
    authority: float,
    timeout: int,
) -> Optional[NewsItem]:
    try:
        data, content_type = fetch_bytes(url, timeout)
        markup = decode_response(data, content_type)
    except Exception:
        return None

    title = (
        clean_text(meta_value(markup, "og:title"), 240)
        or clean_text(title_hint, 240)
    )
    title = re.sub(r"[_\-—|｜]\s*(光明网|新京报).*$", "", title).strip()
    if not title:
        return None

    time_text = (
        meta_value(markup, "article:published_time")
        or meta_value(markup, "firstpublishedtime")
        or meta_value(markup, "publishdate")
    )
    if not re.search(r"\d{2}:\d{2}", time_text):
        match = re.search(
            r"""(?:class\s*=\s*["']timer["'][^>]*>|published_time[^>]*content=["'])(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)""",
            markup,
            re.I,
        )
        if match:
            time_text = match.group(1)
        else:
            cn_match = re.search(
                r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{2}):(\d{2})",
                markup,
            )
            if cn_match:
                year, month, day, hour, minute = map(int, cn_match.groups())
                time_text = (
                    f"{year:04d}-{month:02d}-{day:02d} "
                    f"{hour:02d}:{minute:02d}"
                )
    published_at = parse_datetime(time_text)

    summary = clean_text(meta_value(markup, "description"), 700)
    if not summary or summary.startswith("新京报以文字、图片、视频"):
        content_match = re.search(
            r"""id\s*=\s*["']contentStr["'][^>]*>(.*?)(?:</article>|<div\s+class=["'][^"']*share)""",
            markup,
            re.I | re.S,
        )
        section = content_match.group(1) if content_match else markup
        summary = first_article_paragraph(section)
    summary = clean_text(summary, 700)
    if not summary or summary == title:
        summary = title
    if len(summary) > 260:
        summary = summary[:260].rstrip("，。；、 ") + "…"
    column = commentary_column(title)
    if column not in summary[:30]:
        summary = f"{column}｜{summary}"

    return NewsItem(
        source_id=fed_id(source_name),
        source=source_name,
        publisher=publisher,
        category="时评",
        authority=authority,
        title=title,
        url=url,
        summary=summary,
        published_at=published_at,
    )


def load_commentary_sources(
    timeout: int,
    cutoff: datetime,
    max_items_per_source: int = 8,
) -> tuple[list[NewsItem], list[SourceStatus]]:
    sources = (
        {
            "name": "人民日报·观点",
            "publisher": "人民日报",
            "home": "http://opinion.people.com.cn/",
            "base": "http://opinion.people.com.cn/",
            "mode": "people",
            "authority": 0.96,
        },
        {
            "name": "光明网·时评",
            "publisher": "光明日报",
            "home": "https://guancha.gmw.cn/",
            "base": "https://guancha.gmw.cn/",
            "mode": "guangming",
            "authority": 0.94,
        },
        {
            "name": "新京报·评论",
            "publisher": "新京报",
            "home": "https://www.bjnews.com.cn/point",
            "base": "https://www.bjnews.com.cn/",
            "mode": "bjnews",
            "authority": 0.82,
        },
    )
    items: list[NewsItem] = []
    statuses: list[SourceStatus] = []
    for source in sources:
        try:
            data, content_type = fetch_bytes(source["home"], timeout)
            homepage = decode_response(data, content_type)
            links = extract_anchor_links(
                homepage,
                source["base"],
                max_items_per_source,
                source["mode"],
            )
            if not links:
                raise ValueError("no commentary article links found")
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(
                        fetch_commentary_article,
                        url,
                        title,
                        source["name"],
                        source["publisher"],
                        source["authority"],
                        timeout,
                    )
                    for url, title in links
                ]
                fetched = [future.result() for future in futures]
            parsed = [
                item
                for item in fetched
                if item is not None
                and (item.published_at is None or item.published_at >= cutoff)
            ]
            items.extend(parsed)
            statuses.append(
                SourceStatus(
                    source["name"],
                    "commentary",
                    bool(parsed),
                    len(parsed),
                    "时评栏目解析正常" if parsed else "时评不在时间窗口内",
                    source["home"],
                )
            )
        except Exception as exc:
            statuses.append(
                SourceStatus(
                    source["name"],
                    "commentary",
                    False,
                    0,
                    f"{type(exc).__name__}: {exc}",
                    source["home"],
                )
            )
    return items, statuses


def load_hot_clues(
    timeout: int,
    include_baidu: bool,
    include_bilibili: bool,
) -> tuple[list[HotClue], list[SourceStatus]]:
    clues: list[HotClue] = []
    statuses: list[SourceStatus] = []
    if include_baidu:
        url = "https://top.baidu.com/board?tab=realtime"
        try:
            data, content_type = fetch_bytes(
                url,
                timeout,
                {"Referer": "https://top.baidu.com/board?tab=realtime"},
            )
            parsed = parse_baidu_hot(decode_response(data, content_type))
            clues.extend(parsed)
            statuses.append(SourceStatus("百度热搜", "hot", True, len(parsed), "热榜解析正常", url))
        except Exception as exc:
            statuses.append(
                SourceStatus("百度热搜", "hot", False, 0, f"{type(exc).__name__}: {exc}", url)
            )
    if include_bilibili:
        urls = (
            "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",
            "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1",
        )
        url = urls[0]
        try:
            last_error: Optional[Exception] = None
            parsed: list[HotClue] = []
            successful_url = url
            for candidate_url in urls:
                for attempt in range(2):
                    try:
                        data, content_type = fetch_bytes(
                            candidate_url,
                            timeout,
                            {
                                "Referer": "https://www.bilibili.com/v/popular/rank/all" if "ranking" in candidate_url else "https://www.bilibili.com/v/popular/all",
                                "Origin": "https://www.bilibili.com",
                            },
                        )
                        parsed = parse_bilibili_hot(decode_response(data, content_type))
                        successful_url = candidate_url
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt == 0:
                            time.sleep(0.7)
                if last_error is None:
                    break
            if last_error is not None:
                raise last_error
            clues.extend(parsed)
            statuses.append(SourceStatus("B站热门", "hot", True, len(parsed), "热榜解析正常", successful_url))
        except Exception as exc:
            statuses.append(
                SourceStatus("B站热门", "hot", False, 0, f"{type(exc).__name__}: {exc}", url)
            )
    return clues, statuses


def matches_category(item: NewsItem, category: str) -> bool:
    wanted = category.strip().lower()
    if item.category == "时评":
        return wanted in {"commentary", "opinion", "commentary_all"}
    if wanted in {"commentary", "opinion", "commentary_all"}:
        return False
    if not wanted or wanted == "all":
        return True
    if wanted == "tech":
        text = (item.title + " " + item.summary + " " + item.category).lower()
        return item.publisher == "IT之家" or any(term in text for term in TECH_TERMS)
    category_aliases = {
        "policy": "时政",
        "finance": "财经",
        "world": "国际",
        "international": "国际",
        "society": "社会",
        "culture": "文化",
        "commentary": "报刊时评",
        "opinion": "报刊时评",
    }
    return item.category == category_aliases.get(wanted, category)


def hot_matches_category(clue: HotClue, category: str) -> bool:
    wanted = category.strip().lower()
    if wanted in {"commentary", "opinion", "commentary_all"}:
        return False
    if not wanted or wanted == "all":
        return True
    if wanted == "tech":
        text = (clue.title + " " + clue.summary + " " + clue.category).lower()
        return any(term in text for term in TECH_TERMS)
    return True


def build_events(
    news_items: list[NewsItem],
    hot_clues: list[HotClue],
    query: str,
    window_hours: int,
    reference_time: datetime,
    category: str = "",
) -> tuple[list[Event], list[HotClue]]:
    filtered_news: list[NewsItem] = []
    for item in news_items:
        if not matches_category(item, category):
            continue
        item_relevance = query_relevance(query, item.title, item.summary)
        if not query or item_relevance >= 0.22:
            filtered_news.append(item)

    filtered_hot: list[HotClue] = []
    for clue in hot_clues:
        if not hot_matches_category(clue, category):
            continue
        clue_relevance = query_relevance(query, clue.title, clue.summary)
        if not query or clue_relevance >= 0.32:
            filtered_hot.append(clue)

    clusters: list[Event] = []
    for item in sorted(
        filtered_news,
        key=lambda row: row.published_at or datetime.min.replace(tzinfo=CN_TZ),
    ):
        match: Optional[Event] = None
        for event in clusters:
            if any(is_same_event(item.title, existing.title) for existing in event.items):
                match = event
                break
            if item.url and any(item.url == existing.url for existing in event.items):
                match = event
                break
        relevance = query_relevance(query, item.title, item.summary)
        if match is None:
            match = Event(
                title=item.title,
                summary=item.summary,
                relevance=relevance,
                first_seen=item.published_at,
                last_updated=item.published_at,
            )
            clusters.append(match)
        else:
            match.relevance = max(match.relevance, relevance)
        match.items.append(item)
        if item.summary and len(item.summary) > len(match.summary):
            match.summary = item.summary
        if item.published_at:
            match.first_seen = min(
                value for value in (match.first_seen, item.published_at) if value is not None
            )
            match.last_updated = max(
                value for value in (match.last_updated, item.published_at) if value is not None
            )

    unmatched_hot: list[HotClue] = []
    for clue in filtered_hot:
        best_event: Optional[Event] = None
        best_similarity = 0.0
        for event in clusters:
            similarity, common = title_similarity(clue.title, event.title)
            if similarity > best_similarity:
                best_similarity = similarity
                best_event = event
            if common >= 6 and similarity >= 0.46:
                best_similarity = similarity
                best_event = event
                break
        if best_event is not None and is_same_event(clue.title, best_event.title):
            best_event.hot_clues.append(clue)
        elif query:
            # A closely related hot search is still useful as attention evidence.
            if best_event is not None and best_similarity >= 0.32:
                best_event.hot_clues.append(clue)
            else:
                unmatched_hot.append(clue)
        else:
            unmatched_hot.append(clue)

    for event in clusters:
        score_event(event, window_hours, reference_time)
    clusters.sort(key=lambda event: (event.score, event.last_updated or datetime.min.replace(tzinfo=CN_TZ)), reverse=True)

    # The hot-board remainder is useful only when it did not become an event.
    hot_event_ids = {
        clue.source_id + ":" + str(clue.rank)
        for event in clusters
        for clue in event.hot_clues
    }
    standalone_hot = [
        clue
        for clue in filtered_hot
        if clue.source_id + ":" + str(clue.rank) not in hot_event_ids
    ]
    return clusters, standalone_hot


def score_event(event: Event, window_hours: int, reference_time: datetime) -> None:
    latest = event.last_updated or reference_time
    age_hours = max(0.0, (reference_time - latest).total_seconds() / 3600.0)
    freshness = math.exp(-age_hours / max(8.0, window_hours / 2.2))

    publishers = {item.publisher for item in event.items}
    max_authority = max((item.authority for item in event.items), default=0.35)
    corroboration = min(1.0, max(0, len(publishers) - 1) / 2.0)
    attention = 0.0
    if event.hot_clues:
        best_rank = min(clue.rank for clue in event.hot_clues)
        attention = max(0.15, 1.0 - (best_rank - 1) / 50.0)
    impact_text = event.title + " " + event.summary
    impact = 1.0 if any(term in impact_text for term in IMPACT_TERMS) else 0.0

    event.score = round(
        100
        * (
            0.30 * freshness
            + 0.27 * max_authority
            + 0.18 * corroboration
            + 0.12 * attention
            + 0.08 * impact
            + 0.05 * event.relevance
        ),
        1,
    )

    source_confidence = (
        45 * max_authority
        + 30 * min(1.0, len(publishers) / 3.0)
        + 15 * (1.0 if event.items else 0.0)
        + 10 * freshness
    )
    event.confidence = max(15, min(97, round(source_confidence)))

    if len(publishers) >= 2:
        event.status = "多方报道"
    elif event.items:
        event.status = "单源报道"
    else:
        event.status = "热榜线索 · 待核实"


def parse_rss_spec(value: str) -> str:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=URL")
    return value


def event_why_important(event: Event) -> list[str]:
    text = event.title + " " + event.summary
    publishers = {item.publisher for item in event.items}
    official_count = len({item.publisher for item in event.items if item.authority >= 0.90})
    reasons: list[str] = []
    if event.items and all(item.category == "时评" for item in event.items):
        reasons.append("主流报刊评论，适合作为观点和论证参考")
    if official_count:
        reasons.append("已有政府网站或中央媒体直接来源")
    if len(publishers) >= 2:
        reasons.append(f"{len(publishers)} 个独立出版方形成交叉报道")
    if any(term in text for term in TECH_TERMS):
        reasons.append("涉及科技、产业或数字基础设施")
    if any(term in text for term in ("政策", "立法", "条例", "标准", "通知", "决定")):
        reasons.append("可能影响公共规则、行业标准或办事流程")
    if any(term in text for term in ("事故", "预警", "失联", "通报", "调查", "处罚", "安全")):
        reasons.append("涉及公共安全、风险或监管进展")
    if any(term in text for term in ("启动", "发布", "首次", "成功", "突破", "签署")):
        reasons.append("包含可核实的阶段性进展或首次发生事项")
    if event.hot_clues:
        best_rank = min(clue.rank for clue in event.hot_clues)
        if best_rank <= 20:
            reasons.append(f"进入热榜前 {best_rank} 位，公众关注度较高")
    return reasons[:4] or ["当前主要依据新闻时效与来源完整性进入候选列表"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="汇总国内公开新闻RSS与热榜线索，按事件去重并生成简报。"
    )
    parser.add_argument("topic", nargs="?", default="", help="可选主题或关键词")
    parser.add_argument("--hours", type=int, default=24, help="回看窗口，默认24小时")
    parser.add_argument(
        "--category",
        default="all",
        choices=(
            "all",
            "tech",
            "policy",
            "finance",
            "world",
            "international",
            "society",
            "culture",
            "commentary",
            "opinion",
        ),
        help="新闻分类；科技类请使用 tech",
    )
    parser.add_argument("--limit", type=int, default=12, help="输出事件数量，默认12")
    parser.add_argument("--hot-limit", type=int, default=12, help="独立热榜线索数量，默认12")
    parser.add_argument(
        "--emit",
        choices=("markdown", "json", "html"),
        default="markdown",
        help="输出格式",
    )
    parser.add_argument("--output", help="写入文件；省略时输出到标准输出")
    parser.add_argument("--rss", action="append", default=[], type=parse_rss_spec, help="附加RSS，格式 NAME=URL")
    parser.add_argument("--no-hot", action="store_true", help="不抓取百度热搜和B站热门")
    parser.add_argument("--no-baidu", action="store_true", help="不抓取百度热搜")
    parser.add_argument("--no-bilibili", action="store_true", help="不抓取B站热门")
    parser.add_argument("--no-site-news", action="store_true", help="不抓取政府和新华网首页要闻")
    parser.add_argument("--no-commentary", action="store_true", help="不抓取报刊时评栏目")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单请求超时秒数")
    parser.add_argument("--max-items-per-feed", type=int, default=100, help="每个RSS最多读取条数")
    parser.add_argument("--self-test", action="store_true", help="运行离线自检")
    return parser


def event_to_dict(event: Event) -> dict:
    publishers = sorted({item.publisher for item in event.items})
    official_publishers = sorted(
        {item.publisher for item in event.items if item.authority >= 0.90}
    )
    ordered_items = sorted(
        event.items,
        key=lambda row: row.published_at or datetime.min.replace(tzinfo=CN_TZ),
        reverse=True,
    )
    timeline = []
    seen_urls: set[str] = set()
    for item in sorted(
        event.items,
        key=lambda row: row.published_at or datetime.min.replace(tzinfo=CN_TZ),
    ):
        if not item.url or item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        timeline.append(
            {
                "time": iso_time(item.published_at),
                "source": item.source,
                "publisher": item.publisher,
                "title": item.title,
                "url": item.url,
                "tier": "official" if item.authority >= 0.90 else "media",
            }
        )
    return {
        "event_id": sha1(normalize_title(event.title)),
        "title": event.title,
        "summary": event.summary,
        "status": event.status,
        "score": event.score,
        "confidence": event.confidence,
        "relevance": round(event.relevance, 3),
        "first_seen": iso_time(event.first_seen),
        "last_updated": iso_time(event.last_updated),
        "publishers": publishers,
        "official_publishers": official_publishers,
        "is_commentary": bool(event.items) and all(
            item.category == "时评" for item in event.items
        ),
        "commentary_outlets": sorted(
            {item.publisher for item in event.items if item.category == "时评"}
        ),
        "why_important": event_why_important(event),
        "timeline": timeline,
        "sources": [
            {
                "name": item.source,
                "publisher": item.publisher,
                "title": item.title,
                "url": item.url,
                "published_at": iso_time(item.published_at),
            }
            for item in ordered_items
        ],
        "hot_clues": [asdict(clue) for clue in event.hot_clues],
    }


def build_payload(
    events: list[Event],
    standalone_hot: list[HotClue],
    source_status: list[SourceStatus],
    topic: str,
    hours: int,
    generated_at: datetime,
    news_count: int,
    hot_count: int,
    event_count_total: int,
    category: str = "all",
) -> dict:
    return {
        "meta": {
            "generated_at": iso_time(generated_at),
            "timezone": "Asia/Shanghai",
            "window_hours": hours,
            "topic": topic or None,
            "category": category,
            "news_items": news_count,
            "hot_clues": hot_count,
            "event_count": event_count_total,
            "events_shown": len(events),
            "method": "RSS news + public hot-list clues; event-level title clustering",
        },
        "source_status": [asdict(row) for row in source_status],
        "events": [event_to_dict(event) for event in events],
        "standalone_hot": [asdict(clue) for clue in standalone_hot],
        "notice": "热搜和热榜只代表注意力线索；评分表示检索优先级，不是事实真实性的概率。",
    }


def md_cell(value: object, max_chars: int = 180) -> str:
    text = clean_text(value, max_chars).replace("|", "\\|").replace("\n", " ")
    return text or "-"


def clip_summary(value: str, max_chars: int = 340) -> str:
    text = clean_text(value, max_chars + 80)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip("，。；、 ") + "…"


def render_markdown(payload: dict) -> str:
    meta = payload["meta"]
    events = payload["events"]
    category_labels = {
        "tech": "科技",
        "policy": "时政",
        "finance": "财经",
        "world": "国际",
        "international": "国际",
        "society": "社会",
        "culture": "文化",
        "commentary": "报刊时评",
        "opinion": "报刊时评",
    }
    title = "国内时事简报"
    if meta.get("topic"):
        title += f"｜{meta['topic']}"
    elif meta.get("category") in category_labels:
        title += f"｜{category_labels[meta['category']]}"
    lines = [
        f"# {title}",
        "",
        f"> 窗口：最近 {meta['window_hours']} 小时 · 生成于 {meta['generated_at']}",
        f"> 共读取 {meta['news_items']} 条新闻、{meta['hot_clues']} 条热榜线索，识别 {meta['event_count']} 个候选事件，当前展示 {meta['events_shown']} 个。",
        "> 热搜与热榜仅用于发现关注度，不作为独立事实来源。",
        "",
    ]

    if not events:
        lines.extend(
            [
                "## 暂无匹配事件",
                "",
                "当前窗口和来源没有返回可展示的事件。可扩大 `--hours`、更换关键词或检查来源状态。",
                "",
            ]
        )
    else:
        lead = events[:3]
        lines.extend(["## 今日主线", ""])
        for index, event in enumerate(lead, 1):
            publishers = "、".join(event["publishers"]) or "无新闻RSS来源"
            hot = event["hot_clues"][0]["title"] if event["hot_clues"] else ""
            lines.append(
                f"### {index}. {event['title']}"
            )
            lines.append("")
            lines.append(
                f"**{event['status']} · 优先级 {event['score']:.1f} · 置信度 {event['confidence']}**"
            )
            lines.append("")
            if event.get("why_important"):
                lines.append("为什么重要：" + "；".join(event["why_important"]) + "。")
                lines.append("")
            lines.append(clip_summary(event["summary"]) or "暂无摘要。")
            lines.append("")
            lines.append(
                f"- 时间：{display_time_iso(event['first_seen'])} 至 {display_time_iso(event['last_updated'])}"
            )
            lines.append(f"- 新闻来源：{publishers}")
            if hot:
                lines.append(f"- 热榜线索：{hot}")
            for source in event["sources"][:3]:
                if source["url"]:
                    lines.append(f"- [{source['name']}]({source['url']})")
            lines.append("")

        lines.extend(
            [
                "## 事件列表",
                "",
                "| # | 事件 | 状态 | 新闻来源 | 优先级 | 最近更新 |",
                "|---:|---|---|---|---:|---|",
            ]
        )
        for index, event in enumerate(events, 1):
            lines.append(
                "| {} | {} | {} | {} | {:.1f} | {} |".format(
                    index,
                    md_cell(event["title"], 90),
                    md_cell(event["status"], 30),
                    md_cell("、".join(event["publishers"]) or "热榜", 50),
                    event["score"],
                    display_time_iso(event["last_updated"]),
                )
            )
        lines.append("")

    standalone_hot = payload["standalone_hot"]
    if standalone_hot:
        lines.extend(
            [
                "## 热榜线索",
                "",
                "以下条目没有匹配到新闻RSS报道，仅用于观察公众注意力，不代表事件已经得到证实。",
                "",
                "| 来源 | 排名 | 热词 |",
                "|---|---:|---|",
            ]
        )
        for clue in standalone_hot:
            label = f"[{md_cell(clue['title'], 90)}]({clue['url']})" if clue["url"] else md_cell(clue["title"], 90)
            lines.append(f"| {clue['source']} | {clue['rank']} | {label} |")
        lines.append("")

    lines.extend(["## 来源状态", ""])
    for row in payload["source_status"]:
        mark = "正常" if row["ok"] else "失败"
        lines.append(f"- {row['name']}：{mark}，{row['items']} 条。{row['detail']}")
    lines.extend(
        [
            "",
            "## 阅读提示",
            "",
            payload["notice"],
            "",
        ]
    )
    return "\n".join(lines)


def display_time_iso(value: Optional[str]) -> str:
    if not value:
        return "时间未知"
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    except ValueError:
        return value


def esc(value: object) -> str:
    return html.escape(clean_text(value, 2000), quote=True)


def status_class(status: str) -> str:
    if "多方" in status:
        return "verified"
    if "热榜" in status:
        return "clue"
    return "single"


def render_html(payload: dict) -> str:
    meta = payload["meta"]
    events = payload["events"]
    category_labels = {
        "tech": "科技",
        "policy": "时政",
        "finance": "财经",
        "world": "国际",
        "international": "国际",
        "society": "社会",
        "culture": "文化",
    }
    lead_html = []
    for index, event in enumerate(events[:3], 1):
        sources = "".join(
            f'<a href="{esc(source["url"])}" target="_blank" rel="noopener">{esc(source["name"])}</a>'
            for source in event["sources"][:3]
            if source["url"]
        ) or "<span>热榜线索，暂无新闻RSS链接</span>"
        hot = event["hot_clues"][0]["title"] if event["hot_clues"] else ""
        lead_html.append(
            f"""
            <article class="event-card">
              <div class="event-top">
                <span class="status {status_class(event['status'])}">{esc(event['status'])}</span>
                <span class="score">优先级 {event['score']:.1f}</span>
                <span class="confidence">置信度 {event['confidence']}</span>
              </div>
              <div class="event-index">{index:02d}</div>
              <h2>{esc(event['title'])}</h2>
              <p class="summary">{esc(event['summary'])}</p>
              <div class="meta-row">
                <span>{display_time_iso(event['first_seen'])} 至 {display_time_iso(event['last_updated'])}</span>
                <span>{esc('、'.join(event['publishers']) or '无新闻RSS来源')}</span>
              </div>
              {f'<div class="hot-note">热榜线索：{esc(hot)}</div>' if hot else ''}
              <div class="sources">{sources}</div>
            </article>
            """
        )

    table_rows = "".join(
        f"""
        <tr>
          <td>{index}</td>
          <td><strong>{esc(event['title'])}</strong></td>
          <td><span class="status {status_class(event['status'])}">{esc(event['status'])}</span></td>
          <td>{esc('、'.join(event['publishers']) or '热榜')}</td>
          <td>{event['score']:.1f}</td>
          <td>{display_time_iso(event['last_updated'])}</td>
        </tr>
        """
        for index, event in enumerate(events, 1)
    )
    hot_rows = "".join(
        f"""
        <li>
          <span class="rank">{esc(clue['source'])} #{clue['rank']}</span>
          {f'<a href="{esc(clue["url"])}" target="_blank" rel="noopener">{esc(clue["title"])}</a>' if clue['url'] else esc(clue['title'])}
          <small>{esc(clue['summary'])}</small>
        </li>
        """
        for clue in payload["standalone_hot"]
    )
    source_rows = "".join(
        f"""<li><span class="{'ok' if row['ok'] else 'fail'}">{'正常' if row['ok'] else '失败'}</span>
        <strong>{esc(row['name'])}</strong><span>{row['items']} 条</span><small>{esc(row['detail'])}</small></li>"""
        for row in payload["source_status"]
    )
    topic = meta.get("topic") or (
        f"{category_labels[meta['category']]}要闻"
        if meta.get("category") in category_labels
        else "今日要闻"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(topic)} · 国内时事简报</title>
  <style>
    :root {{ --ink:#172033; --muted:#6e798d; --line:#e5eaf2; --bg:#f3f6fa; --red:#e55353; --green:#237a61; --blue:#31549b; --amber:#9f6b17; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--bg); font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; line-height:1.6; }}
    main {{ width:min(1120px,calc(100% - 32px)); margin:32px auto 64px; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; padding:28px 32px; color:white; border-radius:24px; background:linear-gradient(130deg,#15223e,#29456d); }}
    header h1 {{ margin:4px 0 8px; font-size:clamp(28px,4vw,48px); }}
    header p {{ margin:0; color:#c8d6e9; }}
    .eyebrow {{ color:#ffc1b7; font-size:13px; font-weight:700; letter-spacing:.08em; }}
    .summary-box {{ min-width:190px; text-align:right; color:#c8d6e9; font-size:13px; }}
    .summary-box strong {{ display:block; color:white; font-size:36px; }}
    .notice {{ margin:18px 0 0; padding:13px 16px; border:1px solid #f0dfb3; border-radius:13px; background:#fff9e8; color:#79571c; font-size:13px; }}
    .section-title {{ margin:34px 0 14px; display:flex; justify-content:space-between; align-items:baseline; }}
    .section-title h2 {{ margin:0; font-size:22px; }}
    .section-title span {{ color:var(--muted); font-size:12px; }}
    .lead-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }}
    .event-card {{ position:relative; padding:22px; border:1px solid var(--line); border-radius:20px; background:white; box-shadow:0 8px 24px rgba(23,49,93,.06); overflow:hidden; }}
    .event-top {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .status {{ display:inline-flex; align-items:center; padding:4px 9px; border-radius:999px; font-size:11px; font-weight:700; white-space:nowrap; }}
    .status.verified {{ background:#eaf7f1; color:var(--green); }}
    .status.single {{ background:#eef3ff; color:var(--blue); }}
    .status.clue {{ background:#fff3d8; color:var(--amber); }}
    .score,.confidence {{ color:var(--muted); font-size:11px; padding:4px 0; }}
    .event-index {{ margin-top:18px; color:#c7d2e2; font-size:12px; font-weight:700; }}
    .event-card h2 {{ margin:4px 0 12px; font-size:21px; line-height:1.45; }}
    .summary {{ min-height:5.2em; margin:0 0 16px; color:#526077; font-size:14px; }}
    .meta-row {{ display:flex; justify-content:space-between; gap:10px; padding-top:13px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }}
    .hot-note {{ margin-top:12px; padding:9px 11px; border-radius:10px; background:#fff3f0; color:#a34c43; font-size:12px; }}
    .sources {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:13px; }}
    .sources a,.sources span {{ color:var(--blue); font-size:12px; text-decoration:none; }}
    .table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:18px; background:white; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:13px 14px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ color:var(--muted); background:#f8fafd; font-size:11px; }}
    tr:last-child td {{ border-bottom:0; }}
    .hot-list,.source-list {{ margin:0; padding:0; list-style:none; border:1px solid var(--line); border-radius:18px; background:white; }}
    .hot-list li,.source-list li {{ padding:13px 16px; border-bottom:1px solid var(--line); }}
    .hot-list li:last-child,.source-list li:last-child {{ border-bottom:0; }}
    .hot-list a {{ color:var(--ink); font-weight:600; text-decoration:none; }}
    .hot-list small,.source-list small {{ display:block; color:var(--muted); }}
    .rank {{ margin-right:10px; color:var(--red); font-size:11px; }}
    .source-list li {{ display:grid; grid-template-columns:56px 1fr auto; gap:8px; align-items:center; }}
    .source-list small {{ grid-column:2 / -1; }}
    .ok {{ color:var(--green); font-weight:700; }}
    .fail {{ color:var(--red); font-weight:700; }}
    footer {{ margin-top:28px; color:var(--muted); font-size:11px; }}
    @media (max-width:860px) {{ .lead-grid {{ grid-template-columns:1fr; }} header {{ align-items:flex-start; flex-direction:column; }} .summary-box {{ text-align:left; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div>
      <div class="eyebrow">CN NEWS PULSE · 公开来源聚合</div>
      <h1>{esc(topic)}</h1>
      <p>最近 {meta['window_hours']} 小时 · 生成于 {meta['generated_at']}</p>
    </div>
    <div class="summary-box">
      <strong>{meta['event_count']}</strong>
      个候选事件 · {meta['news_items']} 条新闻 · {meta['hot_clues']} 条热榜线索
    </div>
  </header>
  <p class="notice">{esc(payload['notice'])}</p>
  <div class="section-title"><h2>今日主线</h2><span>按时效、来源和印证综合排序</span></div>
  <section class="lead-grid">{''.join(lead_html) or '<article class="event-card"><h2>暂无匹配事件</h2><p class="summary">请扩大时间窗口、更换关键词或检查来源状态。</p></article>'}</section>
  <div class="section-title"><h2>事件列表</h2><span>展示 {len(events)} / {meta['event_count']} 个事件</span></div>
  <div class="table-wrap"><table>
    <thead><tr><th>#</th><th>事件</th><th>状态</th><th>新闻来源</th><th>优先级</th><th>最近更新</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table></div>
  <div class="section-title"><h2>热榜线索</h2><span>仅代表公众注意力，不代表已核实</span></div>
  <ul class="hot-list">{hot_rows or '<li>没有未匹配的独立热榜线索。</li>'}</ul>
  <div class="section-title"><h2>来源状态</h2><span>单源失败不会清空整份简报</span></div>
  <ul class="source-list">{source_rows}</ul>
  <footer>cn-news-pulse · 公开新闻RSS与热榜线索聚合 · 事实以来源原文和后续通报为准</footer>
</main>
</body>
</html>
"""


def synthetic_news() -> list[NewsItem]:
    at = now_cn() - timedelta(hours=1)
    return [
        NewsItem("a", "A报", "A报", "综合", 0.9, "某地启动冬季交通保障措施", "https://example.com/a", "启动保障措施。", at),
        NewsItem("b", "B报", "B报", "综合", 0.8, "某地启动冬季交通保障措施", "https://example.com/b", "保障措施已启动。", at),
        NewsItem("c", "A报", "A报", "财经", 0.9, "另一条完全不同的财经消息", "https://example.com/c", "财经信息。", at),
    ]


def self_test() -> None:
    events, _ = build_events(synthetic_news(), [], "", 24, now_cn())
    assert len({event.title for event in events}) == 2, "duplicate titles should merge"
    merged = next(event for event in events if "交通保障" in event.title)
    assert merged.status == "多方报道", "two publishers should be independent corroboration"
    assert len(merged.items) == 2, "the two duplicate stories should share an event"

    payload = build_payload(
        events,
        [],
        [SourceStatus("test", "news", True, 3)],
        "",
        24,
        now_cn(),
        3,
        0,
        len(events),
        "all",
    )
    markdown = render_markdown(payload)
    assert "国内时事简报" in markdown and "来源状态" in markdown
    rendered_html = render_html(payload)
    assert "<!doctype html>" in rendered_html and "事件列表" in rendered_html

    rss = """<rss><channel><item><title>测试新闻</title><link>https://example.com/x</link>
    <description><![CDATA[<p>摘要</p>]]></description><pubDate>Wed, 25 Nov 2026 10:00:00 +0800</pubDate>
    </item></channel></rss>"""
    parsed = parse_rss(rss, DEFAULT_FEEDS[0], now_cn() - timedelta(days=1), 10)
    assert len(parsed) == 1 and parsed[0].summary == "摘要"
    print("self-test: ok")


def write_output(text: str, output: Optional[str]) -> None:
    if not output:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    sys.stderr.write(f"saved: {target}\n")


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.hours < 1 or args.hours > 24 * 31:
        raise SystemExit("--hours must be between 1 and 744")
    if args.limit < 1 or args.hot_limit < 1:
        raise SystemExit("--limit and --hot-limit must be positive")

    started = time.monotonic()
    generated_at = now_cn()
    cutoff = generated_at - timedelta(hours=args.hours)
    news_items, news_status = load_feeds(
        args.rss, args.timeout, cutoff, args.max_items_per_feed
    )
    if not args.no_site_news:
        site_items, site_status = load_site_news(
            args.timeout,
            cutoff,
            max_items_per_site=10,
        )
        news_items.extend(site_items)
        news_status.extend(site_status)
    if not args.no_commentary:
        commentary_items, commentary_status = load_commentary_sources(
            args.timeout,
            cutoff,
            max_items_per_source=8,
        )
        news_items.extend(commentary_items)
        news_status.extend(commentary_status)
    hot_clues: list[HotClue] = []
    hot_status: list[SourceStatus] = []
    if not args.no_hot:
        hot_clues, hot_status = load_hot_clues(
            args.timeout,
            include_baidu=not args.no_baidu,
            include_bilibili=not args.no_bilibili,
        )

    all_events, standalone_hot = build_events(
        news_items,
        hot_clues,
        args.topic,
        args.hours,
        generated_at,
        args.category,
    )
    event_count_total = len(all_events)
    events = all_events[: args.limit]
    standalone_hot = standalone_hot[: args.hot_limit]
    payload = build_payload(
        events,
        standalone_hot,
        news_status + hot_status,
        args.topic,
        args.hours,
        generated_at,
        len(news_items),
        len(hot_clues),
        event_count_total,
        args.category,
    )
    payload["meta"]["elapsed_seconds"] = round(time.monotonic() - started, 2)

    if args.emit == "json":
        output = json.dumps(payload, ensure_ascii=False, indent=2)
    elif args.emit == "html":
        output = render_html(payload)
    else:
        output = render_markdown(payload)
    write_output(output, args.output)

    failed = [row.name for row in news_status + hot_status if not row.ok]
    if failed:
        sys.stderr.write("degraded sources: " + ", ".join(failed) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
