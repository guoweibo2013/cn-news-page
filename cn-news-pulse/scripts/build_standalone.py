#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from three CN News Pulse views."""

from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import news_pulse as pulse  # noqa: E402


PRESETS = (
    {
        "id": "headlines",
        "label": "今日要闻",
        "description": "过去 24 小时国内新闻与公共关注线索",
        "hours": 24,
        "category": "all",
        "topic": "",
        "limit": 12,
    },
    {
        "id": "shenzhou",
        "label": "神舟二十四号",
        "description": "过去 72 小时任务进展与相关报道",
        "hours": 72,
        "category": "all",
        "topic": "神舟二十四号",
        "limit": 8,
    },
    {
        "id": "tech",
        "label": "6小时科技",
        "description": "最近 6 小时科技、产业与数字技术动态",
        "hours": 6,
        "category": "tech",
        "topic": "",
        "limit": 10,
    },
)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>国内时事简报 · CN News Pulse</title>
  <style>
    :root {
      --bg: #f2f5f9;
      --panel: #ffffff;
      --ink: #162039;
      --muted: #6b778b;
      --line: #e4e9f1;
      --red: #e55353;
      --red-soft: #fff0ed;
      --blue: #31549b;
      --blue-soft: #edf3ff;
      --green: #237a61;
      --green-soft: #eaf7f1;
      --amber: #9f6b17;
      --amber-soft: #fff5df;
      --navy: #17233d;
      --shadow: 0 10px 32px rgba(23, 49, 93, .07);
    }
    * { box-sizing: border-box; }
    html { background: var(--bg); }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 92% 2%, rgba(210, 223, 245, .75), transparent 24rem),
        radial-gradient(circle at 3% 12%, rgba(249, 225, 220, .55), transparent 22rem),
        var(--bg);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      line-height: 1.62;
    }
    button, input { font: inherit; }
    a { color: var(--blue); }
    .shell { width: min(1240px, calc(100% - 36px)); margin: 26px auto 60px; }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      padding: 17px 20px;
      border: 1px solid rgba(255, 255, 255, .82);
      border-radius: 22px;
      background: rgba(255, 255, 255, .92);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }
    .brand { display: flex; align-items: center; gap: 12px; min-width: 240px; }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 44px;
      height: 44px;
      flex: 0 0 44px;
      border-radius: 13px;
      background: var(--red);
      color: white;
      font-size: 21px;
      font-weight: 800;
    }
    .brand strong { display: block; font-size: 20px; line-height: 1.3; }
    .brand small { display: block; color: var(--muted); font-size: 11px; letter-spacing: .04em; }
    .tabs { display: flex; align-items: center; justify-content: center; gap: 7px; flex: 1; }
    .tab {
      border: 0;
      border-radius: 12px;
      padding: 10px 15px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
      transition: background .16s ease, color .16s ease, transform .16s ease;
    }
    .tab:hover { color: var(--ink); background: #f3f6fa; }
    .tab.active { color: var(--blue); background: var(--blue-soft); font-weight: 700; }
    .snapshot { color: var(--muted); text-align: right; font-size: 11px; white-space: nowrap; }
    .snapshot strong { display: block; color: var(--ink); font-size: 12px; }
    .hero {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(290px, .7fr);
      gap: 28px;
      margin-top: 18px;
      padding: 30px 32px;
      overflow: hidden;
      border-radius: 27px;
      color: white;
      background: linear-gradient(135deg, #14213b 0%, #1d3158 54%, #294777 100%);
      box-shadow: var(--shadow);
    }
    .hero::before, .hero::after {
      content: "";
      position: absolute;
      border-radius: 50%;
      pointer-events: none;
    }
    .hero::before { width: 260px; height: 260px; right: 18%; top: -150px; background: rgba(255,255,255,.08); }
    .hero::after { width: 320px; height: 320px; right: -130px; bottom: -230px; background: rgba(229,83,83,.18); }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(255,255,255,.1);
      color: #cbd8ea;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .08em;
    }
    .eyebrow i { width: 6px; height: 6px; border-radius: 50%; background: #ff9b8b; }
    .hero h1 { position: relative; margin: 15px 0 9px; font-size: clamp(30px, 4vw, 46px); line-height: 1.18; }
    .hero p { position: relative; margin: 0; max-width: 760px; color: #ccd9ea; font-size: 14px; }
    .hero-meta { display: flex; gap: 17px; flex-wrap: wrap; margin-top: 18px; color: #9fb2cc; font-size: 12px; }
    .stats { position: relative; display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; align-self: center; }
    .stat {
      min-width: 0;
      padding: 14px 10px;
      border: 1px solid rgba(255,255,255,.1);
      border-radius: 16px;
      background: rgba(255,255,255,.07);
      text-align: center;
    }
    .stat b { display: block; font-size: 30px; line-height: 1.25; }
    .stat span { color: #b5c5da; font-size: 10px; }
    .notice {
      margin: 16px 0 0;
      padding: 12px 15px;
      border: 1px solid #f0ddb0;
      border-radius: 14px;
      background: #fff9e8;
      color: #805c19;
      font-size: 12px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin: 20px 0 0;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,.8);
    }
    .search { position: relative; flex: 1; max-width: 510px; }
    .search input {
      width: 100%;
      padding: 10px 14px 10px 38px;
      border: 1px solid var(--line);
      border-radius: 11px;
      outline: 0;
      color: var(--ink);
      background: white;
    }
    .search input:focus { border-color: #91a9d4; box-shadow: 0 0 0 3px rgba(49,84,155,.08); }
    .search::before {
      content: "⌕";
      position: absolute;
      left: 13px;
      top: 6px;
      color: #8a96a8;
      font-size: 22px;
    }
    .legend { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 11px; }
    .legend span { display: inline-flex; align-items: center; gap: 5px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; }
    .section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; margin: 30px 0 13px; }
    .section-head h2 { margin: 0; font-size: 23px; }
    .section-head p { margin: 0; color: var(--muted); font-size: 12px; }
    .lead-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 15px; }
    .event {
      position: relative;
      display: flex;
      flex-direction: column;
      min-height: 310px;
      padding: 21px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .event::before { content: ""; position: absolute; left: 0; right: 0; top: 0; height: 3px; background: var(--line); }
    .event.verified::before { background: var(--green); }
    .event.single::before { background: #7898cc; }
    .event.clue::before { background: #dba644; }
    .event-top { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
    .pill { padding: 4px 9px; border-radius: 999px; font-size: 10px; font-weight: 700; white-space: nowrap; }
    .pill.verified { color: var(--green); background: var(--green-soft); }
    .pill.single { color: var(--blue); background: var(--blue-soft); }
    .pill.clue { color: var(--amber); background: var(--amber-soft); }
    .meter { margin-left: auto; color: var(--muted); font-size: 10px; }
    .event-index { margin-top: 14px; color: #c1ccdb; font-size: 11px; font-weight: 700; }
    .event h3 { margin: 2px 0 10px; font-size: 20px; line-height: 1.42; }
    .event p { display: -webkit-box; margin: 0 0 16px; overflow: hidden; color: #536078; font-size: 13px; -webkit-line-clamp: 5; -webkit-box-orient: vertical; }
    .event-meta { margin-top: auto; padding-top: 13px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; }
    .hot-note { margin-top: 10px; padding: 8px 10px; border-radius: 9px; background: var(--red-soft); color: #9f4a41; font-size: 11px; }
    .links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .links a { font-size: 11px; text-decoration: none; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; background: white; box-shadow: var(--shadow); }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { padding: 12px 13px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); background: #f8fafc; font-size: 10px; white-space: nowrap; }
    tr:last-child td { border-bottom: 0; }
    td:nth-child(1) { color: #9aa6b7; }
    td:nth-child(5) { font-weight: 700; color: var(--blue); }
    .split { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 16px; }
    .panel { border: 1px solid var(--line); border-radius: 19px; background: white; box-shadow: var(--shadow); }
    .panel h3 { margin: 0; padding: 17px 18px 11px; font-size: 17px; }
    .hot-list, .source-list { margin: 0; padding: 0 18px 14px; list-style: none; }
    .hot-list li, .source-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 3px 12px; padding: 11px 0; border-top: 1px solid var(--line); font-size: 12px; }
    .hot-list li:first-child, .source-list li:first-child { border-top: 0; }
    .hot-list a { color: var(--ink); font-weight: 600; text-decoration: none; }
    .hot-list small, .source-list small { grid-column: 1 / -1; color: var(--muted); }
    .rank { color: #a0aabc; font-size: 10px; }
    .source-list li { grid-template-columns: 48px 1fr auto; }
    .source-list strong { font-weight: 600; }
    .source-list small { grid-column: 2 / -1; }
    .ok { color: var(--green); font-weight: 700; }
    .fail { color: var(--red); font-weight: 700; }
    .empty { padding: 36px; border: 1px dashed #ccd6e5; border-radius: 18px; color: var(--muted); text-align: center; background: rgba(255,255,255,.55); }
    .foot { margin-top: 28px; color: var(--muted); font-size: 11px; text-align: center; }
    .toast {
      position: fixed;
      right: 22px;
      bottom: 22px;
      padding: 10px 14px;
      border-radius: 10px;
      background: var(--navy);
      color: white;
      font-size: 12px;
      opacity: 0;
      transform: translateY(8px);
      pointer-events: none;
      transition: .18s ease;
    }
    .toast.show { opacity: 1; transform: translateY(0); }
    @media (max-width: 980px) {
      .topbar { align-items: flex-start; flex-wrap: wrap; }
      .tabs { order: 3; flex-basis: 100%; justify-content: flex-start; overflow-x: auto; }
      .snapshot { margin-left: auto; }
      .hero { grid-template-columns: 1fr; }
      .lead-grid { grid-template-columns: 1fr 1fr; }
      .split { grid-template-columns: 1fr; }
    }
    @media (max-width: 680px) {
      .shell { width: min(100% - 20px, 1240px); margin-top: 10px; }
      .topbar { padding: 13px; border-radius: 17px; }
      .brand { min-width: 0; }
      .snapshot { display: none; }
      .tab { padding: 9px 12px; white-space: nowrap; }
      .hero { padding: 24px 20px; border-radius: 21px; }
      .stats { grid-template-columns: repeat(3, 1fr); }
      .stat b { font-size: 24px; }
      .toolbar { align-items: stretch; flex-direction: column; }
      .search { max-width: none; }
      .lead-grid { grid-template-columns: 1fr; }
      .event { min-height: 0; }
      .section-head { align-items: flex-start; flex-direction: column; gap: 2px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <div class="topbar">
      <div class="brand">
        <div class="brand-mark">时</div>
        <div>
          <strong>国内时事简报</strong>
          <small>CN NEWS PULSE · 独立页面</small>
        </div>
      </div>
      <nav class="tabs" id="tabs" aria-label="简报视图">__TABS__</nav>
      <div class="snapshot"><strong id="snapshotTime">__SNAPSHOT_TIME__</strong>单文件快照</div>
    </div>

    <section class="hero">
      <div>
        <span class="eyebrow"><i></i> PUBLIC NEWS AGGREGATE</span>
        <h1 id="heroTitle">__INITIAL_TITLE__</h1>
        <p id="heroDescription">__INITIAL_DESCRIPTION__</p>
        <div class="hero-meta">
          <span id="windowLabel">__WINDOW_LABEL__</span>
          <span id="generatedLabel">__GENERATED_LABEL__</span>
          <span>新闻 RSS 与热榜线索分层</span>
        </div>
      </div>
      <div class="stats">
        <div class="stat"><b id="eventStat">__EVENT_STAT__</b><span>候选事件</span></div>
        <div class="stat"><b id="newsStat">__NEWS_STAT__</b><span>新闻条目</span></div>
        <div class="stat"><b id="hotStat">__HOT_STAT__</b><span>热榜线索</span></div>
      </div>
    </section>

    <p class="notice" id="methodNotice">__NOTICE__</p>

    <section class="toolbar">
      <div class="search">
        <input id="searchInput" type="search" placeholder="在当前简报中搜索事件、来源或热词" autocomplete="off">
      </div>
      <div class="legend">
        <span><i class="dot" style="background:var(--green)"></i>多方报道</span>
        <span><i class="dot" style="background:#7898cc"></i>单源报道</span>
        <span><i class="dot" style="background:#dba644"></i>热榜线索</span>
      </div>
    </section>

    <div id="content">__INITIAL_CONTENT__</div>
    <p class="foot">公开新闻 RSS 与热榜线索聚合 · 评分表示检索优先级，不代表事实真实性概率 · 信息以原文及后续通报为准</p>
  </main>

  <div class="toast" id="toast">已切换视图</div>
  <script>
    const REPORTS = __REPORTS__;
    let active = 0;
    let query = "";

    const esc = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

    const statusClass = (status) => {
      if ((status || "").includes("多方")) return "verified";
      if ((status || "").includes("热榜")) return "clue";
      return "single";
    };

    const displayTime = (value) => {
      if (!value) return "时间未知";
      const part = value.slice(5, 16).replace("T", " ");
      return part || value;
    };

    const sourceLinks = (event) => {
      const seen = new Set();
      return (event.sources || [])
        .filter((source) => source.url && !seen.has(source.url) && seen.add(source.url))
        .slice(0, 4)
        .map((source) => `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.name)}</a>`)
        .join("");
    };

    const eventCard = (event, index) => {
      const klass = statusClass(event.status);
      const hot = event.hot_clues?.[0]?.title || "";
      const publishers = event.publishers?.length ? event.publishers.join("、") : "热榜线索";
      return `
        <article class="event ${klass}">
          <div class="event-top">
            <span class="pill ${klass}">${esc(event.status)}</span>
            <span class="meter">优先级 ${Number(event.score).toFixed(1)} · 置信度 ${event.confidence}</span>
          </div>
          <div class="event-index">${String(index + 1).padStart(2, "0")}</div>
          <h3>${esc(event.title)}</h3>
          <p>${esc(event.summary || "暂无摘要")}</p>
          ${hot ? `<div class="hot-note">热榜线索：${esc(hot)}</div>` : ""}
          <div class="event-meta">
            <div>${displayTime(event.first_seen)} 至 ${displayTime(event.last_updated)} · ${esc(publishers)}</div>
            <div class="links">${sourceLinks(event)}</div>
          </div>
        </article>`;
    };

    const eventRow = (event, index) => `
      <tr>
        <td>${index + 1}</td>
        <td><strong>${esc(event.title)}</strong></td>
        <td><span class="pill ${statusClass(event.status)}">${esc(event.status)}</span></td>
        <td>${esc(event.publishers?.join("、") || "热榜")}</td>
        <td>${Number(event.score).toFixed(1)}</td>
        <td>${displayTime(event.last_updated)}</td>
      </tr>`;

    const hotRows = (items) => items.length ? items.map((item) => `
      <li>
        <span><span class="rank">${esc(item.source)} #${item.rank}</span>
        ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>` : esc(item.title)}</span>
        <small>${esc(item.summary || "仅作为关注度线索，尚无匹配新闻 RSS 报道。")}</small>
      </li>`).join("") : `<li><span>当前视图没有独立热榜线索。</span></li>`;

    const sourceRows = (items) => items.map((source) => `
      <li>
        <span class="${source.ok ? "ok" : "fail"}">${source.ok ? "正常" : "失败"}</span>
        <strong>${esc(source.name)}</strong>
        <span>${source.items} 条</span>
        <small>${esc(source.detail || "")}</small>
      </li>`).join("");

    const matches = (event, needle) => {
      if (!needle) return true;
      const haystack = [
        event.title,
        event.summary,
        event.status,
        ...(event.publishers || []),
        ...(event.hot_clues || []).map((item) => item.title),
      ].join(" ").toLowerCase();
      return haystack.includes(needle);
    };

    const matchesHot = (item, needle) => {
      if (!needle) return true;
      return `${item.title} ${item.summary} ${item.source}`.toLowerCase().includes(needle);
    };

    const render = () => {
      const report = REPORTS[active];
      const payload = report.payload;
      const meta = payload.meta;
      const needle = query.trim().toLowerCase();
      const events = payload.events.filter((event) => matches(event, needle));
      const hot = payload.standalone_hot.filter((item) => matchesHot(item, needle));

      document.querySelectorAll(".tab").forEach((tab, index) => {
        tab.classList.toggle("active", index === active);
        tab.setAttribute("aria-selected", String(index === active));
      });
      document.getElementById("heroTitle").textContent = report.label;
      document.getElementById("heroDescription").textContent = report.description;
      document.getElementById("windowLabel").textContent = `最近 ${meta.window_hours} 小时`;
      document.getElementById("generatedLabel").textContent = `生成于 ${displayTime(meta.generated_at)}`;
      document.getElementById("snapshotTime").textContent = displayTime(meta.generated_at);
      document.getElementById("eventStat").textContent = meta.event_count;
      document.getElementById("newsStat").textContent = meta.news_items;
      document.getElementById("hotStat").textContent = meta.hot_clues;
      document.getElementById("methodNotice").textContent = payload.notice;

      const lead = events.slice(0, 3);
      const leadHtml = lead.length
        ? lead.map(eventCard).join("")
        : `<div class="empty">没有符合当前搜索条件的事件。</div>`;
      const tableHtml = events.length
        ? `<div class="table-wrap"><table>
            <thead><tr><th>#</th><th>事件</th><th>状态</th><th>新闻来源</th><th>优先级</th><th>最近更新</th></tr></thead>
            <tbody>${events.map(eventRow).join("")}</tbody>
          </table></div>`
        : `<div class="empty">没有符合当前搜索条件的事件。</div>`;

      document.getElementById("content").innerHTML = `
        <div class="section-head">
          <h2>${needle ? "搜索结果" : "当前主线"}</h2>
          <p>${needle ? `匹配 ${events.length} 个事件` : "按时效、来源、独立印证和关注度综合排序"}</p>
        </div>
        <section class="lead-grid">${leadHtml}</section>
        <div class="section-head">
          <h2>事件列表</h2>
          <p>当前展示 ${events.length} / ${meta.events_shown} 个事件</p>
        </div>
        ${tableHtml}
        <div class="section-head">
          <h2>热榜线索</h2>
          <p>只代表公众注意力，不代表事件已核实</p>
        </div>
        <section class="split">
          <div class="panel"><h3>关注词</h3><ul class="hot-list">${hotRows(hot)}</ul></div>
          <div class="panel"><h3>来源状态</h3><ul class="source-list">${sourceRows(payload.source_status)}</ul></div>
        </section>`;
    };

    const tabs = document.getElementById("tabs");
    tabs.innerHTML = "";
    REPORTS.forEach((report, index) => {
      const button = document.createElement("button");
      button.className = "tab";
      button.type = "button";
      button.textContent = report.label;
      button.setAttribute("role", "tab");
      button.addEventListener("click", () => {
        active = index;
        query = "";
        document.getElementById("searchInput").value = "";
        render();
        toast(`${report.label} 已加载`);
      });
      tabs.appendChild(button);
    });

    document.getElementById("searchInput").addEventListener("input", (event) => {
      query = event.target.value;
      render();
    });

    let toastTimer;
    const toast = (message) => {
      const node = document.getElementById("toast");
      node.textContent = message;
      node.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => node.classList.remove("show"), 1300);
    };

    render();
  </script>
</body>
</html>
"""


def filtered_statuses(
    statuses: list[pulse.SourceStatus],
    items: list[pulse.NewsItem],
    cutoff: datetime,
) -> list[pulse.SourceStatus]:
    counts: dict[str, int] = {}
    for item in items:
        if item.published_at is None or item.published_at >= cutoff:
            counts[item.source] = counts.get(item.source, 0) + 1
    return [replace(row, items=counts.get(row.name, 0)) for row in statuses]


def build_report(
    preset: dict,
    news_items: list[pulse.NewsItem],
    hot_clues: list[pulse.HotClue],
    news_status: list[pulse.SourceStatus],
    hot_status: list[pulse.SourceStatus],
    generated_at: datetime,
) -> dict:
    cutoff = generated_at - timedelta(hours=preset["hours"])
    visible_news = [
        item
        for item in news_items
        if item.published_at is None or item.published_at >= cutoff
    ]
    all_events, standalone_hot = pulse.build_events(
        visible_news,
        hot_clues,
        preset["topic"],
        preset["hours"],
        generated_at,
        category=preset["category"],
    )
    total_events = len(all_events)
    events = all_events[: preset["limit"]]
    payload = pulse.build_payload(
        events,
        standalone_hot[:12],
        filtered_statuses(news_status, visible_news, cutoff) + hot_status,
        preset["topic"],
        preset["hours"],
        generated_at,
        len(visible_news),
        len(hot_clues),
        total_events,
        preset["category"],
    )
    return {
        "id": preset["id"],
        "label": preset["label"],
        "description": preset["description"],
        "payload": payload,
    }


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def display_time(value: Optional[str]) -> str:
    if not value:
        return "时间未知"
    return value[5:16].replace("T", " ") or value


def status_class(status: str) -> str:
    if "多方" in status:
        return "verified"
    if "热榜" in status:
        return "clue"
    return "single"


def render_source_links(event: dict) -> str:
    seen: set[str] = set()
    links = []
    for source in event.get("sources", []):
        url = source.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        links.append(
            f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(source.get("name"))}</a>'
        )
        if len(links) == 4:
            break
    return "".join(links)


def render_event_card(event: dict, index: int) -> str:
    klass = status_class(event.get("status", ""))
    publishers = "、".join(event.get("publishers") or []) or "热榜线索"
    hot_clues = event.get("hot_clues") or []
    hot = f'<div class="hot-note">热榜线索：{esc(hot_clues[0].get("title"))}</div>' if hot_clues else ""
    return f"""
      <article class="event {klass}">
        <div class="event-top">
          <span class="pill {klass}">{esc(event.get("status"))}</span>
          <span class="meter">优先级 {float(event.get("score") or 0):.1f} · 置信度 {int(event.get("confidence") or 0)}</span>
        </div>
        <div class="event-index">{index + 1:02d}</div>
        <h3>{esc(event.get("title"))}</h3>
        <p>{esc(event.get("summary") or "暂无摘要")}</p>
        {hot}
        <div class="event-meta">
          <div>{display_time(event.get("first_seen"))} 至 {display_time(event.get("last_updated"))} · {esc(publishers)}</div>
          <div class="links">{render_source_links(event)}</div>
        </div>
      </article>"""


def render_event_row(event: dict, index: int) -> str:
    klass = status_class(event.get("status", ""))
    return f"""
      <tr>
        <td>{index + 1}</td>
        <td><strong>{esc(event.get("title"))}</strong></td>
        <td><span class="pill {klass}">{esc(event.get("status"))}</span></td>
        <td>{esc("、".join(event.get("publishers") or []) or "热榜")}</td>
        <td>{float(event.get("score") or 0):.1f}</td>
        <td>{display_time(event.get("last_updated"))}</td>
      </tr>"""


def render_initial_content(report: dict) -> str:
    payload = report["payload"]
    events = payload["events"]
    lead = "".join(
        render_event_card(event, index) for index, event in enumerate(events[:3])
    )
    if not lead:
        lead = '<div class="empty">没有符合当前条件的事件。</div>'
    rows = "".join(
        render_event_row(event, index) for index, event in enumerate(events)
    )
    table = (
        f"""<div class="table-wrap"><table>
          <thead><tr><th>#</th><th>事件</th><th>状态</th><th>新闻来源</th><th>优先级</th><th>最近更新</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>"""
        if rows
        else '<div class="empty">没有符合当前条件的事件。</div>'
    )
    hot_rows = "".join(
        f"""<li>
          <span><span class="rank">{esc(item.get("source"))} #{item.get("rank")}</span>
          {f'<a href="{esc(item.get("url"))}" target="_blank" rel="noopener">{esc(item.get("title"))}</a>' if item.get("url") else esc(item.get("title"))}</span>
          <small>{esc(item.get("summary") or "仅作为关注度线索，尚无匹配新闻 RSS 报道。")}</small>
        </li>"""
        for item in payload["standalone_hot"]
    ) or "<li><span>当前视图没有独立热榜线索。</span></li>"
    source_rows = "".join(
        f"""<li>
          <span class="{"ok" if item.get("ok") else "fail"}">{"正常" if item.get("ok") else "失败"}</span>
          <strong>{esc(item.get("name"))}</strong>
          <span>{int(item.get("items") or 0)} 条</span>
          <small>{esc(item.get("detail"))}</small>
        </li>"""
        for item in payload["source_status"]
    )
    meta = payload["meta"]
    return f"""
      <div class="section-head">
        <h2>当前主线</h2>
        <p>按时效、来源、独立印证和关注度综合排序</p>
      </div>
      <section class="lead-grid">{lead}</section>
      <div class="section-head">
        <h2>事件列表</h2>
        <p>当前展示 {len(events)} / {meta["event_count"]} 个事件</p>
      </div>
      {table}
      <div class="section-head">
        <h2>热榜线索</h2>
        <p>只代表公众注意力，不代表事件已核实</p>
      </div>
      <section class="split">
        <div class="panel"><h3>关注词</h3><ul class="hot-list">{hot_rows}</ul></div>
        <div class="panel"><h3>来源状态</h3><ul class="source-list">{source_rows}</ul></div>
      </section>"""


def render_tabs(reports: list[dict]) -> str:
    return "".join(
        f"""<button class="tab{" active" if index == 0 else ""}" type="button" role="tab" aria-selected="{"true" if index == 0 else "false"}">{esc(report["label"])}</button>"""
        for index, report in enumerate(reports)
    )


def build_page(reports: list[dict], generated_at: datetime) -> str:
    data = json.dumps(reports, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")
    first = reports[0]
    meta = first["payload"]["meta"]
    output = HTML_TEMPLATE
    replacements = {
        "__TABS__": render_tabs(reports),
        "__SNAPSHOT_TIME__": display_time(meta["generated_at"]),
        "__INITIAL_TITLE__": esc(first["label"]),
        "__INITIAL_DESCRIPTION__": esc(first["description"]),
        "__WINDOW_LABEL__": f'最近 {int(meta["window_hours"])} 小时',
        "__GENERATED_LABEL__": f'生成于 {display_time(meta["generated_at"])}',
        "__EVENT_STAT__": str(int(meta["event_count"])),
        "__NEWS_STAT__": str(int(meta["news_items"])),
        "__HOT_STAT__": str(int(meta["hot_clues"])),
        "__NOTICE__": esc(first["payload"]["notice"]),
        "__INITIAL_CONTENT__": render_initial_content(first),
    }
    for token, value in replacements.items():
        output = output.replace(token, value)
    return output.replace("__REPORTS__", data)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可离线打开的三视图国内时事页面。")
    parser.add_argument("--output", default="cn-news-dashboard.html", help="HTML输出路径")
    parser.add_argument("--timeout", type=int, default=pulse.DEFAULT_TIMEOUT, help="单请求超时秒数")
    args = parser.parse_args()

    generated_at = pulse.now_cn()
    max_hours = max(preset["hours"] for preset in PRESETS)
    cutoff = generated_at - timedelta(hours=max_hours)
    news_items, news_status = pulse.load_feeds([], args.timeout, cutoff, 200)
    hot_clues, hot_status = pulse.load_hot_clues(args.timeout, True, True)
    reports = [
        build_report(
            preset,
            news_items,
            hot_clues,
            news_status,
            hot_status,
            generated_at,
        )
        for preset in PRESETS
    ]
    output = build_page(reports, generated_at)
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")
    failed = [row.name for row in news_status + hot_status if not row.ok]
    if failed:
        sys.stderr.write("degraded sources: " + ", ".join(failed) + "\n")
    sys.stderr.write(f"saved: {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
