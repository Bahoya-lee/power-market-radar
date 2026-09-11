/* 电力市场研究前沿追踪 —— 前端逻辑（无外部依赖） */
(function () {
  "use strict";

  // ============================================================ 数据装载

  var REAL = window.__PM_DATA__ || null;
  var DEMO = window.__PM_DEMO__ || null;

  var hasReal = !!(REAL && REAL.papers && REAL.papers.length);
  var usingDemo = !hasReal && !!(DEMO && DEMO.papers && DEMO.papers.length);

  var DATA = usingDemo ? DEMO : (REAL || { meta: {}, insights: {}, papers: [], topics: [] });
  DATA.papers = DATA.papers || [];
  DATA.topics = DATA.topics || [];
  DATA.insights = DATA.insights || { hotspots: [], trends: { months: [], series: {} }, rising: [], summary: {} };
  DATA.meta = DATA.meta || {};

  var TOPIC_MAP = {};
  DATA.topics.forEach(function (t) { TOPIC_MAP[t.id] = t; });

  var PAGE_SIZE = 20;

  // ============================================================ 本地状态

  var LS = {
    fav: "pmr.fav", read: "pmr.read", theme: "pmr.theme", errorAt: "pmr.errorAt"
  };

  function loadSet(key) {
    try {
      var raw = localStorage.getItem(key);
      return new Set(raw ? JSON.parse(raw) : []);
    } catch (e) { return new Set(); }
  }
  function saveSet(key, set) {
    try { localStorage.setItem(key, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  var favSet = loadSet(LS.fav);
  var readSet = loadSet(LS.read);

  var state = {
    q: "",
    days: 0,
    topics: new Set(),
    sources: new Set(),
    sort: "newest",
    onlyFav: false,
    onlyUnread: false,
    onlyNew: false,
    hidden: new Set(),      // 趋势图上被点掉的系列
    page: 1,
    exportFmt: "bibtex"
  };

  // ============================================================ 小工具

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function daysSince(iso) {
    if (!iso) return 1e9;
    var d = new Date(iso.slice(0, 10) + "T00:00:00");
    if (isNaN(d)) return 1e9;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  function fmtDate(iso) {
    if (!iso) return "日期未知";
    var m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return iso;
    return m[1] + "年" + parseInt(m[2], 10) + "月";
  }

  function pad2(n) { return n < 10 ? "0" + n : "" + n; }

  var toastTimer = null;
  function toast(msg) {
    var el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 2200);
  }

  function topicColor(id) {
    var t = TOPIC_MAP[id];
    return (t && t.color) || "#4da3ff";
  }
  function topicName(id) {
    var t = TOPIC_MAP[id];
    return (t && t.zh) || id;
  }

  function download(filename, text, mime) {
    var blob = new Blob([text], { type: (mime || "text/plain") + ";charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  function copyText(text, okMsg) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast(okMsg || "已复制"); },
        function () { fallbackCopy(text, okMsg); });
    } else {
      fallbackCopy(text, okMsg);
    }
  }
  function fallbackCopy(text, okMsg) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); toast(okMsg || "已复制"); }
    catch (e) { toast("复制失败，请手动选择"); }
    document.body.removeChild(ta);
  }

  // ============================================================ 中文检索扩展

  // 用户输入中文时，把对应主题的英文检索词一起纳入匹配，
  // 否则中文关键词几乎匹配不到英文文献。
  var ZH_ALIAS = [];
  DATA.topics.forEach(function (t) {
    var terms = [t.zh].concat((t.keywords || []).filter(function (k) {
      return /[\u4e00-\u9fff]/.test(k);
    }));
    ZH_ALIAS.push({ terms: terms, topic: t.id });
  });

  function expandQuery(q) {
    var base = q.trim().toLowerCase();
    if (!base) return { text: "", terms: [], topics: [] };

    var terms = [base];
    var topics = [];
    ZH_ALIAS.forEach(function (item) {
      var hit = item.terms.some(function (t) {
        return base.indexOf(t.toLowerCase()) >= 0 || t.toLowerCase().indexOf(base) >= 0 && base.length >= 2;
      });
      if (hit) {
        topics.push(item.topic);
        var t = TOPIC_MAP[item.topic];
        if (t && t.keywords) {
          t.keywords.forEach(function (k) {
            if (!/[\u4e00-\u9fff]/.test(k)) terms.push(k.toLowerCase());
          });
        }
      }
    });
    return { text: base, terms: terms, topics: topics };
  }

  function paperText(p) {
    return [
      p.title || "",
      p.abstract || "",
      (p.authors || []).join(" "),
      p.venue || "",
      (p.topics || []).map(topicName).join(" ")
    ].join(" ").toLowerCase();
  }

  function relevanceScore(p, terms) {
    if (!terms.length) return 0;
    var title = (p.title || "").toLowerCase();
    var abs = (p.abstract || "").toLowerCase();
    var score = 0;
    terms.forEach(function (t) {
      if (!t) return;
      var inTitle = title.split(t).length - 1;
      var inAbs = abs.split(t).length - 1;
      score += inTitle * 4 + inAbs;
    });
    return score;
  }

  // ============================================================ 过滤与排序

  function filtered() {
    var q = expandQuery(state.q);
    var out = [];

    DATA.papers.forEach(function (p) {
      if (state.days > 0 && daysSince(p.date) > state.days) return;
      if (state.onlyFav && !favSet.has(p.uid)) return;
      if (state.onlyUnread && readSet.has(p.uid)) return;
      if (state.onlyNew && !p.is_new) return;
      if (state.sources.size && !state.sources.has(p.source_name || p.source)) return;
      if (state.topics.size) {
        var hit = (p.topics || []).some(function (t) { return state.topics.has(t); });
        if (!hit) return;
      }
      if (q.text) {
        var text = paperText(p);
        var ok = q.terms.some(function (t) { return text.indexOf(t) >= 0; });
        if (!ok) return;
      }
      out.push(p);
    });

    var terms = q.terms;
    out.sort(function (a, b) {
      switch (state.sort) {
        case "cited":
          return (b.citations || 0) - (a.citations || 0);
        case "velocity":
          return (b.cite_per_year || 0) - (a.cite_per_year || 0);
        case "venue":
          return (b.journal_weight || 0) - (a.journal_weight || 0)
            || String(b.date || "").localeCompare(String(a.date || ""));
        case "relevance":
          return relevanceScore(b, terms) - relevanceScore(a, terms)
            || String(b.date || "").localeCompare(String(a.date || ""));
        default:
          return String(b.date || "").localeCompare(String(a.date || ""))
            || (b.citations || 0) - (a.citations || 0);
      }
    });
    return out;
  }

  // ============================================================ 渲染：统计

  function renderStats() {
    var m = DATA.meta || {};
    var ins = DATA.insights.summary || {};
    var cards = [
      { label: "收录文献", value: m.total || DATA.papers.length || 0, unit: "篇" },
      { label: "近 30 天新增", value: m.recent30 || ins.recent30 || 0, unit: "篇" },
      { label: "今日新增", value: m.new_today || 0, unit: "篇" },
      { label: "开放获取", value: m.oa || ins.oa || 0, unit: "篇" },
      { label: "覆盖主题", value: (DATA.insights.hotspots || []).length || DATA.topics.length, unit: "个" }
    ];
    $("stats").innerHTML = cards.map(function (c) {
      return '<div class="stat"><div class="stat-label">' + esc(c.label) + '</div>' +
        '<div class="stat-value">' + c.value + '<small>' + esc(c.unit) + '</small></div></div>';
    }).join("");
  }

  function renderHeader() {
    var m = DATA.meta || {};
    $("updateText").textContent = m.updated_at ? "更新于 " + m.updated_at : "尚未更新";
    var total = m.total || DATA.papers.length || 0;
    $("pageSummary").textContent = usingDemo
      ? "当前展示演示数据，用于预览界面；抓取真实文献后会自动切换。"
      : "本地文献库已收录 " + total + " 篇，最近更新于 " + (m.updated_at || "尚未更新") + "。";

    $("demoBanner").hidden = !usingDemo;

    var errs = m.errors || [];
    var dismissedError = "";
    try { dismissedError = localStorage.getItem(LS.errorAt) || ""; } catch (e) {}
    if (errs.length && dismissedError !== (m.updated_at || "")) {
      var names = {};
      errs.forEach(function (e) { names[e.source] = (names[e.source] || 0) + 1; });
      var keys = Object.keys(names);
      var labels = { arxiv: "arXiv", openalex: "OpenAlex", crossref: "Crossref", semanticscholar: "Semantic Scholar" };
      var list = keys.map(function (k) { return labels[k] || k; }).join("、");
      var message = keys.length === 1 && keys[0] === "arxiv"
        ? "arXiv 接口本次不可用，系统已自动跳过；OpenAlex 等来源已正常更新。"
        : "本次有 " + errs.length + " 次数据源连接失败：" + list + "。其余来源已正常更新。";
      $("errorBanner").innerHTML = '<span aria-hidden="true">⚠</span><span class="banner-message">' +
        esc(message) + '</span><button class="banner-dismiss" type="button" aria-label="关闭提示">✕</button>';
      $("errorBanner").hidden = false;
      $("errorBanner").querySelector(".banner-dismiss").addEventListener("click", function () {
        $("errorBanner").hidden = true;
        try { localStorage.setItem(LS.errorAt, m.updated_at || ""); } catch (e) {}
      });
    } else {
      $("errorBanner").hidden = true;
    }
  }

  // ============================================================ 渲染：工具栏

  function renderSourceChips() {
    var counts = {};
    DATA.papers.forEach(function (p) {
      var n = p.source_name || p.source || "未知";
      counts[n] = (counts[n] || 0) + 1;
    });
    var names = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
    $("sourceGroup").innerHTML = names.map(function (n) {
      return '<button class="chip" type="button" data-src="' + esc(n) + '" aria-pressed="false">' + esc(n) +
        ' <span class="cnt">' + counts[n] + '</span></button>';
    }).join("");
    Array.prototype.forEach.call($("sourceGroup").querySelectorAll(".chip"), function (btn) {
      btn.addEventListener("click", function () {
        var v = btn.getAttribute("data-src");
        if (state.sources.has(v)) state.sources.delete(v); else state.sources.add(v);
        btn.classList.toggle("active");
        btn.setAttribute("aria-pressed", state.sources.has(v) ? "true" : "false");
        state.page = 1;
        renderList();
      });
    });
  }

  function renderTopicChips() {
    var counts = {};
    DATA.papers.forEach(function (p) {
      (p.topics || []).forEach(function (t) { counts[t] = (counts[t] || 0) + 1; });
    });
    var ordered = DATA.topics.slice().sort(function (a, b) {
      return (counts[b.id] || 0) - (counts[a.id] || 0);
    });
    $("topicBar").innerHTML = ordered.map(function (t) {
      return '<button class="topic-chip" type="button" data-topic="' + esc(t.id) + '" aria-pressed="false" style="--c:' + esc(t.color) + '">' +
        '<span class="swatch"></span>' + esc(t.zh) +
        ' <span class="cnt">' + (counts[t.id] || 0) + '</span></button>';
    }).join("");
    Array.prototype.forEach.call($("topicBar").querySelectorAll(".topic-chip"), function (btn) {
      btn.addEventListener("click", function () {
        var v = btn.getAttribute("data-topic");
        if (state.topics.has(v)) state.topics.delete(v); else state.topics.add(v);
        btn.classList.toggle("on");
        btn.setAttribute("aria-pressed", state.topics.has(v) ? "true" : "false");
        state.page = 1;
        renderList();
      });
    });
  }

  function syncFilterChips() {
    $("favFilter").classList.toggle("on", state.onlyFav);
    $("unreadFilter").classList.toggle("on", state.onlyUnread);
    $("newFilter").classList.toggle("on", state.onlyNew);
    $("favFilter").setAttribute("aria-pressed", state.onlyFav ? "true" : "false");
    $("unreadFilter").setAttribute("aria-pressed", state.onlyUnread ? "true" : "false");
    $("newFilter").setAttribute("aria-pressed", state.onlyNew ? "true" : "false");
    Array.prototype.forEach.call($("rangeGroup").querySelectorAll(".chip"), function (b) {
      var on = Number(b.getAttribute("data-days")) === state.days;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  // ============================================================ 渲染：列表

  function badgeHtml(p) {
    var out = [];
    (p.topics || []).slice(0, 3).forEach(function (t) {
      out.push('<span class="badge topic" style="--c:' + esc(topicColor(t)) + '">' + esc(topicName(t)) + '</span>');
    });
    if (p.is_new) out.push('<span class="badge new">✦ 今日新增</span>');
    if (p.is_top_venue) out.push('<span class="badge top">重点期刊</span>');
    if (p.is_oa) out.push('<span class="badge oa">开放获取</span>');
    if (p.source === "arxiv" || p.type === "preprint") out.push('<span class="badge">预印本</span>');
    if (p.source === "demo") out.push('<span class="badge">演示数据</span>');
    return '<div class="badges">' + out.join("") + '</div>';
  }

  function authorsText(p) {
    var a = p.authors || [];
    if (!a.length) return "作者未标注";
    if (a.length <= 4) return a.join("、");
    return a.slice(0, 4).join("、") + " 等 " + a.length + " 人";
  }

  function paperHtml(p, idx) {
    var isFav = favSet.has(p.uid);
    var isRead = readSet.has(p.uid);
    var cls = "paper" + (isFav ? " fav" : "") + (isRead ? " read" : "");
    var url = p.url || (p.doi ? "https://doi.org/" + p.doi : "");

    var meta = [];
    meta.push('<span>' + esc(authorsText(p)) + '</span>');
    if (p.venue) meta.push('<span class="venue">' + esc(p.venue) + '</span>');
    meta.push('<span>' + esc(fmtDate(p.date)) + '</span>');
    if (p.citations) meta.push('<span>被引 ' + p.citations + '</span>');

    var abs = p.abstract || "";
    var absHtml = abs
      ? '<p class="abstract" data-abs>' + esc(abs) + '</p>' +
        '<button class="abstract-toggle" type="button" data-toggle-abs aria-expanded="false">展开摘要</button>'
      : '<p class="abstract muted">暂无摘要</p>';

    var actions = [];
    actions.push('<button class="act' + (isFav ? " on" : "") + '" type="button" data-fav aria-pressed="' +
      (isFav ? "true" : "false") + '" title="加入收藏">★ 收藏</button>');
    actions.push('<button class="act' + (isRead ? " read-on" : "") + '" type="button" data-read aria-pressed="' +
      (isRead ? "true" : "false") + '" title="标记已读">✓ 已读</button>');
    actions.push('<button class="act primary-action" type="button" data-detail>查看详情</button>');
    actions.push('<button class="act" type="button" data-cite>复制引用</button>');
    actions.push('<button class="act" type="button" data-bib>BibTeX</button>');
    if (url) actions.push('<a class="act link" href="' + esc(url) + '" target="_blank" rel="noopener">原文 ↗</a>');
    if (p.pdf_url) actions.push('<a class="act link" href="' + esc(p.pdf_url) + '" target="_blank" rel="noopener">PDF ↗</a>');
    if (p.doi) actions.push('<span class="act" style="cursor:default;opacity:.7">DOI ' + esc(p.doi) + '</span>');

    return '<article class="' + cls + '" data-uid="' + esc(p.uid) + '">' +
      '<div class="paper-top">' +
        '<div class="paper-idx">' + idx + '</div>' +
        '<div class="paper-body">' +
          '<h3 class="paper-title">' +
            '<button class="paper-title-link" type="button" data-detail>' + esc(p.title) + '</button>' +
          '</h3>' +
          '<div class="paper-meta">' + meta.join("") + '</div>' +
          badgeHtml(p) +
          absHtml +
          '<div class="paper-actions">' + actions.join("") + '</div>' +
        '</div>' +
      '</div>' +
    '</article>';
  }

  function bindPaperEvents() {
    Array.prototype.forEach.call(document.querySelectorAll(".paper"), function (card) {
      var uid = card.getAttribute("data-uid");
      var paper = DATA.papers.filter(function (p) { return p.uid === uid; })[0];
      if (!paper) return;

      var absBtn = card.querySelector("[data-toggle-abs]");
      if (absBtn) {
        absBtn.addEventListener("click", function () {
          var abs = card.querySelector("[data-abs]");
          var open = abs.classList.toggle("open");
          absBtn.textContent = open ? "收起摘要" : "展开摘要";
          absBtn.setAttribute("aria-expanded", open ? "true" : "false");
        });
      }

      card.querySelector("[data-fav]").addEventListener("click", function () {
        if (favSet.has(uid)) { favSet.delete(uid); toast("已取消收藏"); }
        else { favSet.add(uid); toast("已加入收藏"); }
        saveSet(LS.fav, favSet);
        renderList();
      });

      card.querySelector("[data-read]").addEventListener("click", function () {
        if (readSet.has(uid)) { readSet.delete(uid); toast("已标记为未读"); }
        else { readSet.add(uid); toast("已标记为已读"); }
        saveSet(LS.read, readSet);
        renderList();
      });

      card.querySelector("[data-cite]").addEventListener("click", function () {
        copyText(apaText(paper), "已复制参考文献");
      });

      card.querySelector("[data-bib]").addEventListener("click", function () {
        copyText(bibtex(paper), "已复制 BibTeX");
      });

      Array.prototype.forEach.call(card.querySelectorAll("[data-detail]"), function (button) {
        button.addEventListener("click", function () {
          openDetail(paper);
        });
      });
    });
  }

  function renderList() {
    var rows = filtered();
    var shown = rows.slice(0, state.page * PAGE_SIZE);

    $("resultCount").textContent = rows.length
      ? "共 " + rows.length + " 篇，显示 " + shown.length + " 篇"
      : "";
    $("listTitle").textContent = state.onlyFav ? "我的收藏" : "文献列表";

    var box = $("paperList");
    if (!rows.length) {
      box.innerHTML = "";
      var empty = $("emptyState");
      empty.hidden = false;
      if (DATA.papers.length === 0) {
        empty.innerHTML = '<h3>还没有文献数据</h3>' +
          '<p>双击项目文件夹里的「一键更新.bat」，脚本会自动抓取最新文献并刷新本页数据。</p>' +
          '<ol>' +
          '<li>确认电脑可以正常上网</li>' +
          '<li>双击运行 <code>一键更新.bat</code>（首次约需 2—5 分钟）</li>' +
          '<li>运行结束后会自动打开本页面</li>' +
          '<li>想要每天自动更新，再双击 <code>注册每日更新任务.bat</code></li>' +
          '</ol>' +
          '<p class="muted">想先看看界面效果，可以点上方横幅中的演示数据。</p>';
      } else {
        empty.innerHTML = '<h3>没有符合条件的文献</h3><p>试试放宽时间范围，或点「重置筛选」。</p>';
      }
    } else {
      $("emptyState").hidden = true;
      box.innerHTML = shown.map(function (p, i) { return paperHtml(p, i + 1); }).join("");
      bindPaperEvents();
    }

    $("loadMoreBtn").hidden = shown.length >= rows.length;
    $("loadMoreBtn").textContent = "加载更多（还有 " + Math.max(0, rows.length - shown.length) + " 篇）";
  }

  // ============================================================ 渲染：侧栏

  function sparkline(values, color) {
    if (!values || !values.length) return "";
    var max = Math.max.apply(null, values.concat([1]));
    var pts = values.map(function (v, i) {
      var x = (i / Math.max(1, values.length - 1)) * 100;
      var y = 18 - (v / max) * 16;
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    return '<svg viewBox="0 0 100 20" preserveAspectRatio="none" style="width:74px;height:20px">' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.6"/></svg>';
  }

  function renderHotspots() {
    var hot = DATA.insights.hotspots || [];
    $("hotMeta").textContent = hot.length ? "共 " + hot.length + " 个方向" : "";
    if (!hot.length) {
      $("hotList").innerHTML = '<p class="muted">更新数据后这里会显示各主题的热度排行。</p>';
      return;
    }
    var top = hot.slice(0, 10);
    var max = Math.max.apply(null, top.map(function (h) { return h.score || 0; }).concat([1]));
    $("hotList").innerHTML = top.map(function (h) {
      var w = Math.round(((h.score || 0) / max) * 100);
      var arrow = h.level === "升温"
        ? '<span class="trend-up">▲ 升温 ×' + h.momentum + '</span>'
        : (h.level === "降温"
          ? '<span class="trend-down">▼ 降温 ×' + h.momentum + '</span>'
          : '<span>— 平稳 ×' + h.momentum + '</span>');
      return '<button class="hot-row" type="button" data-hot="' + esc(h.id) + '" aria-label="筛选主题：' + esc(h.zh) + '">' +
        '<div class="hot-line"><span class="hot-name">' + esc(h.zh) + '</span>' +
        '<span class="hot-score">' + h.score + '</span></div>' +
        '<div class="hot-bar"><i style="width:' + w + '%;background:' + esc(h.color) + '"></i></div>' +
        '<div class="hot-sub">近 30 天 ' + h.recent30 + ' 篇 · 近半年 ' + h.recent180 + ' 篇 · ' + arrow + '</div>' +
      '</button>';
    }).join("");

    Array.prototype.forEach.call($("hotList").querySelectorAll(".hot-row"), function (row) {
      row.addEventListener("click", function () {
        var id = row.getAttribute("data-hot");
        state.topics.clear();
        state.topics.add(id);
        state.page = 1;
        Array.prototype.forEach.call($("topicBar").querySelectorAll(".topic-chip"), function (b) {
          b.classList.toggle("on", b.getAttribute("data-topic") === id);
        });
        renderList();
        toast("已筛选：" + topicName(id));
      });
    });
  }

  function renderTrend() {
    var trends = DATA.insights.trends || { months: [], series: {} };
    var months = trends.months || [];
    var svg = $("trendChart");
    var legend = $("trendLegend");

    if (!months.length) {
      svg.innerHTML = "";
      legend.innerHTML = "";
      return;
    }

    var hot = (DATA.insights.hotspots || []).slice(0, 6);
    var W = 520, H = 260;
    var padL = 34, padR = 12, padT = 14, padB = 30;
    var iw = W - padL - padR, ih = H - padT - padB;

    var maxV = 1;
    hot.forEach(function (h) {
      (trends.series[h.id] || []).forEach(function (v) { if (v > maxV) maxV = v; });
    });
    maxV = Math.ceil(maxV * 1.15);

    function X(i) { return padL + (i / Math.max(1, months.length - 1)) * iw; }
    function Y(v) { return padT + ih - (v / maxV) * ih; }

    var parts = [];

    // 网格与 Y 轴刻度
    for (var g = 0; g <= 4; g++) {
      var val = Math.round((maxV / 4) * g);
      var y = Y(val);
      parts.push('<line x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y +
        '" stroke="currentColor" stroke-opacity=".12" stroke-width="1"/>');
      parts.push('<text x="' + (padL - 7) + '" y="' + (y + 4) + '" text-anchor="end" ' +
        'font-size="10" fill="currentColor" fill-opacity=".45">' + val + '</text>');
    }

    // X 轴月份（每隔 2 个标一次）
    months.forEach(function (m, i) {
      if (i % 2 !== 0 && i !== months.length - 1) return;
      parts.push('<text x="' + X(i) + '" y="' + (H - 9) + '" text-anchor="middle" ' +
        'font-size="10" fill="currentColor" fill-opacity=".45">' + esc(m.slice(2)) + '</text>');
    });

    hot.forEach(function (h) {
      if (state.hidden.has(h.id)) return;
      var vals = trends.series[h.id] || [];
      var pts = vals.map(function (v, i) { return X(i) + "," + Y(v); }).join(" ");
      parts.push('<polyline points="' + pts + '" fill="none" stroke="' + esc(h.color) +
        '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>');
      vals.forEach(function (v, i) {
        parts.push('<circle cx="' + X(i) + '" cy="' + Y(v) + '" r="2.4" fill="' + esc(h.color) + '"/>');
      });
    });

    svg.innerHTML = parts.join("");

    legend.innerHTML = hot.map(function (h) {
      var off = state.hidden.has(h.id) ? " off" : "";
      return '<span class="' + off.trim() + '" data-legend="' + esc(h.id) + '" role="button" tabindex="0" aria-pressed="' +
        (state.hidden.has(h.id) ? "false" : "true") + '">' +
        '<i style="background:' + esc(h.color) + '"></i>' + esc(h.zh) + '</span>';
    }).join("");

    Array.prototype.forEach.call(legend.querySelectorAll("span"), function (sp) {
      function toggleSeries() {
        var id = sp.getAttribute("data-legend");
        if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
        renderTrend();
      }
      sp.addEventListener("click", toggleSeries);
      sp.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleSeries();
        }
      });
    });
  }

  function renderRising() {
    var rising = DATA.insights.rising || [];
    var box = $("risingCloud");
    if (!rising.length) {
      box.innerHTML = '<p class="muted">积累一定文献量后，这里会自动显示上升中的新术语。</p>';
      return;
    }
    var maxW = Math.max.apply(null, rising.map(function (r) { return r.weight || 0; }).concat([1]));
    box.innerHTML = rising.slice(0, 28).map(function (r) {
      var ratio = (r.weight || 0) / maxW;
      var size = (11.5 + ratio * 8).toFixed(1);
      var alpha = (0.55 + ratio * 0.45).toFixed(2);
      var cls = r.is_new ? "fresh" : "";
      var tip = "近半年 " + r.count + " 篇，此前 " + r.prev_count + " 篇，增长 ×" + r.growth;
      return '<span class="' + cls + '" style="font-size:' + size + 'px;color:rgba(77,163,255,' +
        alpha + ')" title="' + esc(tip) + '">' + esc(r.term) + '</span>';
    }).join("");
  }

  function renderCnLinks() {
    var targets = [
      ["知网 CNKI", "https://kns.cnki.net/kns8s/defaultresult/index?kw={q}&korder=SU"],
      ["万方", "https://s.wanfangdata.com.cn/paper?q={q}"],
      ["百度学术", "https://xueshu.baidu.com/s?wd={q}"],
      ["Google 学术", "https://scholar.google.com/scholar?q={q}"]
    ];

    var hot = (DATA.insights.hotspots || []).slice(0, 6);
    var queries = hot.length ? hot.map(function (h) { return h.zh; }) : ["电力市场"];

    var chips = queries.map(function (q) {
      return '<button class="chip" type="button" data-cnq="' + esc(q) + '" aria-pressed="false">' + esc(q) + '</button>';
    }).join("");

    $("cnLinks").innerHTML =
      '<div class="cn-query" style="grid-column:1/-1">' + chips + '</div>' +
      targets.map(function (t) {
        return '<a href="' + t[1].replace("{q}", encodeURIComponent(queries[0])) +
          '" target="_blank" rel="noopener" data-tpl="' + esc(t[1]) + '">' + esc(t[0]) + '</a>';
      }).join("");

    var current = queries[0];
    function apply() {
      Array.prototype.forEach.call($("cnLinks").querySelectorAll("a[data-tpl]"), function (a) {
        a.href = a.getAttribute("data-tpl").replace("{q}", encodeURIComponent(current));
      });
      Array.prototype.forEach.call($("cnLinks").querySelectorAll("[data-cnq]"), function (b) {
        var on = b.getAttribute("data-cnq") === current;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
    Array.prototype.forEach.call($("cnLinks").querySelectorAll("[data-cnq]"), function (b) {
      b.addEventListener("click", function () {
        current = b.getAttribute("data-cnq");
        apply();
      });
    });
    apply();
  }

  function renderSourceStats() {
    var list = (DATA.insights.summary && DATA.insights.summary.sources) || [];
    if (!list.length) {
      $("sourceStats").innerHTML = '<p class="muted">暂无数据。</p>';
      return;
    }
    var max = Math.max.apply(null, list.map(function (s) { return s.count; }));
    $("sourceStats").innerHTML = list.map(function (s) {
      return '<div class="src-line"><span class="name">' + esc(s.name) + '</span>' +
        '<span class="bar"><i style="width:' + Math.round(s.count / max * 100) + '%"></i></span>' +
        '<span class="num">' + s.count + '</span></div>';
    }).join("");
  }

  // ============================================================ 引用格式

  function firstAuthor(p) {
    var a = (p.authors || [])[0] || "佚名";
    return a;
  }

  function bibKey(p) {
    var name = firstAuthor(p).replace(/[^A-Za-z\u4e00-\u9fff]/g, "");
    return (name || "ref") + (p.year || "");
  }

  function bibtex(p) {
    var type = p.source === "arxiv" ? "misc" : "article";
    var lines = ["@" + type + "{" + bibKey(p) + ","];
    lines.push("  title   = {" + (p.title || "") + "},");
    if ((p.authors || []).length) lines.push("  author  = {" + p.authors.join(" and ") + "},");
    if (p.venue) lines.push("  journal = {" + p.venue + "},");
    if (p.year) lines.push("  year    = {" + p.year + "},");
    if (p.doi) lines.push("  doi     = {" + p.doi + "},");
    if (p.url) lines.push("  url     = {" + p.url + "},");
    lines.push("}");
    return lines.join("\n");
  }

  function apaText(p) {
    var a = (p.authors || []).slice(0, 3).join(", ");
    if ((p.authors || []).length > 3) a += ", et al.";
    if (!a) a = "佚名";
    return a + " (" + (p.year || "n.d.") + "). " + (p.title || "") +
      (p.venue ? ". " + p.venue : "") +
      (p.doi ? ". https://doi.org/" + p.doi : (p.url ? ". " + p.url : ""));
  }

  function csvCell(v) {
    v = String(v == null ? "" : v);
    return '"' + v.replace(/"/g, '""') + '"';
  }

  function buildExport(fmt) {
    var list = DATA.papers.filter(function (p) { return favSet.has(p.uid); });
    if (!list.length) return { text: "（收藏夹是空的，先在文献卡片上点「★ 收藏」）", count: 0 };

    if (fmt === "bibtex") {
      return { text: list.map(bibtex).join("\n\n"), count: list.length };
    }
    if (fmt === "markdown") {
      var lines = ["# 电力市场研究 · 收藏文献（" + list.length + " 篇）", ""];
      list.forEach(function (p, i) {
        var url = p.url || (p.doi ? "https://doi.org/" + p.doi : "");
        lines.push((i + 1) + ". **" + (p.title || "") + "**");
        lines.push("   - 作者：" + ((p.authors || []).join("、") || "未标注"));
        lines.push("   - 来源：" + (p.venue || "未标注") + "（" + (p.year || "n.d.") + "）");
        if (p.citations) lines.push("   - 被引：" + p.citations);
        if (p.topics && p.topics.length) {
          lines.push("   - 主题：" + p.topics.map(topicName).join("、"));
        }
        if (url) lines.push("   - 链接：" + url);
        lines.push("");
      });
      return { text: lines.join("\n"), count: list.length };
    }
    if (fmt === "csv") {
      var rows = [["标题", "作者", "来源", "年份", "被引", "主题", "DOI", "链接"].map(csvCell).join(",")];
      list.forEach(function (p) {
        rows.push([
          p.title, (p.authors || []).join("; "), p.venue, p.year, p.citations,
          (p.topics || []).map(topicName).join("; "), p.doi,
          p.url || (p.doi ? "https://doi.org/" + p.doi : "")
        ].map(csvCell).join(","));
      });
      return { text: "\ufeff" + rows.join("\n"), count: list.length };
    }
    // apa
    return {
      text: list.map(function (p, i) { return "[" + (i + 1) + "] " + apaText(p); }).join("\n"),
      count: list.length
    };
  }

  var lastFocused = null;

  function openDetail(paper) {
    var url = paper.url || (paper.doi ? "https://doi.org/" + paper.doi : "");
    var isFav = favSet.has(paper.uid);
    var isRead = readSet.has(paper.uid);
    var meta = [];
    meta.push('<span>' + esc(authorsText(paper)) + '</span>');
    if (paper.venue) meta.push('<span class="venue">' + esc(paper.venue) + '</span>');
    meta.push('<span>' + esc(fmtDate(paper.date)) + '</span>');
    if (paper.citations) meta.push('<span>被引 ' + paper.citations + '</span>');

    var links = [];
    if (url) links.push('<a class="btn primary" href="' + esc(url) + '" target="_blank" rel="noopener">打开原文 ↗</a>');
    if (paper.pdf_url) links.push('<a class="btn" href="' + esc(paper.pdf_url) + '" target="_blank" rel="noopener">打开 PDF ↗</a>');
    if (paper.doi) links.push('<button class="btn" type="button" data-detail-copy-doi>复制 DOI</button>');
    links.push('<button class="btn" type="button" data-detail-cite>复制引用</button>');
    links.push('<button class="btn" type="button" data-detail-bib>复制 BibTeX</button>');
    links.push('<button class="btn' + (isFav ? " primary" : "") + '" type="button" data-detail-fav>' +
      (isFav ? "已收藏" : "收藏") + '</button>');
    links.push('<button class="btn' + (isRead ? " primary" : "") + '" type="button" data-detail-read>' +
      (isRead ? "已读" : "标记已读") + '</button>');

    $("detailContent").innerHTML =
      '<h4 class="detail-paper-title">' + esc(paper.title || "未命名文献") + '</h4>' +
      '<div class="paper-meta detail-meta">' + meta.join("") + '</div>' +
      badgeHtml(paper) +
      '<div class="detail-abstract">' + esc(paper.abstract || "这篇文献暂时没有摘要，可以尝试打开原文查看详细信息。") + '</div>' +
      (paper.doi ? '<div class="detail-doi">DOI：' + esc(paper.doi) + '</div>' : "") +
      '<div class="detail-actions">' + links.join("") + '</div>' +
      '<p class="detail-hint">电脑上如果无法打开原文，通常是本机浏览器代理或 DOI 网络访问问题。站内详情、摘要和 DOI 仍可正常查看。</p>';

    var favButton = $("detailContent").querySelector("[data-detail-fav]");
    if (favButton) {
      favButton.addEventListener("click", function () {
        if (favSet.has(paper.uid)) { favSet.delete(paper.uid); toast("已取消收藏"); }
        else { favSet.add(paper.uid); toast("已加入收藏"); }
        saveSet(LS.fav, favSet);
        renderList();
        openDetail(paper);
      });
    }
    var readButton = $("detailContent").querySelector("[data-detail-read]");
    if (readButton) {
      readButton.addEventListener("click", function () {
        if (readSet.has(paper.uid)) { readSet.delete(paper.uid); toast("已标记为未读"); }
        else { readSet.add(paper.uid); toast("已标记为已读"); }
        saveSet(LS.read, readSet);
        renderList();
        openDetail(paper);
      });
    }
    var citeButton = $("detailContent").querySelector("[data-detail-cite]");
    if (citeButton) citeButton.addEventListener("click", function () { copyText(apaText(paper), "已复制参考文献"); });
    var bibButton = $("detailContent").querySelector("[data-detail-bib]");
    if (bibButton) bibButton.addEventListener("click", function () { copyText(bibtex(paper), "已复制 BibTeX"); });
    var doiButton = $("detailContent").querySelector("[data-detail-copy-doi]");
    if (doiButton) doiButton.addEventListener("click", function () { copyText(paper.doi || "", "已复制 DOI"); });

    lastFocused = document.activeElement;
    $("detailModal").hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(function () { $("closeDetail").focus(); }, 0);
  }

  function closeDetailModal() {
    if ($("detailModal").hidden) return;
    $("detailModal").hidden = true;
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function openExport() {
    refreshExport();
    lastFocused = document.activeElement;
    $("exportModal").hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(function () { $("closeExport").focus(); }, 0);
  }

  function closeExportModal() {
    if ($("exportModal").hidden) return;
    $("exportModal").hidden = true;
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  function refreshExport() {
    var res = buildExport(state.exportFmt);
    $("exportText").value = res.text;
    $("exportCount").textContent = res.count
      ? "已选 " + res.count + " 篇收藏文献，可直接复制或下载。"
      : "收藏夹为空。";
    Array.prototype.forEach.call(document.querySelectorAll("#exportModal [data-fmt]"), function (b) {
      var on = b.getAttribute("data-fmt") === state.exportFmt;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  var EXT = { bibtex: "bib", markdown: "md", csv: "csv", apa: "txt" };

  // ============================================================ 事件绑定

  function bindToolbar() {
    var input = $("searchInput");
    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = input.value;
        state.page = 1;
        $("clearSearch").hidden = !input.value;
        renderList();
      }, 180);
    });
    $("clearSearch").addEventListener("click", function () {
      input.value = "";
      state.q = "";
      $("clearSearch").hidden = true;
      state.page = 1;
      renderList();
    });

    $("sortSelect").addEventListener("change", function () {
      state.sort = this.value;
      state.page = 1;
      renderList();
    });

    Array.prototype.forEach.call($("rangeGroup").querySelectorAll(".chip"), function (b) {
      b.addEventListener("click", function () {
        state.days = Number(b.getAttribute("data-days"));
        state.page = 1;
        syncFilterChips();
        renderList();
      });
    });

    $("favFilter").addEventListener("click", function () {
      state.onlyFav = !state.onlyFav;
      state.page = 1; syncFilterChips(); renderList();
    });
    $("unreadFilter").addEventListener("click", function () {
      state.onlyUnread = !state.onlyUnread;
      state.page = 1; syncFilterChips(); renderList();
    });
    $("newFilter").addEventListener("click", function () {
      state.onlyNew = !state.onlyNew;
      state.page = 1; syncFilterChips(); renderList();
    });
    $("resetBtn").addEventListener("click", function () {
      state.q = ""; state.days = 0; state.topics.clear(); state.sources.clear();
      state.onlyFav = false; state.onlyUnread = false; state.onlyNew = false;
      state.page = 1;
      $("searchInput").value = "";
      $("clearSearch").hidden = true;
      Array.prototype.forEach.call(document.querySelectorAll("#sourceGroup .chip, #topicBar .topic-chip"), function (b) {
        b.classList.remove("active"); b.classList.remove("on");
        b.setAttribute("aria-pressed", "false");
      });
      syncFilterChips();
      renderList();
      toast("已重置筛选");
    });

    $("loadMoreBtn").addEventListener("click", function () {
      state.page += 1;
      renderList();
    });
  }

  function syncThemeButton() {
    var dark = document.documentElement.getAttribute("data-theme") === "dark";
    $("themeBtn").setAttribute("aria-label", dark ? "切换为浅色模式" : "切换为深色模式");
    $("themeBtn").title = dark ? "切换为浅色模式" : "切换为深色模式";
  }

  function bindGlobal() {
    $("themeBtn").addEventListener("click", function () {
      var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem(LS.theme, next); } catch (e) {}
      syncThemeButton();
      renderTrend();
    });

    $("exportBtn").addEventListener("click", openExport);
    $("closeExport").addEventListener("click", closeExportModal);
    $("exportModal").addEventListener("click", function (e) {
      if (e.target === $("exportModal")) closeExportModal();
    });
    $("closeDetail").addEventListener("click", closeDetailModal);
    $("detailModal").addEventListener("click", function (e) {
      if (e.target === $("detailModal")) closeDetailModal();
    });
    Array.prototype.forEach.call(document.querySelectorAll("#exportModal [data-fmt]"), function (b) {
      b.addEventListener("click", function () {
        state.exportFmt = b.getAttribute("data-fmt");
        refreshExport();
      });
    });
    $("copyExport").addEventListener("click", function () {
      copyText($("exportText").value, "已复制到剪贴板");
    });
    $("downloadExport").addEventListener("click", function () {
      var res = buildExport(state.exportFmt);
      if (!res.count) { toast("收藏夹为空"); return; }
      download("电力市场前沿_收藏." + EXT[state.exportFmt], res.text);
      toast("已开始下载");
    });

    document.addEventListener("keydown", function (e) {
      var detailOpen = !$("detailModal").hidden;
      var exportOpen = !$("exportModal").hidden;
      var modalOpen = detailOpen || exportOpen;
      var openModal = detailOpen ? $("detailModal") : $("exportModal");
      if (e.key === "Escape" && modalOpen) {
        if (detailOpen) closeDetailModal();
        else closeExportModal();
        return;
      }
      if (e.key === "Tab" && modalOpen) {
        var focusable = openModal.querySelectorAll(
          'button:not([disabled]), [href], textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (!focusable.length) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
      if (e.key === "/" && !modalOpen && document.activeElement !== $("searchInput")) {
        e.preventDefault();
        $("searchInput").focus();
      }
    });
  }

  // ============================================================ 启动

  function init() {
    try {
      var saved = localStorage.getItem(LS.theme);
      if (saved) document.documentElement.setAttribute("data-theme", saved);
    } catch (e) {}
    syncThemeButton();

    renderHeader();
    renderStats();
    renderSourceChips();
    renderTopicChips();
    syncFilterChips();
    renderList();
    renderHotspots();
    renderTrend();
    renderRising();
    renderCnLinks();
    renderSourceStats();
    bindToolbar();
    bindGlobal();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
