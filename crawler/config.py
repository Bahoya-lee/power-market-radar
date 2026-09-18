# -*- coding: utf-8 -*-
"""
全局配置：主题词库、数据源、重点期刊、停用词。

主题词库是本项目的"靶心"：爬虫按 topic.queries 去各大学术数据源检索，
再按 topic.keywords 给命中的文献打标签，最后据此统计热点与趋势。
想扩展研究范围，只需要往 TOPICS 里加一条。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 基本设置

# 学术 API 的礼貌标识（OpenAlex / Crossref 建议带上联系方式）
MAILTO = "power.market.radar@example.com"
USER_AGENT = (
    "PowerMarketResearchRadar/1.0 (academic literature tracker; "
    f"mailto:{MAILTO})"
)

# 网络参数
HTTP_TIMEOUT = 30          # 单次请求超时（秒）
HTTP_RETRIES = 3           # 失败重试次数
HTTP_BACKOFF = 2.5         # 重试退避基数（秒）
REQUEST_INTERVAL = 1.2     # 同一数据源两次请求之间的间隔（秒），避免触发限流

# 各数据源各自的超时与重试：arXiv 在国内经常被重置，所以等得更短、更早放弃；
# 其余源也不让单次请求拖太久，避免代理异常时整轮更新被一两个请求卡死。
SOURCE_TIMEOUTS = {
    "openalex": 25,
    "arxiv": 12,
    "crossref": 25,
    "semanticscholar": 20,
}
SOURCE_RETRIES = {
    "openalex": 2,
    "arxiv": 1,
    "crossref": 2,
    "semanticscholar": 2,
}

# 单次更新的时间预算（分钟）。到点就停止抓取、用已经拿到的数据建站，
# 保证"一键更新"和每日任务不会因为网络异常跑上几个小时。
# 需要不限时（例如首次全量抓取）时用 --max-minutes 0。
MAX_UPDATE_MINUTES = 25
# 连接池：复用 TCP/TLS 连接，走代理时能省掉大量握手时间。
HTTP_POOL_SIZE = 8

# 并发抓取：主题级和单个主题内的数据源级并行度。
# 过大会触发 OpenAlex / Crossref 限流，过小又拖慢整次更新。
MAX_TOPIC_WORKERS = 4
MAX_SOURCE_WORKERS = 3

# arXiv 直连在国内网络下经常被重置，这里缩短等待并快速切换到 OpenAlex 预印本兜底。
ARXIV_TIMEOUT = 12
ARXIV_RETRIES = 1

# 某个数据源连续失败多少个主题后暂时跳过。
# 这样 arXiv 等站点被网络环境阻断时，不会让整次更新久等。
SOURCE_FAILURE_LIMIT = 2

# 抓取规模
RECENT_DAYS = 540          # 常规抓取回看的发表时间窗口（天）
CLASSIC_YEARS = 6          # "高被引经典" 的回看年数
PER_TOPIC_RECENT = 40      # 每个主题抓多少条最新文献
PER_TOPIC_CLASSIC = 15     # 每个主题抓多少条高被引文献
PER_TOPIC_PREPRINTS = 15   # 每个主题从 OpenAlex 补充多少条预印本

# 建站数据上限
MAX_PAPERS_IN_SITE = 2000  # 站点最多展示多少篇（按时间倒序保留）
ABSTRACT_KEEP = 1400       # 摘要截断长度（字符）

# 指标补全（被引数 / 参考文献数 / 期刊层级）
# OpenAlex 之外的源（Crossref、arXiv）拿不到被引数，更拿不到期刊层级，
# 这里统一按 DOI（无 DOI 时按标题）回查 OpenAlex 补齐，并把结果缓存到本地，
# 日常增量更新只回查新入库或超期未更新的文献。
METRICS_ENABLED = True
METRICS_BATCH = 40          # 一次请求最多回查多少个 DOI（OpenAlex 上限 50）
METRICS_CACHE = "data/metrics_cache.json"
METRICS_REFRESH_DAYS = 7    # 缓存多久之后重新回查一次被引数
METRICS_TITLE_LOOKUPS = 300 # 单次更新最多用标题检索补全多少篇（无 DOI 的预印本）
METRICS_WORKERS = 3         # 指标回查的并发请求数（网络抖动时靠并发保吞吐）

# 数据源开关
SOURCES = {
    "openalex": True,          # 综合覆盖最广，无需 Key，作为主源
    "arxiv": True,             # 预印本，最快反映前沿动向
    "crossref": True,          # 期刊元数据补充
    "semanticscholar": False,  # 需要 Key 或严格限流，默认关闭
}

SOURCE_LABELS = {
    "openalex": "OpenAlex",
    "arxiv": "arXiv",
    "crossref": "Crossref",
    "semanticscholar": "Semantic Scholar",
}

# ---------------------------------------------------------------- 主题词库

TOPICS = [
    {
        "id": "spot_market",
        "zh": "电力现货市场",
        "color": "#4da3ff",
        "queries": [
            "electricity spot market",
            "electricity market clearing",
            "day-ahead electricity market",
            "real-time electricity market",
            "locational marginal price",
        ],
        "keywords": [
            "spot market", "day-ahead market", "day ahead market", "real-time market",
            "market clearing", "clearing price", "locational marginal price", "lmp",
            "unit commitment", "economic dispatch", "现货市场", "市场出清",
        ],
    },
    {
        "id": "price_forecast",
        "zh": "电价预测与价格形成",
        "color": "#22c55e",
        "queries": [
            "electricity price forecasting",
            "electricity price prediction",
            "electricity price spike",
            "probabilistic electricity price forecast",
        ],
        "keywords": [
            "price forecast", "price prediction", "price spike", "electricity price",
            "price volatility", "电价预测", "价格预测",
        ],
    },
    {
        "id": "demand_response",
        "zh": "需求响应与负荷灵活性",
        "color": "#f59e0b",
        "queries": [
            "demand response electricity market",
            "demand side management power system",
            "flexibility market electricity",
            "industrial demand response",
        ],
        "keywords": [
            "demand response", "demand-side management", "demand side management",
            "load flexibility", "flexibility market", "flexibility", "需求响应", "负荷灵活性",
        ],
    },
    {
        "id": "ancillary",
        "zh": "辅助服务与调频市场",
        "color": "#a78bfa",
        "queries": [
            "ancillary service market",
            "frequency regulation market",
            "operating reserve market",
            "flexibility procurement power system",
        ],
        "keywords": [
            "ancillary service", "frequency regulation", "frequency containment",
            "reserve market", "operating reserve", "调频", "辅助服务",
        ],
    },
    {
        "id": "capacity",
        "zh": "容量市场与充裕性定价",
        "color": "#38bdf8",
        "queries": [
            "capacity market electricity",
            "capacity remuneration mechanism",
            "resource adequacy power system",
            "reliability pricing electricity",
        ],
        "keywords": [
            "capacity market", "capacity remuneration", "resource adequacy",
            "reliability pricing", "adequacy", "容量市场", "充裕性",
        ],
    },
    {
        "id": "carbon",
        "zh": "碳市场与电碳耦合",
        "color": "#34d399",
        "queries": [
            "carbon emission trading electricity market",
            "electricity and carbon market coupling",
            "carbon price power sector",
            "green certificate trading renewable",
        ],
        "keywords": [
            "carbon market", "carbon emission trading", "carbon price", "carbon emission",
            "green certificate", "renewable portfolio", "电碳", "碳市场", "绿证",
        ],
    },
    {
        "id": "renewable",
        "zh": "高比例可再生能源并网与消纳",
        "color": "#facc15",
        "queries": [
            "renewable energy integration electricity market",
            "variable renewable energy market design",
            "renewable curtailment power system",
            "high penetration renewable power market",
        ],
        "keywords": [
            "renewable integration", "variable renewable", "curtailment",
            "high penetration", "wind power market", "solar power market",
            "可再生能源", "消纳",
        ],
    },
    {
        "id": "vpp",
        "zh": "虚拟电厂与聚合商",
        "color": "#fb7185",
        "queries": [
            "virtual power plant",
            "aggregator electricity market",
            "distributed energy resource aggregation",
            "load aggregator market participation",
        ],
        "keywords": [
            "virtual power plant", "aggregator", "aggregation", "vpp",
            "virtual power", "虚拟电厂", "聚合商",
        ],
    },
    {
        "id": "p2p",
        "zh": "分布式交易与点对点交易",
        "color": "#60a5fa",
        "queries": [
            "peer-to-peer energy trading",
            "transactive energy",
            "community energy market",
            "microgrid energy market",
        ],
        "keywords": [
            "peer-to-peer", "peer to peer", "p2p trading", "transactive energy",
            "community energy", "microgrid market", "分布式交易", "点对点",
        ],
    },
    {
        "id": "storage",
        "zh": "储能参与市场与套利",
        "color": "#c084fc",
        "queries": [
            "energy storage electricity market participation",
            "battery storage market revenue",
            "energy storage arbitrage market",
            "pumped hydro market bidding",
        ],
        "keywords": [
            "energy storage", "battery storage", "storage arbitrage",
            "storage bidding", "pumped hydro", "储能",
        ],
    },
    {
        "id": "ev",
        "zh": "电动汽车与充电市场",
        "color": "#2dd4bf",
        "queries": [
            "electric vehicle charging electricity market",
            "electric vehicle aggregator market",
            "vehicle-to-grid market participation",
        ],
        "keywords": [
            "electric vehicle", "charging station", "vehicle-to-grid", "vehicle to grid",
            "v2g", "电动汽车", "充电",
        ],
    },
    {
        "id": "bidding",
        "zh": "市场博弈与报价策略",
        "color": "#f97316",
        "queries": [
            "bidding strategy electricity market",
            "market power electricity market",
            "strategic bidding power market",
            "electricity market equilibrium",
        ],
        "keywords": [
            "bidding strategy", "strategic bidding", "market power", "game theory",
            "nash equilibrium", "equilibrium", "博弈", "报价策略",
        ],
    },
    {
        "id": "retail",
        "zh": "售电侧与零售市场",
        "color": "#e879f9",
        "queries": [
            "electricity retail market",
            "electricity retailer pricing strategy",
            "electricity tariff design",
            "residential electricity pricing",
        ],
        "keywords": [
            "retail market", "retailer", "retail pricing", "tariff design", "tariff",
            "售电", "零售市场", "电价套餐",
        ],
    },
    {
        "id": "ai",
        "zh": "人工智能在电力市场中的应用",
        "color": "#818cf8",
        "queries": [
            "machine learning electricity market",
            "deep learning power market",
            "reinforcement learning electricity market bidding",
            "large language model power system",
        ],
        "keywords": [
            "machine learning", "deep learning", "reinforcement learning",
            "artificial intelligence", "neural network", "large language model",
            "深度学习", "机器学习", "强化学习", "大模型",
        ],
    },
    {
        "id": "uncertainty",
        "zh": "不确定性、风险与随机优化",
        "color": "#94a3b8",
        "queries": [
            "uncertainty electricity market",
            "stochastic optimization power market",
            "risk management electricity market",
            "robust optimization electricity market",
        ],
        "keywords": [
            "uncertainty", "stochastic optimization", "robust optimization",
            "chance-constrained", "risk management", "scenario", "随机", "鲁棒", "风险",
        ],
    },
    {
        "id": "integrated",
        "zh": "综合能源系统与多能市场",
        "color": "#10b981",
        "queries": [
            "integrated energy system market",
            "multi-energy market coupling",
            "electricity hydrogen market",
            "sector coupling energy market",
        ],
        "keywords": [
            "integrated energy", "multi-energy", "sector coupling", "hydrogen",
            "power-to-gas", "综合能源", "多能互补", "氢",
        ],
    },
    {
        "id": "congestion",
        "zh": "电网阻塞、输电权与网络定价",
        "color": "#f43f5e",
        "queries": [
            "congestion management electricity market",
            "financial transmission right",
            "nodal pricing power system",
            "transmission congestion market",
        ],
        "keywords": [
            "congestion", "transmission right", "transmission congestion",
            "nodal pricing", "zonal pricing", "阻塞", "输电权",
        ],
    },
    {
        "id": "policy",
        "zh": "电力市场政策与机制设计",
        "color": "#0ea5e9",
        "queries": [
            "electricity market design",
            "power market reform",
            "electricity market deregulation",
            "electricity market policy",
        ],
        "keywords": [
            "market design", "market reform", "deregulation", "liberalization",
            "electricity policy", "regulation", "电力市场改革", "机制设计",
        ],
    },
]

TOPIC_BY_ID = {t["id"]: t for t in TOPICS}

# ---------------------------------------------------------------- 重点期刊
# 命中这些期刊的文献会在界面上显示"重点"标记，并得到更高的影响力权重。

TOP_JOURNALS = {
    "ieee transactions on power systems": 1.00,
    "ieee transactions on smart grid": 0.98,
    "ieee transactions on sustainable energy": 0.95,
    "ieee transactions on energy markets, policy and regulation": 1.00,
    "ieee transactions on industry applications": 0.80,
    "ieee transactions on industrial informatics": 0.85,
    "ieee transactions on power delivery": 0.78,
    "ieee journal of emerging and selected topics in power electronics": 0.70,
    "applied energy": 1.00,
    "energy economics": 1.00,
    "energy policy": 0.95,
    "the energy journal": 0.95,
    "energy": 0.92,
    "renewable and sustainable energy reviews": 0.95,
    "nature energy": 1.00,
    "joule": 1.00,
    "electric power systems research": 0.88,
    "international journal of electrical power & energy systems": 0.88,
    "energy conversion and economics": 0.90,
    "journal of modern power systems and clean energy": 0.88,
    "csee journal of power and energy systems": 0.88,
    "iet generation, transmission & distribution": 0.82,
    "iET renewable power generation": 0.78,
    "protection and control of modern power systems": 0.82,
    "energy strategy reviews": 0.80,
    "utilities policy": 0.80,
    "the electricity journal": 0.75,
    "energy reports": 0.72,
    "sustainable energy, grids and networks": 0.80,
    "journal of energy storage": 0.72,
    "energy conversion and management": 0.85,
    "applied soft computing": 0.68,
    "expert systems with applications": 0.68,
    "energy informatics": 0.72,
    "advances in applied energy": 0.90,
}

# 期刊层级：先看这份人工整理的名单（电力/能源/综合领域），
# 名单外的期刊由 crawler/metrics.py 依据 OpenAlex 的期刊指标自动定级。
#
#   T1 顶级期刊 / T2 权威期刊 / T3 核心期刊 / T4 一般期刊 / T5 新兴或低影响期刊
#   PRE 预印本（arXiv、SSRN、Zenodo 等，不算期刊层级）
JOURNAL_TIERS = {
    # ---- T1：本领域公认的顶刊 ----
    "nature energy": "T1",
    "nature climate change": "T1",
    "joule": "T1",
    "energy & environmental science": "T1",
    "progress in energy and combustion science": "T1",
    "applied energy": "T1",
    "advances in applied energy": "T1",
    "energy conversion and management": "T1",
    "renewable and sustainable energy reviews": "T1",
    "ieee transactions on power systems": "T1",
    "ieee transactions on smart grid": "T1",
    "ieee transactions on sustainable energy": "T1",
    "ieee transactions on industrial informatics": "T1",
    "ieee transactions on energy markets, policy and regulation": "T1",
    # ---- T2：领域权威期刊 ----
    "energy economics": "T2",
    "energy policy": "T2",
    "the energy journal": "T2",
    "energy": "T2",
    "ieee transactions on power delivery": "T2",
    "ieee transactions on industry applications": "T2",
    "ieee transactions on transportation electrification": "T2",
    "electric power systems research": "T2",
    "international journal of electrical power & energy systems": "T2",
    "journal of modern power systems and clean energy": "T2",
    "csee journal of power and energy systems": "T2",
    "protection and control of modern power systems": "T2",
    "iet generation, transmission & distribution": "T2",
    "iet renewable power generation": "T2",
    "energy strategy reviews": "T2",
    "journal of energy storage": "T2",
    "sustainable energy, grids and networks": "T2",
    "energy conversion and economics": "T2",
    "utilities policy": "T2",
    # ---- T3：领域核心期刊 ----
    "ieee access": "T3",
    "energies": "T3",
    "sustainability": "T3",
    "energy reports": "T3",
    "the electricity journal": "T3",
    "applied sciences": "T3",
    "energy informatics": "T3",
    "energy sources part b: economics, planning, and policy": "T3",
    "international journal of sustainable energy": "T3",
}

# 期刊层级显示文案
TIER_LABELS = {
    "T1": "顶级期刊",
    "T2": "权威期刊",
    "T3": "核心期刊",
    "T4": "一般期刊",
    "T5": "新兴期刊",
    "PRE": "预印本",
    "NA": "未收录",
}

# ---------------------------------------------------------------- 停用词

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "as", "at", "by",
    "for", "from", "in", "into", "of", "on", "onto", "to", "with", "within", "without",
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does", "did",
    "have", "has", "had", "having", "will", "would", "shall", "should", "can", "could",
    "may", "might", "must", "this", "that", "these", "those", "it", "its", "their",
    "there", "here", "we", "our", "you", "your", "they", "them", "he", "she", "his",
    "her", "i", "me", "my", "not", "no", "nor", "so", "such", "also", "both", "each",
    "more", "most", "other", "some", "any", "all", "very", "just", "only", "own",
    "same", "too", "s", "t", "d", "ll", "m", "re", "ve", "y", "about", "above",
    "after", "again", "against", "before", "below", "between", "during", "under",
    "over", "up", "down", "out", "off", "through", "because", "while", "when", "where",
    "which", "who", "whom", "what", "how", "why", "however", "therefore", "thus",
    "moreover", "furthermore", "paper", "study", "results", "result", "proposed",
    "method", "methods", "approach", "approaches", "based", "using", "used", "use",
    "new", "novel", "present", "presents", "presented", "show", "shows", "shown",
    "case", "cases", "two", "three", "one", "first", "second", "third", "high", "low",
    "different", "various", "given", "including", "include", "includes", "analysis",
    "model", "models", "modeling", "modelling", "framework", "system", "systems",
    "data", "time", "number", "value", "values", "set", "optimal", "optimization",
    "optimisation", "problem", "problems", "consider", "considered", "considering",
    "obtained", "total", "average", "respectively", "significant", "significantly",
    "compared", "comparison", "increase", "decrease", "higher", "lower", "large",
    "small", "good", "better", "best", "well", "well-known", "recent", "recently",
    "et", "al", "ieee", "doi", "http", "https", "www", "com", "org", "figure", "table",
    "eq", "equations", "section", "chapter", "vol", "pp", "copyright", "elsevier",
    "springer", "wiley", "author", "authors", "rights", "reserved", "abstract",
    "keywords", "introduction", "conclusion", "references", "however", "although",
    "possible", "provide", "provides", "provided", "make", "makes", "made", "take",
    "takes", "need", "needs", "able", "may", "many", "much", "less", "least", "like",
    "unlike", "due", "order", "way", "ways", "term", "terms", "level", "levels",
    "type", "types", "part", "parts", "point", "points", "form", "forms", "role",
    "state", "states", "process", "processes", "effect", "effects", "impact", "impacts",
    "cost", "costs", "price", "prices", "market", "markets", "power", "energy",
    "electricity", "electric", "grid", "network", "networks", "demand", "supply",
}

# 中文检索直达（用于界面上"去中文库检索"按钮）
CN_SEARCH_TEMPLATES = [
    ("知网 CNKI", "https://kns.cnki.net/kns8s/defaultresult/index?kw={q}&korder=SU"),
    ("万方", "https://s.wanfangdata.com.cn/paper?q={q}"),
    ("百度学术", "https://xueshu.baidu.com/s?wd={q}"),
    ("Google Scholar", "https://scholar.google.com/scholar?q={q}"),
]

# arXiv 分类白名单（预印本源的检索范围）
ARXIV_CATEGORIES = ["eess.SY", "cs.SY", "econ.EM", "q-fin.GN", "math.OC"]
