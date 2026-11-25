#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from three CN News Pulse views."""

from __future__ import annotations

import argparse
import html
import json
import struct
import sys
import zlib
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
  <meta name="theme-color" content="#17233d">
  <link rel="manifest" href="./manifest.webmanifest">
  <link rel="icon" href="./icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="./icon-192.png">
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
      font-size: 17px;
      line-height: 1.68;
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
    .brand small { display: block; color: var(--muted); font-size: 13px; letter-spacing: .04em; }
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
    .snapshot { color: var(--muted); text-align: right; font-size: 13px; white-space: nowrap; }
    .snapshot strong { display: block; color: var(--ink); font-size: 14px; }
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
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
    }
    .eyebrow i { width: 6px; height: 6px; border-radius: 50%; background: #ff9b8b; }
    .hero h1 { position: relative; margin: 15px 0 9px; font-size: clamp(30px, 4vw, 46px); line-height: 1.18; }
    .hero p { position: relative; margin: 0; max-width: 760px; color: #ccd9ea; font-size: 16px; }
    .hero-meta { display: flex; gap: 17px; flex-wrap: wrap; margin-top: 18px; color: #9fb2cc; font-size: 14px; }
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
    .stat span { color: #b5c5da; font-size: 12px; }
    .notice {
      margin: 16px 0 0;
      padding: 12px 15px;
      border: 1px solid #f0ddb0;
      border-radius: 14px;
      background: #fff9e8;
      color: #805c19;
      font-size: 14px;
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
    .legend { display: flex; gap: 14px; flex-wrap: wrap; color: var(--muted); font-size: 13px; }
    .legend span { display: inline-flex; align-items: center; gap: 5px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; }
    .section-head { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; margin: 30px 0 13px; }
    .section-head h2 { margin: 0; font-size: 23px; }
    .section-head p { margin: 0; color: var(--muted); font-size: 14px; }
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
    .pill { padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }
    .pill.verified { color: var(--green); background: var(--green-soft); }
    .pill.single { color: var(--blue); background: var(--blue-soft); }
    .pill.clue { color: var(--amber); background: var(--amber-soft); }
    .meter { margin-left: auto; color: var(--muted); font-size: 12px; }
    .event-index { margin-top: 14px; color: #c1ccdb; font-size: 13px; font-weight: 700; }
    .event h3 { margin: 2px 0 10px; font-size: 22px; line-height: 1.42; }
    .event p { display: -webkit-box; margin: 0 0 16px; overflow: hidden; color: #536078; font-size: 15px; line-height: 1.72; -webkit-line-clamp: 6; -webkit-box-orient: vertical; }
    .event-meta { margin-top: auto; padding-top: 13px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
    .hot-note { margin-top: 10px; padding: 9px 11px; border-radius: 9px; background: var(--red-soft); color: #9f4a41; font-size: 13px; }
    .links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
    .links a { font-size: 13px; text-decoration: none; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 18px; background: white; box-shadow: var(--shadow); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { padding: 12px 13px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); background: #f8fafc; font-size: 12px; white-space: nowrap; }
    tr:last-child td { border-bottom: 0; }
    td:nth-child(1) { color: #9aa6b7; }
    td:nth-child(5) { font-weight: 700; color: var(--blue); }
    .split { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 16px; }
    .panel { border: 1px solid var(--line); border-radius: 19px; background: white; box-shadow: var(--shadow); }
    .panel h3 { margin: 0; padding: 17px 18px 11px; font-size: 17px; }
    .hot-list, .source-list { margin: 0; padding: 0 18px 14px; list-style: none; }
    .hot-list li, .source-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; padding: 12px 0; border-top: 1px solid var(--line); font-size: 14px; }
    .hot-list li:first-child, .source-list li:first-child { border-top: 0; }
    .hot-list a { color: var(--ink); font-weight: 600; text-decoration: none; }
    .hot-list small, .source-list small { grid-column: 1 / -1; color: var(--muted); }
    .rank { color: #a0aabc; font-size: 12px; }
    .source-list li { grid-template-columns: 48px 1fr auto; }
    .source-list strong { font-weight: 600; }
    .source-list small { grid-column: 2 / -1; }
    .ok { color: var(--green); font-weight: 700; }
    .fail { color: var(--red); font-weight: 700; }
    .empty { padding: 36px; border: 1px dashed #ccd6e5; border-radius: 18px; color: var(--muted); text-align: center; background: rgba(255,255,255,.55); }
    .foot { margin-top: 28px; color: var(--muted); font-size: 12px; text-align: center; }
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
    .change {
      display: inline-flex;
      align-items: center;
      padding: 3px 7px;
      border-radius: 999px;
      background: #f0f3f8;
      color: #6b778b;
      font-size: 12px;
      font-weight: 700;
    }
    .change.new { background: #fff0ed; color: #c64e45; }
    .change.updated { background: #fff5df; color: #966412; }
    .open-event {
      margin: 10px 0 0;
      padding: 0;
      border: 0;
      color: var(--blue);
      background: transparent;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .open-event:hover { text-decoration: underline; }
    button.event-title {
      padding: 0;
      border: 0;
      color: var(--ink);
      background: transparent;
      text-align: left;
      font-weight: 700;
      cursor: pointer;
    }
    button.event-title:hover { color: var(--blue); }
    .row-summary { display: none; }
    .row-badges { display: inline-flex; gap: 6px; flex-wrap: wrap; margin-left: 7px; }
    .watchbar {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 12px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,.8);
    }
    .watchbar strong { font-size: 14px; white-space: nowrap; }
    .watchbar input { font-size: 15px; }
    .watchbar input {
      min-width: 150px;
      flex: 0 1 260px;
      padding: 8px 11px;
      border: 1px solid var(--line);
      border-radius: 9px;
      outline: none;
    }
    .watchbar button {
      padding: 8px 12px;
      border: 0;
      border-radius: 9px;
      color: white;
      background: var(--blue);
      cursor: pointer;
    }
    .chips { display: flex; flex-wrap: wrap; gap: 7px; flex: 1; }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 9px;
      border-radius: 999px;
      background: var(--blue-soft);
      color: var(--blue);
      font-size: 12px;
      font-weight: 700;
    }
    .chip button { padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; }
    .refresh-state { color: #9fb2cc; font-size: 12px; }
    .health-strip { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 8px; }
    .health-dot { width: 9px; height: 9px; border-radius: 50%; background: #cfd8e5; }
    .health-dot.ok { background: var(--green); }
    .health-dot.fail { background: var(--red); }
    dialog {
      width: min(760px, calc(100% - 24px));
      max-height: min(86vh, 900px);
      padding: 0;
      border: 0;
      border-radius: 24px;
      color: var(--ink);
      background: white;
      box-shadow: 0 30px 80px rgba(17, 35, 61, .28);
    }
    dialog::backdrop { background: rgba(17, 28, 48, .52); backdrop-filter: blur(4px); }
    .dialog-head {
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      backdrop-filter: blur(12px);
    }
    .dialog-head h2 { margin: 0; font-size: 24px; }
    .dialog-actions { display: flex; gap: 8px; }
    .dialog-actions button {
      padding: 7px 11px;
      border: 1px solid var(--line);
      border-radius: 9px;
      color: var(--ink);
      background: white;
      cursor: pointer;
    }
    .dialog-body { padding: 22px; }
    .reason-list { display: flex; flex-wrap: wrap; gap: 7px; margin: 12px 0 18px; }
    .reason {
      padding: 6px 10px;
      border-radius: 9px;
      background: #f3f6fa;
      color: #536078;
      font-size: 13px;
    }
    .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .detail-box { padding: 15px; border: 1px solid var(--line); border-radius: 14px; background: #f9fbfd; }
    .detail-box h3 { margin: 0 0 9px; padding: 0; font-size: 16px; }
    .detail-box p { margin: 0; color: #536078; font-size: 14px; }
    .timeline { margin: 16px 0 0; padding: 0; list-style: none; }
    .timeline li { position: relative; padding: 0 0 18px 22px; border-left: 2px solid #dfe6f0; }
    .timeline li:last-child { border-left-color: transparent; padding-bottom: 0; }
    .timeline li::before {
      content: "";
      position: absolute;
      left: -6px;
      top: 3px;
      width: 10px;
      height: 10px;
      border: 2px solid white;
      border-radius: 50%;
      background: var(--blue);
    }
    .timeline li.official::before { background: var(--green); }
    .timeline time { display: block; color: var(--muted); font-size: 12px; }
    .timeline a { display: block; color: var(--ink); font-size: 14px; font-weight: 600; text-decoration: none; }
    .read-badge { color: var(--muted); font-size: 12px; }
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
      .snapshot {
        display: block;
        width: 100%;
        margin-left: 0;
        padding-top: 8px;
        border-top: 1px solid var(--line);
        text-align: left;
      }
      .tab { padding: 9px 12px; white-space: nowrap; }
      .hero { padding: 24px 20px; border-radius: 21px; }
      .stats { grid-template-columns: repeat(3, 1fr); }
      .stat b { font-size: 26px; }
      .toolbar { align-items: stretch; flex-direction: column; }
      .search { max-width: none; }
      .lead-grid { grid-template-columns: 1fr; }
      .event { min-height: 0; }
      .section-head { align-items: flex-start; flex-direction: column; gap: 2px; }
      .watchbar { align-items: flex-start; flex-wrap: wrap; }
      .watchbar input { flex: 1 1 100%; }
      .detail-grid { grid-template-columns: 1fr; }
      .table-wrap {
        overflow: visible;
        border: 0;
        background: transparent;
        box-shadow: none;
      }
      .table-wrap table,
      .table-wrap tbody {
        display: block;
      }
      .table-wrap thead {
        display: none;
      }
      .table-wrap tbody {
        display: grid;
        gap: 12px;
      }
      .table-wrap tr {
        display: block;
        padding: 18px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: white;
        box-shadow: var(--shadow);
      }
      .table-wrap td {
        display: none;
        padding: 0;
        border: 0;
      }
      .table-wrap td:nth-child(2) {
        display: block;
      }
      .table-wrap .event-title {
        display: block;
        width: 100%;
        font-size: 18px;
        line-height: 1.52;
      }
      .table-wrap .row-badges {
        display: none;
      }
      .table-wrap .row-summary {
        display: -webkit-box;
        margin-top: 9px;
        overflow: hidden;
        color: #536078;
        font-size: 15px;
        font-weight: 400;
        line-height: 1.68;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
      }
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
      <div class="snapshot">
        <strong id="snapshotTime">__SNAPSHOT_TIME__</strong>
        单文件快照
        <span class="refresh-state" id="refreshState">15 分钟后检查更新</span>
      </div>
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
    <section class="watchbar">
      <strong>我的关注</strong>
      <input id="watchInput" type="text" placeholder="输入关键词，例如：航天、人工智能、天气" autocomplete="off">
      <button id="watchAdd" type="button">添加关注</button>
      <div class="chips" id="watchChips"></div>
    </section>

    <div id="content">__INITIAL_CONTENT__</div>
    <p class="foot">
      公开新闻 RSS 与热榜线索聚合 · 评分表示检索优先级，不代表事实真实性概率 · 信息以原文及后续通报为准
      <br><a href="./digest.xml">订阅每日摘要</a> · <a href="./digest.md">Markdown 日报</a>
    </p>
  </main>

  <dialog id="eventDialog">
    <div class="dialog-head">
      <h2 id="dialogTitle">事件详情</h2>
      <div class="dialog-actions">
        <button id="shareEvent" type="button">复制链接</button>
        <button id="closeDialog" type="button">关闭</button>
      </div>
    </div>
    <div class="dialog-body" id="dialogBody"></div>
  </dialog>

  <div class="toast" id="toast">已切换视图</div>
  <script>
    const REPORTS = __REPORTS__;
    const WATCH_KEY = "cn-news-watchlist-v1";
    const READ_KEY = "cn-news-read-v1";
    const NOTIFY_KEY = "cn-news-notified-v1";
    const AUTO_REFRESH_MS = 15 * 60 * 1000;
    const params = new URLSearchParams(location.search);
    const requestedView = params.get("view");
    const requestedEvent = params.get("event");
    let active = Math.max(0, REPORTS.findIndex((report) => report.id === requestedView));
    let query = "";
    let currentEvents = [];
    let sharedEvent = null;
    let watchlist = readStore(WATCH_KEY, []);
    let readIds = new Set(readStore(READ_KEY, []));
    let notifiedIds = new Set(readStore(NOTIFY_KEY, []));

    function readStore(key, fallback) {
      try {
        const value = JSON.parse(localStorage.getItem(key) || "null");
        return value ?? fallback;
      } catch (_) {
        return fallback;
      }
    }

    function writeStore(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
    }

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

    const changeLabel = (change) => {
      if (change === "new") return "新事件";
      if (change === "updated") return "刚刚更新";
      return "";
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
      const change = changeLabel(event.change);
      const official = event.official_publishers?.length ? `<span class="change">官方来源</span>` : "";
      return `
        <article class="event ${klass}">
          <div class="event-top">
            <span class="pill ${klass}">${esc(event.status)}</span>
            ${change ? `<span class="change ${event.change}">${change}</span>` : ""}
            ${official}
            <span class="meter">优先级 ${Number(event.score).toFixed(1)} · 置信度 ${event.confidence}</span>
          </div>
          <div class="event-index">${String(index + 1).padStart(2, "0")} · ${readIds.has(event.event_id) ? '<span class="read-badge">已读</span>' : ""}</div>
          <h3>${esc(event.title)}</h3>
          <p>${esc(event.summary || "暂无摘要")}</p>
          ${event.why_important?.[0] ? `<div class="hot-note">为什么重要：${esc(event.why_important[0])}</div>` : ""}
          ${hot ? `<div class="hot-note">热榜线索：${esc(hot)}</div>` : ""}
          <button class="open-event" type="button" data-event-id="${esc(event.event_id)}">查看时间线与来源对比 →</button>
          <div class="event-meta">
            <div>${displayTime(event.first_seen)} 至 ${displayTime(event.last_updated)} · ${esc(publishers)}</div>
            <div class="links">${sourceLinks(event)}</div>
          </div>
        </article>`;
    };

    const eventRow = (event, index) => `
      <tr>
        <td>${index + 1}</td>
        <td>
          <button class="event-title" type="button" data-event-id="${esc(event.event_id)}">${esc(event.title)}</button>
          <span class="row-badges">
            ${event.change === "new" ? '<span class="change new">新事件</span>' : event.change === "updated" ? '<span class="change updated">更新</span>' : ""}
            ${readIds.has(event.event_id) ? '<span class="read-badge">已读</span>' : ""}
          </span>
          <span class="row-summary">${esc(event.summary || "")}</span>
        </td>
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

    const sourceHistory = (source, history) => {
      const dots = history.slice(-12).map((run) => {
        const row = (run.sources || []).find((item) => item.name === source.name);
        const state = !row ? "" : row.ok ? "ok" : "fail";
        return `<i class="health-dot ${state}" title="${esc(run.generated_at || "")}"></i>`;
      }).join("");
      return dots ? `<div class="health-strip">${dots}</div>` : "";
    };

    const sourceRows = (items, history = []) => items.map((source) => `
      <li>
        <span class="${source.ok ? "ok" : "fail"}">${source.ok ? "正常" : "失败"}</span>
        <strong>${esc(source.name)}</strong>
        <span>${source.items} 条</span>
        <small>${esc(source.detail || "")}</small>
        ${sourceHistory(source, history)}
      </li>`).join("");

    const matches = (event, needle) => {
      if (!needle) return true;
      const haystack = [
        event.title,
        event.summary,
        event.status,
        ...(event.publishers || []),
        ...(event.hot_clues || []).map((item) => item.title),
        ...(event.why_important || []),
      ].join(" ").toLowerCase();
      return haystack.includes(needle);
    };

    const matchesHot = (item, needle) => {
      if (!needle) return true;
      return `${item.title} ${item.summary} ${item.source}`.toLowerCase().includes(needle);
    };

    const watchMatches = (events) => {
      if (!watchlist.length) return [];
      return events.filter((event) => watchlist.some((word) =>
        `${event.title} ${event.summary}`.toLowerCase().includes(word.toLowerCase())
      ));
    };

    const maybeNotify = (events) => {
      if (!("Notification" in window) || Notification.permission !== "granted") return;
      const fresh = events
        .filter((event) => ["new", "updated"].includes(event.change) && !notifiedIds.has(event.event_id))
        .slice(0, 3);
      fresh.forEach((event) => {
        try {
          new Notification("关注事件更新", {
            body: event.title,
            icon: "./icon-192.png",
            tag: event.event_id,
          });
          notifiedIds.add(event.event_id);
        } catch (_) {}
      });
      if (fresh.length) writeStore(NOTIFY_KEY, [...notifiedIds].slice(-500));
    };

    function renderWatch() {
      const chips = document.getElementById("watchChips");
      chips.innerHTML = watchlist.map((word, index) => `
        <span class="chip">${esc(word)}<button type="button" data-watch-remove="${index}" aria-label="移除${esc(word)}">×</button></span>
      `).join("");
      chips.querySelectorAll("[data-watch-remove]").forEach((button) => {
        button.addEventListener("click", () => {
          watchlist.splice(Number(button.dataset.watchRemove), 1);
          writeStore(WATCH_KEY, watchlist);
          renderWatch();
          render();
        });
      });
    }

    const openEvent = (event) => {
      if (!event) return;
      sharedEvent = event;
      readIds.add(event.event_id);
      writeStore(READ_KEY, [...readIds]);
      document.getElementById("dialogTitle").textContent = event.title;
      const klass = statusClass(event.status);
      const reasons = (event.why_important || []).map((reason) => `<span class="reason">${esc(reason)}</span>`).join("");
      const timeline = (event.timeline || []).map((item) => `
        <li class="${item.tier}">
          <time>${displayTime(item.time)} · ${esc(item.publisher || item.source)}</time>
          ${item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>` : `<span>${esc(item.title)}</span>`}
        </li>`).join("");
      const hot = (event.hot_clues || []).map((item) =>
        `${esc(item.source)} #${item.rank} ${esc(item.title)}`
      ).join("<br>") || "暂无匹配热榜线索";
      const previous = event.previous ? `
        <div class="detail-box" style="margin-top:16px">
          <h3>上次记录</h3>
          <p>最近更新：${displayTime(event.previous.last_updated)}<br>当时状态：${esc(event.previous.status || "未知")}<br>当时优先级：${Number(event.previous.score || 0).toFixed(1)}</p>
        </div>` : "";
      document.getElementById("dialogBody").innerHTML = `
        <div class="event-top">
          <span class="pill ${klass}">${esc(event.status)}</span>
          <span class="meter">优先级 ${Number(event.score).toFixed(1)} · 置信度 ${event.confidence}</span>
        </div>
        <p>${esc(event.summary || "暂无摘要")}</p>
        <div class="reason-list">${reasons}</div>
        <div class="detail-grid">
          <div class="detail-box">
            <h3>发生了什么</h3>
            <p>首次出现：${displayTime(event.first_seen)}<br>最近更新：${displayTime(event.last_updated)}<br>新闻来源：${esc(event.publishers?.join("、") || "暂无")} </p>
          </div>
          <div class="detail-box">
            <h3>核实状态</h3>
            <p>${esc(event.status)}，共 ${event.publishers?.length || 0} 个新闻出版方。<br>官方直源：${esc(event.official_publishers?.join("、") || "暂无")} </p>
          </div>
        </div>
        <div class="section-head"><h2 style="font-size:16px">事件时间线</h2><p>同一事件按来源发布时间排列</p></div>
        <ul class="timeline">${timeline || "<li>暂无详细时间线。</li>"}</ul>
        <div class="detail-box" style="margin-top:16px"><h3>热榜线索</h3><p>${hot}</p></div>
        ${previous}`;
      document.getElementById("eventDialog").showModal();
      history.replaceState(null, "", `?view=${REPORTS[active].id}&event=${encodeURIComponent(event.event_id)}`);
      render();
    };

    const render = () => {
      const report = REPORTS[active];
      const payload = report.payload;
      const meta = payload.meta;
      const needle = query.trim().toLowerCase();
      currentEvents = payload.events;
      const events = payload.events.filter((event) => matches(event, needle));
      const hot = payload.standalone_hot.filter((item) => matchesHot(item, needle));
      const watched = watchMatches(events);
      const healthHistory = meta.health_history || [];

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
      const watchHtml = watchlist.length ? `
        <div class="section-head">
          <h2>我的关注</h2>
          <p>${watched.length ? `找到 ${watched.length} 个相关事件` : "当前视图暂无匹配"}</p>
        </div>
        ${watched.length ? `<div class="table-wrap"><table><tbody>${watched.slice(0, 8).map(eventRow).join("")}</tbody></table></div>` : '<div class="empty">关注词暂时没有命中新事件。</div>'}
      ` : "";

      document.getElementById("content").innerHTML = `
        ${watchHtml}
        <div class="section-head">
          <h2>${needle ? "搜索结果" : "当前主线"}</h2>
          <p>${needle ? `匹配 ${events.length} 个事件` : "按时效、来源、独立印证和关注度综合排序"}</p>
        </div>
        <section class="lead-grid">${leadHtml}</section>
        <div class="section-head">
          <h2>事件列表</h2>
          <p>${meta.events_shown} 个已展示事件 · ${events.length} 个匹配</p>
        </div>
        ${tableHtml}
        <div class="section-head">
          <h2>热榜线索</h2>
          <p>只代表公众注意力，不代表事件已核实</p>
        </div>
        <section class="split">
          <div class="panel"><h3>关注词</h3><ul class="hot-list">${hotRows(hot)}</ul></div>
          <div class="panel"><h3>来源状态 · 最近12次</h3><ul class="source-list">${sourceRows(payload.source_status, healthHistory)}</ul></div>
        </section>`;
      document.querySelectorAll("[data-event-id]").forEach((button) => {
        button.addEventListener("click", () => {
          openEvent(currentEvents.find((item) => item.event_id === button.dataset.eventId));
        });
      });
      maybeNotify(watched);
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
        history.replaceState(null, "", `?view=${report.id}`);
        render();
        renderWatch();
        toast(`${report.label} 已加载`);
      });
      tabs.appendChild(button);
    });

    document.getElementById("searchInput").addEventListener("input", (event) => {
      query = event.target.value;
      render();
    });

    document.getElementById("watchAdd").addEventListener("click", () => {
      const input = document.getElementById("watchInput");
      const value = input.value.trim();
      if (value && !watchlist.includes(value)) {
        watchlist.push(value);
        watchlist = watchlist.slice(-20);
        writeStore(WATCH_KEY, watchlist);
        input.value = "";
        renderWatch();
        render();
        toast(`已关注“${value}”`);
        if ("Notification" in window && Notification.permission === "default") {
          Notification.requestPermission().catch(() => {});
        }
      }
    });
    document.getElementById("watchInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") document.getElementById("watchAdd").click();
    });

    document.getElementById("closeDialog").addEventListener("click", () => {
      document.getElementById("eventDialog").close();
      history.replaceState(null, "", `?view=${REPORTS[active].id}`);
    });
    document.getElementById("eventDialog").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) {
        event.currentTarget.close();
      }
    });
    document.getElementById("shareEvent").addEventListener("click", async () => {
      const url = new URL(location.href);
      url.searchParams.set("view", REPORTS[active].id);
      if (sharedEvent) url.searchParams.set("event", sharedEvent.event_id);
      try {
        await navigator.clipboard.writeText(url.toString());
        toast("事件链接已复制");
      } catch (_) {
        toast(url.toString());
      }
    });

    let toastTimer;
    const toast = (message) => {
      const node = document.getElementById("toast");
      node.textContent = message;
      node.classList.add("show");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => node.classList.remove("show"), 1800);
    };

    const refreshAt = Date.now() + AUTO_REFRESH_MS;
    const updateRefresh = () => {
      if (document.hidden) return;
      const left = Math.max(0, refreshAt - Date.now());
      const minutes = Math.ceil(left / 60000);
      document.getElementById("refreshState").textContent = minutes
        ? `${minutes} 分钟后检查更新`
        : "正在检查更新";
    };
    setInterval(updateRefresh, 30000);
    setTimeout(() => location.reload(), AUTO_REFRESH_MS);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() >= refreshAt) location.reload();
      updateRefresh();
    });

    if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    }

    renderWatch();
    render();
    updateRefresh();
    if (requestedEvent) {
      const event = currentEvents.find((item) => item.event_id === requestedEvent);
      if (event) openEvent(event);
    }
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


def load_state(path: Optional[Path]) -> dict:
    if not path or not path.exists():
        return {"events": {}, "health_history": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"events": {}, "health_history": []}
        data.setdefault("events", {})
        data.setdefault("health_history", [])
        return data
    except (OSError, ValueError, TypeError):
        return {"events": {}, "health_history": []}


def apply_change_tracking(reports: list[dict], state: dict) -> None:
    stored_events = state.get("events") or {}
    next_events: dict[str, dict] = {}
    for report in reports:
        for event in report["payload"]["events"]:
            key = f"{report['id']}:{event.get('event_id') or event.get('title')}"
            previous = stored_events.get(key)
            if not previous:
                event["change"] = "new"
                event["previous"] = None
            elif (
                previous.get("last_updated") != event.get("last_updated")
                or previous.get("status") != event.get("status")
            ):
                event["change"] = "updated"
                event["previous"] = {
                    "last_updated": previous.get("last_updated"),
                    "score": previous.get("score"),
                    "status": previous.get("status"),
                }
            else:
                event["change"] = "unchanged"
                event["previous"] = None
            next_events[key] = {
                "title": event.get("title"),
                "last_updated": event.get("last_updated"),
                "score": event.get("score"),
                "status": event.get("status"),
                "seen_at": report["payload"]["meta"].get("generated_at"),
            }
    state["events"] = next_events
    state["updated_at"] = pulse.iso_time(pulse.now_cn())


def append_health_history(
    state: dict,
    statuses: list[pulse.SourceStatus],
    generated_at: datetime,
) -> list[dict]:
    history = state.get("health_history") or []
    history.append(
        {
            "generated_at": pulse.iso_time(generated_at),
            "sources": [
                {
                    "name": row.name,
                    "ok": row.ok,
                    "items": row.items,
                    "detail": row.detail,
                }
                for row in statuses
            ],
        }
    )
    history = history[-48:]
    state["health_history"] = history
    return history


def write_state(path: Optional[Path], state: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def strip_markdown(value: object) -> str:
    return pulse.clean_text(value, 1000)


def build_digest_markdown(report: dict) -> str:
    payload = report["payload"]
    meta = payload["meta"]
    lines = [
        f"# 国内时事日报｜{meta['generated_at'][:10]}",
        "",
        f"截至 {meta['generated_at']}，最近 {meta['window_hours']} 小时重点事件。",
        "",
    ]
    for index, event in enumerate(payload["events"][:6], 1):
        lines.append(f"## {index}. {event['title']}")
        lines.append("")
        lines.append(strip_markdown(event.get("summary")))
        lines.append("")
        if event.get("why_important"):
            lines.append("为什么重要：" + "；".join(event["why_important"]) + "。")
            lines.append("")
        for source in event.get("sources", [])[:2]:
            if source.get("url"):
                lines.append(f"- [{source['name']}]({source['url']})")
        lines.append("")
    lines.append("热榜与热搜仅作为关注度线索，事实以原文和后续通报为准。")
    lines.append("")
    return "\n".join(lines)


def build_digest_atom(report: dict, page_url: str) -> str:
    payload = report["payload"]
    meta = payload["meta"]
    updated = meta["generated_at"]
    entries = []
    for event in payload["events"][:10]:
        source_url = next(
            (source["url"] for source in event.get("sources", []) if source.get("url")),
            page_url,
        )
        entries.append(
            f"""<entry>
  <title>{esc(event.get("title"))}</title>
  <link href="{esc(source_url)}"/>
  <id>urn:cn-news-pulse:{esc(event.get("event_id"))}</id>
  <updated>{esc(event.get("last_updated") or updated)}</updated>
  <summary>{esc(event.get("summary"))}</summary>
</entry>"""
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>国内时事日报</title>
  <id>{esc(page_url)}</id>
  <link href="{esc(page_url)}"/>
  <updated>{esc(updated)}</updated>
  <author><name>CN News Pulse</name></author>
  {"".join(entries)}
</feed>
"""


PWA_ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="120" fill="#e55353"/>
  <path d="M142 126h228v260H142z" fill="#fff8f5"/>
  <path d="M185 180h142M185 232h142M185 284h95" stroke="#17233d" stroke-width="25" stroke-linecap="round"/>
  <circle cx="337" cy="337" r="78" fill="#17233d"/>
  <path d="M337 295v42l28 18" fill="none" stroke="#ffffff" stroke-width="16" stroke-linecap="round"/>
</svg>
"""


def make_pwa_png(size: int) -> bytes:
    red = (229, 83, 83, 255)
    white = (255, 248, 245, 255)
    navy = (23, 35, 61, 255)
    transparent = (255, 255, 255, 0)
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            nx = x / max(1, size - 1)
            ny = y / max(1, size - 1)
            color = red
            if 0.18 <= nx <= 0.82 and 0.18 <= ny <= 0.82:
                color = white
            if 0.31 <= ny <= 0.35 and 0.30 <= nx <= 0.70:
                color = navy
            if 0.44 <= ny <= 0.48 and 0.30 <= nx <= 0.70:
                color = navy
            if 0.57 <= ny <= 0.61 and 0.30 <= nx <= 0.55:
                color = navy
            cx, cy, radius = 0.67, 0.66, 0.15
            if (nx - cx) ** 2 + (ny - cy) ** 2 <= radius ** 2:
                color = navy
            if (nx - cx) ** 2 + (ny - cy) ** 2 <= 0.105 ** 2:
                color = white
            if color == white and (
                (abs(nx - cx) <= 0.018 and cy - 0.01 <= ny <= cy)
                or (abs(ny - cy) <= 0.018 and cx <= nx <= cx + 0.075)
            ):
                color = navy
            if (nx < 0.10 or nx > 0.90 or ny < 0.10 or ny > 0.90):
                color = transparent
            pixels.extend(color)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + chunk(b"IEND", b"")
    )


def write_sidecars(
    output: Path,
    report: dict,
    generated_at: datetime,
    page_url: str,
) -> None:
    directory = output.parent
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "国内时事简报",
        "short_name": "国内时事",
        "description": "聚合国内公开新闻、事件时间线和热榜线索。",
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#f2f5f9",
        "theme_color": "#17233d",
        "lang": "zh-CN",
        "icons": [
            {
                "src": "icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            }
        ],
    }
    (directory / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (directory / "icon.svg").write_text(PWA_ICON, encoding="utf-8")
    (directory / "icon-192.png").write_bytes(make_pwa_png(192))
    (directory / "icon-512.png").write_bytes(make_pwa_png(512))
    version = generated_at.strftime("%Y%m%d%H%M")
    service_worker = f"""const CACHE_NAME = "cn-news-pulse-{version}";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg", "./icon-192.png"];
self.addEventListener("install", (event) => {{
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
}});
self.addEventListener("activate", (event) => {{
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
}});
self.addEventListener("fetch", (event) => {{
  if (event.request.mode === "navigate") {{
    event.respondWith(
      fetch(event.request)
        .then((response) => {{
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("./index.html", copy));
          return response;
        }})
        .catch(() => caches.match("./index.html"))
    );
  }}
}});
"""
    (directory / "sw.js").write_text(service_worker, encoding="utf-8")
    digest = build_digest_markdown(report)
    (directory / "digest.md").write_text(digest, encoding="utf-8")
    (directory / "digest.xml").write_text(
        build_digest_atom(report, page_url),
        encoding="utf-8",
    )


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
    why = event.get("why_important") or []
    why_html = f'<div class="hot-note">为什么重要：{esc(why[0])}</div>' if why else ""
    change = event.get("change")
    change_html = (
        '<span class="change new">新事件</span>'
        if change == "new"
        else '<span class="change updated">刚刚更新</span>'
        if change == "updated"
        else ""
    )
    official_html = '<span class="change">官方来源</span>' if event.get("official_publishers") else ""
    return f"""
      <article class="event {klass}">
        <div class="event-top">
          <span class="pill {klass}">{esc(event.get("status"))}</span>
          {change_html}
          {official_html}
          <span class="meter">优先级 {float(event.get("score") or 0):.1f} · 置信度 {int(event.get("confidence") or 0)}</span>
        </div>
        <div class="event-index">{index + 1:02d}</div>
        <h3>{esc(event.get("title"))}</h3>
        <p>{esc(event.get("summary") or "暂无摘要")}</p>
        {why_html}
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
        <td>
          <strong class="event-title">{esc(event.get("title"))}</strong>
          <span class="row-summary">{esc(event.get("summary") or "")}</span>
        </td>
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
    parser.add_argument("--cache-dir", help="保存跨运行事件状态和来源健康历史的目录")
    parser.add_argument("--site-url", default="https://guoweibo2013.github.io/cn-news-page/", help="公开主页地址")
    parser.add_argument("--fail-if-empty", action="store_true", help="没有任何新闻或事件时以失败退出，保留上一版页面")
    parser.add_argument("--no-site-news", action="store_true", help="不抓取政府和新华网首页要闻")
    args = parser.parse_args()

    generated_at = pulse.now_cn()
    max_hours = max(preset["hours"] for preset in PRESETS)
    cutoff = generated_at - timedelta(hours=max_hours)
    news_items, news_status = pulse.load_feeds([], args.timeout, cutoff, 200)
    if not args.no_site_news:
        site_items, site_status = pulse.load_site_news(
            args.timeout,
            cutoff,
            max_items_per_site=10,
        )
        news_items.extend(site_items)
        news_status.extend(site_status)
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
    if args.fail_if_empty and (
        not news_items
        or not any(report["payload"]["events"] for report in reports)
    ):
        sys.stderr.write("refusing to publish an empty dashboard\n")
        return 2

    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else None
    state_path = cache_dir / "dashboard-state.json" if cache_dir else None
    state = load_state(state_path)
    health_history = append_health_history(
        state,
        news_status + hot_status,
        generated_at,
    )
    apply_change_tracking(reports, state)
    for report in reports:
        report["payload"]["meta"]["health_history"] = health_history

    output = build_page(reports, generated_at)
    target = Path(args.output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")
    write_sidecars(target, reports[0], generated_at, args.site_url)
    write_state(state_path, state)
    failed = [row.name for row in news_status + hot_status if not row.ok]
    if failed:
        sys.stderr.write("degraded sources: " + ", ".join(failed) + "\n")
    sys.stderr.write(f"saved: {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
