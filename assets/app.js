/* 电力市场研究前沿追踪 — 前端交互 */
(function () {
  "use strict";

  var REAL = window.__PM_DATA__ || null;
  var DEMO = window.__PM_DEMO__ || null;
  var usingDemo = !(REAL && REAL.papers && REAL.papers.length);
  var DATA = usingDemo ? (DEMO || {}) : (REAL || {});

  DATA.papers = DATA.papers || [];
  DATA.topics = DATA.topics || [];
  DATA.insights = DATA.insights || { hotspots: [], rising: [], summary: {} };
  DATA.meta = DATA.meta || {};

  var TOPIC_MAP = {};
  DATA.topics.forEach(function (t) { TOPIC_MAP[t.id] = t; });

  var VENUE_ZH = {
    "applied energy": "应用能源",
    "the energy journal": "能源期刊",
    "ieee transactions on power systems": "IEEE 电力系统汇刊",
    "energy policy": "能源政策",
    "nature energy": "自然·能源",
    "ieee transactions on smart grid": "IEEE 智能电网汇刊",
    "ieee transactions on energy markets, policy and regulation": "IEEE 能源市场、政策与监管汇刊",
    "ieee transactions on power delivery": "IEEE 电力输送汇刊",
    "ieee transactions on sustainable energy": "IEEE 可持续能源汇刊",
    "ieee transactions on industrial informatics": "IEEE 工业信息学汇刊",
    "energy": "能源",
    "renewable and sustainable energy reviews": "可再生与可持续能源评论",
    "joule": "焦耳",
    "energy economics": "能源经济学"
  };

  function hasChinese(s) {
    return /[\u4e00-\u9fff]/.test(String(s || ""));
  }

  function ensureTranslation(p) {
    if (!p) return p;
    if (!p.title_zh && hasChinese(p.title)) p.title_zh = p.title;
    if (!p.abstract_zh && hasChinese(p.abstract)) p.abstract_zh = p.abstract;
    if (!p.venue_zh) p.venue_zh = VENUE_ZH[String(p.venue || "").toLowerCase()] || "";
    if (!p.title_en) p.title_en = hasChinese(p.title) ? "" : (p.title || "");
    if (!p.abstract_en) p.abstract_en = hasChinese(p.abstract) ? "" : (p.abstract || "");
    return p;
  }

  DATA.papers = DATA.papers.map(ensureTranslation);

  // ---------------------------------------------------------------- 指标

  function num(v) {
    return typeof v === "number" && isFinite(v) ? v : null;
  }

  function tierOf(p) {
    return String(p.venue_tier || "").toUpperCase();
  }

  function tierText(p) {
    var t = tierOf(p);
    if (!t) return p.metrics_source ? "未收录" : "待补全";
    return p.venue_tier_label || TIER_TEXT[t] || t;
  }

  function norm01(values) {
    if (!values.length) return values;
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    if (hi - lo < 1e-9) return values.map(function () { return 0.5; });
    return values.map(function (v) { return (v - lo) / (hi - lo); });
  }

  function ensureHeat() {
    var missing = DATA.papers.some(function (p) { return num(p.heat) === null; });
    if (!missing || !DATA.papers.length) return;
    var velocity = [], cited = [], recency = [], venue = [];

    DATA.papers.forEach(function (p) {
      velocity.push(Math.log1p(Math.max(0, num(p.cite_per_year) || 0)));
      cited.push(Math.log1p(Math.max(0, num(p.citations) || 0)));
      var days = num(p.recency_days);
      if (days === null) days = daysSince(p.date);
      recency.push(Math.exp(-Math.min(Math.max(days, 0), 3650) / 180));
      venue.push(TIER_SCORE[tierOf(p)] || TIER_SCORE[""]);
    });

    var v = norm01(velocity);
    var c = norm01(cited);
    DATA.papers.forEach(function (p, i) {
      var score = 0.32 * v[i] + 0.22 * c[i] + 0.30 * recency[i] + 0.16 * venue[i];
      p.heat = Math.round(score * 1000) / 10;
    });
  }

  function heatOf(p) {
    var h = num(p.heat);
    return h === null ? 0 : h;
  }

  function citationsOf(p) { return Math.max(0, num(p.citations) || 0); }

  function refsOf(p) { return Math.max(0, num(p.reference_count) || 0); }

  function velocityOf(p) {
    if (num(p.cite_per_year) !== null) return p.cite_per_year;
    var age = Math.max(1, new Date().getFullYear() - (p.year || new Date().getFullYear()) + 1);
    return Math.round((citationsOf(p) / age) * 100) / 100;
  }

  function impactOf(p) { return num(p.venue_impact); }

  function fmtNum(v, digits) {
    var n = num(v);
    if (n === null) return "—";
    return digits ? n.toFixed(digits) : String(Math.round(n));
  }

  function tierBadge(p) {
    var tier = tierOf(p);
    if (!tier) return "";
    var hint = tierText(p) + (p.venue_tier_basis ? "（依据：" + p.venue_tier_basis + "）" : "");
    return '<span class="tier-badge ' + esc(tier.toLowerCase()) + '" title="' + esc(hint) + '">' +
      esc(tier) + " " + esc(tierText(p)) + "</span>";
  }

  function venueLine(p) {
    var name = displayVenue(p);
    var meta = [];
    if (impactOf(p) !== null) meta.push("影响 " + fmtNum(impactOf(p), 1));
    if (num(p.venue_h_index)) meta.push("h 指数 " + fmtNum(p.venue_h_index));
    return '<div class="card-venue">' +
      '<span class="venue-name" title="' + esc(name) + '">' + esc(name) + "</span>" +
      tierBadge(p) +
      (meta.length ? '<span class="venue-meta">' + esc(meta.join(" · ")) + "</span>" : "") +
      "</div>";
  }

  function metricsRow(p) {
    return '<div class="card-metrics">' +
      '<span class="metric-chip"><b>' + fmtNum(velocityOf(p), 1) + "</b>引用/年</span>" +
      '<span class="metric-chip"><b>' + fmtNum(refsOf(p)) + "</b>参考文献</span>" +
      '<span class="metric-chip"><b>' + fmtNum(heatOf(p), 1) + "</b>热度</span>" +
      "</div>";
  }

  function citationText(p) {
    var authors = (p.authors || []).slice(0, 3).join(", ");
    if ((p.authors || []).length > 3) authors += ", et al.";
    var kind = String(p.type || "").indexOf("preprint") >= 0 ? "[EB/OL]" : "[J]";
    var authorPart = (authors || "佚名").replace(/[.\s]+$/, "") + ".";
    var parts = [
      authorPart + " " + (p.title || "未命名文献") + kind + ". " +
      (p.venue || "未标注来源"),
    ];
    if (p.year) parts.push(String(p.year) + ".");
    if (p.doi) parts.push("DOI: " + p.doi + ".");
    else if (p.url) parts.push(p.url);
    return parts.join(" ");
  }

  var LS = {
    fav: "pmr.fav",
    read: "pmr.read",
    lang: "pmr.lang"
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

  // 期刊层级：文案与热度权重（与 crawler/analyze.py 保持一致）
  var TIER_TEXT = {
    T1: "顶级期刊",
    T2: "权威期刊",
    T3: "核心期刊",
    T4: "一般期刊",
    T5: "新兴期刊",
    PRE: "预印本"
  };

  var TIER_SCORE = { T1: 1, T2: 0.82, T3: 0.62, T4: 0.44, T5: 0.3, PRE: 0.34, "": 0.15 };

  // 不同板块各自记住自己的排序方式
  var state = {
    q: "",
    tab: "all",
    sort: "newest",
    sortByTab: {},
    featuredSort: "heat",
    topicSort: "score",
    sourceSort: "count",
    page: 1,
    selectedTopic: null,
    lang: "zh"
  };

  var PAGE_SIZE = 10;

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
    var m = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return "日期未知";
    return m[1] + "年" + parseInt(m[2], 10) + "月";
  }

  function topicName(id) {
    var t = TOPIC_MAP[id];
    return t ? t.zh : id;
  }

  function displayTitle(p) {
    if (state.lang === "zh") return p.title_zh || p.title || "未命名文献";
    return p.title_en || p.title || "未命名文献";
  }

  function displayAbstract(p) {
    if (state.lang === "zh") return p.abstract_zh || p.abstract || "暂无摘要";
    return p.abstract_en || p.abstract || "暂无摘要";
  }

  function displayVenue(p) {
    if (state.lang === "zh") return p.venue_zh || p.venue || (p.source_name || p.source || "未标注来源");
    return p.venue || (p.source_name || p.source || "未标注来源");
  }

  function hasAutoTranslation(p) {
    return Boolean(
      (state.lang === "zh" && p.title_zh && p.title_zh !== p.title) ||
      (state.lang === "zh" && p.abstract_zh && p.abstract_zh !== p.abstract) ||
      (state.lang === "zh" && p.venue_zh && p.venue_zh !== p.venue)
    );
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

  function filtered() {
    var q = state.q.trim().toLowerCase();
    var days = state.tab === "7" ? 7 : (state.tab === "30" ? 30 : 0);
    var out = DATA.papers.filter(function (p) {
      if (days && daysSince(p.date) > days) return false;
      if (state.tab === "fav" && !favSet.has(p.uid)) return false;
      if (state.tab === "unread" && readSet.has(p.uid)) return false;
      if (state.tab === "new" && !p.is_new) return false;
      if (state.selectedTopic && !(p.topics || []).includes(state.selectedTopic)) return false;
      if (q && paperText(p).indexOf(q) < 0) return false;
      return true;
    });

    out.sort(comparePapers(state.sort));
    return out;
  }

  // 各板块共用的排序规则：热度 / 被引数 / 引用速度 / 期刊层级 / 时间……
  function comparePapers(mode) {
    return function (a, b) {
      var newest = String(b.date || "").localeCompare(String(a.date || ""));
      if (mode === "oldest") return -newest || citationsOf(b) - citationsOf(a);
      if (mode === "heat") return heatOf(b) - heatOf(a) || newest;
      if (mode === "cited") return citationsOf(b) - citationsOf(a) || newest;
      if (mode === "velocity") return velocityOf(b) - velocityOf(a) || newest;
      if (mode === "reference") return refsOf(b) - refsOf(a) || newest;
      if (mode === "impact") {
        return (impactOf(b) || -1) - (impactOf(a) || -1) || newest;
      }
      if (mode === "venue") {
        return (TIER_SCORE[tierOf(b)] || 0) - (TIER_SCORE[tierOf(a)] || 0) ||
          (impactOf(b) || 0) - (impactOf(a) || 0) || newest;
      }
      return newest || citationsOf(b) - citationsOf(a);
    };
  }

  function renderHeader() {
    var m = DATA.meta || {};
    $("updateLabel").textContent = m.updated_at ? "更新于 " + m.updated_at : "尚未抓取真实数据";
    $("heroSub").textContent = usingDemo
      ? "当前展示演示数据，仅用于预览界面；抓取真实文献后会自动切换。"
      : "每日自动追踪电力市场研究热点、重点期刊与新增文献。";
  }

  function renderMetrics() {
    var m = DATA.meta || {};
    var ins = DATA.insights.summary || {};
    var total = m.total || DATA.papers.length || 0;
    var recent = m.recent30 || ins.recent30 || 0;
    var topics = (DATA.insights.hotspots || []).length || DATA.topics.length || 0;
    var oa = m.oa || ins.oa || 0;

    $("metrics").innerHTML =
      '<div class="metric"><div class="metric-value">' + total + '<small>篇</small></div><div class="metric-label">已收录文献</div></div>' +
      '<div class="metric"><div class="metric-value">' + recent + '<small>篇</small></div><div class="metric-label">近 30 天新增</div></div>' +
      '<div class="metric"><div class="metric-value">' + oa + '<small>篇</small></div><div class="metric-label">开放获取</div></div>' +
      '<div class="metric"><div class="metric-value">' + topics + '<small>个</small></div><div class="metric-label">覆盖主题</div></div>';

    var note = $("metricsNote");
    if (note) {
      var mc = m.metrics || {};
      note.textContent = mc.with_citations
        ? "被引数与期刊层级已覆盖 " + mc.with_citations + "/" + (mc.total || total) +
          " 篇（数据源 " + (mc.source || "OpenAlex") +
          (mc.updated_at ? "，更新于 " + mc.updated_at : "") + "）"
        : "被引数与期刊层级尚未补全：运行一次「一键更新」即可自动回查。";
    }
  }

  function renderQuickTopics() {
    var counts = {};
    DATA.papers.forEach(function (p) {
      (p.topics || []).forEach(function (t) { counts[t] = (counts[t] || 0) + 1; });
    });

    var list = DATA.topics.slice().sort(function (a, b) {
      return (counts[b.id] || 0) - (counts[a.id] || 0);
    }).slice(0, 8);

    $("quickTopics").innerHTML = list.map(function (t) {
      return '<button class="topic-pill' + (state.selectedTopic === t.id ? " active" : "") + '" type="button" data-topic="' + esc(t.id) + '">' +
        esc(t.zh) + ' <span class="muted">' + (counts[t.id] || 0) + '</span></button>';
    }).join("");

    Array.prototype.forEach.call($("quickTopics").querySelectorAll("[data-topic]"), function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-topic");
        state.selectedTopic = state.selectedTopic === id ? null : id;
        state.tab = "all";
        state.page = 1;
        syncTabs();
        renderQuickTopics();
        renderResults();
      });
    });
  }

  function syncTabs() {
    Array.prototype.forEach.call(document.querySelectorAll("#tabs .tab"), function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === state.tab);
    });
    $("results").scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function renderFeatured() {
    var pool = filtered();
    if (!pool.length) pool = DATA.papers.slice();
    var paper = pool.slice().sort(comparePapers(state.featuredSort))[0];
    var box = $("featuredCard");
    if (!paper) {
      box.innerHTML = '<div class="featured-label">Featured Research</div><p class="muted" style="margin-top:26px">暂无重点文献</p>';
      return;
    }

    var primaryTopic = paper.topic_primary || (paper.topics || [])[0] || "";
    var topic = topicName(primaryTopic) || "重点研究";
    var authors = (paper.authors || []).slice(0, 3).join("、");
    if ((paper.authors || []).length > 3) authors += " 等";
    var url = paper.url || (paper.doi ? "https://doi.org/" + paper.doi : "");

    box.innerHTML =
      '<div class="featured-label">Featured Research</div>' +
      '<h3 class="featured-title">' + esc(displayTitle(paper)) + '</h3>' +
      '<div class="featured-meta">' +
        '<span>' + esc(topic) + '</span>' +
        '<span>' + esc(authors || "作者未标注") + '</span>' +
        '<span>' + esc(fmtDate(paper.date)) + '</span>' +
        '<span>热度 ' + fmtNum(heatOf(paper), 1) + '</span>' +
      '</div>' +
      venueLine(paper) +
      '<p class="featured-abstract">' + esc(displayAbstract(paper)) + '</p>' +
      '<div class="featured-stats">' +
        '<div class="featured-stat"><b>' + fmtNum(citationsOf(paper)) + '</b><span>被引数</span></div>' +
        '<div class="featured-stat"><b>' + fmtNum(velocityOf(paper), 1) + '</b><span>引用/年</span></div>' +
        '<div class="featured-stat"><b>' + fmtNum(refsOf(paper)) + '</b><span>参考文献</span></div>' +
        '<div class="featured-stat"><b>' + esc(tierOf(paper) || "—") + '</b><span>' + esc(tierText(paper)) + '</span></div>' +
      '</div>' +
      '<div class="featured-actions">' +
        '<button class="pill-btn primary" type="button" data-featured-action="detail" data-uid="' + esc(paper.uid) + '">阅读详情</button>' +
        (url ? '<a class="outline-btn" href="' + esc(url) + '" target="_blank" rel="noopener">打开原文</a>' : '') +
      '</div>';

    Array.prototype.forEach.call(box.querySelectorAll("[data-featured-action]"), function (btn) {
      btn.addEventListener("click", function () {
        var uid = btn.getAttribute("data-uid");
        var p = DATA.papers.filter(function (x) { return x.uid === uid; })[0];
        if (p) openDetail(p);
      });
    });
  }

  function badgeHtml(p) {
    var tags = [];
    (p.topics || []).slice(0, 3).forEach(function (t) {
      tags.push('<span class="tag">' + esc(topicName(t)) + '</span>');
    });
    if (p.is_new) tags.push('<span class="tag new">今日新增</span>');
    if (p.is_oa) tags.push('<span class="tag oa">开放获取</span>');
    return tags.join("");
  }

  function renderResults() {
    var rows = filtered();
    var shown = rows.slice(0, state.page * PAGE_SIZE);

    $("resultCount").innerHTML = rows.length
      ? "找到 <strong>" + rows.length + "</strong> 篇文献"
      : "没有符合条件的文献";

    var box = $("results");
    if (!rows.length) {
      box.innerHTML = '<div class="muted" style="padding:50px 0;text-align:center">试试放宽时间范围，或清空搜索条件。</div>';
    } else {
      box.innerHTML = shown.map(function (p) {
        var isFav = favSet.has(p.uid);
        var isRead = readSet.has(p.uid);
        var primaryTopic = p.topic_primary || (p.topics || [])[0] || "";
        var topic = topicName(primaryTopic) || "电力市场研究";
        var url = p.url || (p.doi ? "https://doi.org/" + p.doi : "");
        var authors = (p.authors || []).slice(0, 3).join("、");
        if ((p.authors || []).length > 3) authors += " 等";
        var date = fmtDate(p.date);

        var actions = [];
        actions.push('<button class="text-action' + (isFav ? " on" : "") + '" type="button" data-action="fav" data-uid="' + esc(p.uid) + '">' + (isFav ? "已收藏" : "收藏") + '</button>');
        actions.push('<button class="text-action' + (isRead ? " read-on" : "") + '" type="button" data-action="read" data-uid="' + esc(p.uid) + '">' + (isRead ? "已读" : "标记已读") + '</button>');
        actions.push('<button class="text-action" type="button" data-action="detail" data-uid="' + esc(p.uid) + '">详情</button>');
        if (url) actions.push('<a class="text-action" href="' + esc(url) + '" target="_blank" rel="noopener">打开原文</a>');

        var tags = badgeHtml(p);
        if (hasAutoTranslation(p)) tags += '<span class="tag translated">已译</span>';

        return '<article class="paper-card" data-uid="' + esc(p.uid) + '">' +
          '<div class="paper-card-top">' +
            '<span class="card-kicker">' + esc(topic) + '</span>' +
            '<span class="card-cites">被引 <b>' + fmtNum(citationsOf(p)) + '</b></span>' +
          '</div>' +
          '<button class="card-title" type="button" data-action="detail" data-uid="' + esc(p.uid) + '">' + esc(displayTitle(p)) + '</button>' +
          venueLine(p) +
          '<div class="card-meta">' + esc(authors || "作者未标注") + ' · ' + esc(date) + '</div>' +
          '<p class="card-abstract">' + esc(displayAbstract(p)) + '</p>' +
          metricsRow(p) +
          '<div class="card-tags">' + tags + '</div>' +
          '<div class="card-actions">' + actions.join("") + '</div>' +
        '</article>';
      }).join("");
    }

    $("loadMore").hidden = shown.length >= rows.length;
    $("loadMore").textContent = rows.length > shown.length
      ? "加载更多（还有 " + (rows.length - shown.length) + " 篇）"
      : "";

    renderFeatured();
    bindResultEvents();
  }

  function bindResultEvents() {
    Array.prototype.forEach.call($("results").querySelectorAll("[data-action]"), function (el) {
      el.addEventListener("click", function () {
        var uid = el.getAttribute("data-uid");
        var paper = DATA.papers.filter(function (p) { return p.uid === uid; })[0];
        if (!paper) return;
        var action = el.getAttribute("data-action");

        if (action === "fav") {
          if (favSet.has(uid)) { favSet.delete(uid); toast("已取消收藏"); }
          else { favSet.add(uid); toast("已加入收藏"); }
          saveSet(LS.fav, favSet);
          renderResults();
        } else if (action === "read") {
          if (readSet.has(uid)) { readSet.delete(uid); toast("已标记为未读"); }
          else { readSet.add(uid); toast("已标记为已读"); }
          saveSet(LS.read, readSet);
          renderResults();
        } else if (action === "detail") {
          openDetail(paper);
        }
      });
    });
  }

  function renderInsights() {
    renderHotTopics();

    var rising = DATA.insights.rising || [];
    if (rising.length) {
      var maxWeight = Math.max.apply(null, rising.map(function (r) { return r.weight || 0; }).concat([1]));
      $("risingKeywords").innerHTML = rising.slice(0, 24).map(function (r) {
        var size = 12 + Math.round(((r.weight || 0) / maxWeight) * 8);
        return '<span class="' + (r.is_new ? "fresh" : "") + '" style="font-size:' + size + 'px">' + esc(r.term) + '</span>';
      }).join("");
    } else {
      $("risingKeywords").innerHTML = '<span>现货市场</span><span>市场出清</span><span>节点电价</span><span>碳市场</span><span>储能套利</span><span>容量市场</span>';
    }

    renderSourceStats();
  }

  // 热点主题板块：可以按热度分、论文总数、近 30 天新增等排序
  function hotspotValue(h) {
    var mode = state.topicSort;
    if (mode === "total") return h.total || 0;
    if (mode === "recent30") return h.recent30 || 0;
    if (mode === "impact") return h.impact || 0;
    if (mode === "top_venue_ratio") return Math.round((h.top_venue_ratio || 0) * 100);
    return h.score || 0;
  }

  function renderHotTopics() {
    var hot = (DATA.insights.hotspots || []).slice();
    if (!hot.length) {
      $("hotTopics").innerHTML = '<p class="muted">暂无热点主题</p>';
      return;
    }
    hot.sort(function (a, b) { return hotspotValue(b) - hotspotValue(a); });
    hot = hot.slice(0, 8);
    var max = Math.max.apply(null, hot.map(hotspotValue).concat([1]));

    $("hotTopics").innerHTML = hot.map(function (h) {
      var value = hotspotValue(h);
      var w = Math.round((value / max) * 100);
      return '<div class="topic-line" title="' + esc(
        h.zh + "：热度 " + (h.score || 0) + " · 共 " + (h.total || 0) + " 篇 · 近30天 " +
        (h.recent30 || 0) + " 篇 · 平均引用速度 " + (h.impact || 0)
      ) + '">' +
        '<span class="topic-name">' + esc(h.zh) + '</span>' +
        '<span class="topic-bar"><i style="width:' + w + '%"></i></span>' +
        '<span class="topic-score">' + value + '</span>' +
      '</div>';
    }).join("");
  }

  // 来源分布板块：可以按论文数、平均被引、近 30 天新增排序
  function collectSourceStats() {
    var map = {};
    DATA.papers.forEach(function (p) {
      var name = p.source_name || p.source || "未知";
      var item = map[name];
      if (!item) {
        item = map[name] = { name: name, count: 0, cited: 0, recent: 0 };
      }
      item.count += 1;
      item.cited += citationsOf(p);
      if (daysSince(p.date) <= 30) item.recent += 1;
    });
    return Object.keys(map).map(function (k) {
      var item = map[k];
      item.avg = item.count ? item.cited / item.count : 0;
      return item;
    });
  }

  function renderSourceStats() {
    var list = collectSourceStats();
    if (!list.length) {
      $("sourceStats").innerHTML = '<p class="muted">暂无来源数据</p>';
      return;
    }
    var mode = state.sourceSort;
    list.sort(function (a, b) {
      if (mode === "cited") return b.avg - a.avg || b.count - a.count;
      if (mode === "recent") return b.recent - a.recent || b.count - a.count;
      if (mode === "name") return a.name.localeCompare(b.name, "zh-Hans-CN");
      return b.count - a.count || a.name.localeCompare(b.name, "zh-Hans-CN");
    });
    var top = list.slice(0, 8);
    var max = Math.max.apply(null, top.map(function (s) { return s.count; }).concat([1]));

    $("sourceStats").innerHTML = top.map(function (s) {
      var hint = s.name + "：共 " + s.count + " 篇 · 平均被引 " + s.avg.toFixed(1) +
        " · 近30天 " + s.recent + " 篇";
      return '<div class="source-line" title="' + esc(hint) + '">' +
        '<span class="source-name">' + esc(s.name) + '</span>' +
        '<span class="source-bar"><i style="width:' + Math.round(s.count / max * 100) + '%"></i></span>' +
        '<span class="source-num">' + s.count + '</span>' +
      '</div>';
    }).join("");
  }

  // 详情面板里的指标表：被引、引用速度、参考文献、期刊名称与层级
  function detailMetricsHtml(paper) {
    var rows = [
      ["被引数", citationsOf(paper) ? fmtNum(citationsOf(paper)) + " 次" : "0 次"],
      ["引用速度", fmtNum(velocityOf(paper), 1) + " 次/年"],
      ["参考文献", refsOf(paper) ? fmtNum(refsOf(paper)) + " 篇" : "—"],
      ["综合热度", fmtNum(heatOf(paper), 1) + " 分"],
      ["期刊名称", displayVenue(paper)],
      ["期刊层级", tierOf(paper) ? tierOf(paper) + " " + tierText(paper) : tierText(paper)]
    ];
    if (impactOf(paper) !== null) rows.push(["期刊影响", fmtNum(impactOf(paper), 2) + "（2年均被引）"]);
    if (num(paper.venue_h_index)) rows.push(["期刊 h 指数", fmtNum(paper.venue_h_index)]);
    if (paper.venue_publisher) rows.push(["出版商", paper.venue_publisher]);
    if (paper.metrics_updated) rows.push(["指标更新", paper.metrics_updated]);

    var body = rows.map(function (row) {
      return '<div class="detail-metric"><span>' + esc(row[0]) + "</span><b>" +
        esc(row[1]) + "</b></div>";
    }).join("");

    var note = paper.metrics_source
      ? "指标来源：" + esc(paper.metrics_source) + (paper.venue_tier_basis ? "（层级依据：" + esc(paper.venue_tier_basis) + "）" : "")
      : "这篇文献暂未回查到引用与期刊指标，可用「一键更新」重新补全。";
    return '<div class="detail-metrics-grid">' + body + '</div>' +
      '<p class="detail-note">' + note + "</p>";
  }

  // 引用信息：给出可直接粘贴的引用格式
  function detailCiteHtml(paper) {
    var text = citationText(paper);
    return "<span class=\"cite-label\">引用格式</span>" +
      '<code class="cite-text">' + esc(text) + "</code>" +
      '<button class="text-action" type="button" data-cite-action="copy">复制引用</button>';
  }

  function copyText(text) {
    function fallback() {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "readonly");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(area);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast("引用格式已复制");
      }, function () {
        fallback();
        toast("引用格式已复制");
      });
      return;
    }
    fallback();
    toast("引用格式已复制");
  }

  function openDetail(paper) {
    $("detailTitle").textContent = displayTitle(paper);
    var meta = [];
    meta.push((paper.authors || []).join("、") || "作者未标注");
    if (paper.venue) meta.push("期刊：" + displayVenue(paper));
    meta.push(fmtDate(paper.date));
    $("detailMeta").textContent = meta.join(" · ");
    $("detailAbstract").textContent = displayAbstract(paper);
    $("detailMetrics").innerHTML = detailMetricsHtml(paper);
    $("detailCite").innerHTML = detailCiteHtml(paper);

    var copyBtn = $("detailCite").querySelector("[data-cite-action='copy']");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        copyText(citationText(paper));
      });
    }

    var isFav = favSet.has(paper.uid);
    var isRead = readSet.has(paper.uid);
    var url = paper.url || (paper.doi ? "https://doi.org/" + paper.doi : "");
    var html = '';
    html += '<button class="pill-btn primary" type="button" data-detail-action="fav" data-uid="' + esc(paper.uid) + '">' + (isFav ? "已收藏" : "收藏") + '</button>';
    html += '<button class="outline-btn" type="button" data-detail-action="read" data-uid="' + esc(paper.uid) + '">' + (isRead ? "已读" : "标记已读") + '</button>';
    if (url) html += '<a class="outline-btn" href="' + esc(url) + '" target="_blank" rel="noopener">打开原文</a>';
    $("detailActions").innerHTML = html;

    Array.prototype.forEach.call($("detailActions").querySelectorAll("[data-detail-action]"), function (btn) {
      btn.addEventListener("click", function () {
        var action = btn.getAttribute("data-detail-action");
        if (action === "fav") {
          if (favSet.has(paper.uid)) { favSet.delete(paper.uid); toast("已取消收藏"); }
          else { favSet.add(paper.uid); toast("已加入收藏"); }
          saveSet(LS.fav, favSet);
          renderResults();
          openDetail(paper);
        } else if (action === "read") {
          if (readSet.has(paper.uid)) { readSet.delete(paper.uid); toast("已标记为未读"); }
          else { readSet.add(paper.uid); toast("已标记为已读"); }
          saveSet(LS.read, readSet);
          renderResults();
          openDetail(paper);
        }
      });
    });

    $("detailModal").hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(function () { $("closeDetail").focus(); }, 0);
  }

  function closeDetail() {
    if ($("detailModal").hidden) return;
    $("detailModal").hidden = true;
    document.body.style.overflow = "";
  }

  var toastTimer = null;
  function toast(msg) {
    var el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 2200);
  }

  function syncLangButtons() {
    Array.prototype.forEach.call(document.querySelectorAll(".lang-btn"), function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-lang") === state.lang);
    });
  }

  function download(filename, text) {
    var blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  function bindEvents() {
    var input = $("searchInput");
    var timer = null;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = input.value;
        state.page = 1;
        $("clearSearch").hidden = !input.value;
        renderResults();
      }, 160);
    });

    $("clearSearch").addEventListener("click", function () {
      input.value = "";
      state.q = "";
      state.page = 1;
      $("clearSearch").hidden = true;
      renderResults();
    });

    $("sortSelect").addEventListener("change", function () {
      state.sort = this.value;
      state.sortByTab[state.tab] = state.sort;
      state.page = 1;
      renderResults();
    });

    // 头条板块：自己带一个排序选项
    $("featuredSort").addEventListener("change", function () {
      state.featuredSort = this.value;
      renderFeatured();
    });

    // 研究洞察里的热点主题 / 来源分布：各自独立排序
    $("topicSort").addEventListener("change", function () {
      state.topicSort = this.value;
      renderHotTopics();
    });

    $("sourceSort").addEventListener("change", function () {
      state.sourceSort = this.value;
      renderSourceStats();
    });

    Array.prototype.forEach.call(document.querySelectorAll(".lang-btn"), function (btn) {
      btn.addEventListener("click", function () {
        state.lang = btn.getAttribute("data-lang");
        try { localStorage.setItem(LS.lang, state.lang); } catch (e) {}
        syncLangButtons();
        renderResults();
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll("#tabs .tab"), function (btn) {
      btn.addEventListener("click", function () {
        state.tab = btn.getAttribute("data-tab");
        state.page = 1;
        state.selectedTopic = null;
        // 每个标签页记住自己的排序方式
        state.sort = state.sortByTab[state.tab] || state.sort;
        state.sortByTab[state.tab] = state.sort;
        $("sortSelect").value = state.sort;
        syncTabs();
        renderQuickTopics();
        renderResults();
      });
    });

    document.querySelector('[data-action="show-fav"]').addEventListener("click", function (e) {
      e.preventDefault();
      state.tab = "fav";
      state.page = 1;
      state.selectedTopic = null;
      state.sort = state.sortByTab.fav || state.sort;
      state.sortByTab.fav = state.sort;
      $("sortSelect").value = state.sort;
      syncTabs();
      renderQuickTopics();
      renderResults();
    });

    $("loadMore").addEventListener("click", function () {
      state.page += 1;
      renderResults();
    });

    $("exportBtn").addEventListener("click", function () {
      var list = DATA.papers.filter(function (p) { return favSet.has(p.uid); });
      if (!list.length) { toast("收藏夹为空"); return; }
      var text = list.map(function (p, i) {
        return (i + 1) + ". " + displayTitle(p) + " — " + ((p.authors || []).join(", ") || "作者未标注") +
          " (" + (p.year || "n.d.") + ")" + (p.doi ? " https://doi.org/" + p.doi : "");
      }).join("\n");
      download("电力市场前沿_收藏.txt", text);
      toast("已开始下载");
    });

    $("closeDetail").addEventListener("click", closeDetail);
    $("detailModal").addEventListener("click", function (e) {
      if (e.target === $("detailModal")) closeDetail();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !$("detailModal").hidden) closeDetail();
      if (e.key === "/" && $("detailModal").hidden && document.activeElement !== $("searchInput")) {
        e.preventDefault();
        $("searchInput").focus();
      }
    });
  }

  function init() {
    try {
      var savedLang = localStorage.getItem(LS.lang);
      if (savedLang === "en" || savedLang === "zh") state.lang = savedLang;
    } catch (e) {}

    ensureHeat();
    renderHeader();
    renderMetrics();
    renderQuickTopics();
    syncLangButtons();
    renderResults();
    renderInsights();
    bindEvents();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
