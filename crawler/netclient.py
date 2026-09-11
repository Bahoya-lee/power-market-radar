# -*- coding: utf-8 -*-
"""
轻量网络层：优先用 requests，没装则退回标准库 urllib。
统一处理重试、退避、超时、编码与限速。

注意：本文件名不能叫 http.py —— 那会遮蔽标准库的 http 包，
导致 urllib 无法导入。同理避开 json.py / types.py 等。
"""

from __future__ import annotations

import gzip
import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from . import config

try:  # requests 是可选依赖
    import requests  # type: ignore

    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAS_REQUESTS = False


class FetchError(RuntimeError):
    """网络获取失败（重试后仍然失败）。"""


_last_request_at: dict[str, float] = {}


def _proxy_config() -> dict[str, str] | None:
    """决定是否走代理。

    默认只读取标准的 HTTP_PROXY / HTTPS_PROXY 环境变量，不自动继承
    Windows 注册表里的系统代理。很多代理软件退出后注册表仍有残留，
    会让 requests 一直连本地端口并超时。

    可用 PMR_PROXY_MODE=direct 强制直连，或用 PMR_PROXY=http://host:port
    指定代理；PMR_PROXY_MODE=system 则交回 requests 读取系统代理。
    """
    mode = (os.environ.get("PMR_PROXY_MODE") or "").strip().lower()
    explicit = (os.environ.get("PMR_PROXY") or "").strip()

    if mode in {"direct", "none", "off"} or explicit.lower() in {"direct", "none", "off"}:
        return {"http": "", "https": ""}
    if explicit:
        return {"http": explicit, "https": explicit}
    if mode == "system":
        return None

    http_proxy = (os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "").strip()
    https_proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or http_proxy
    ).strip()
    if http_proxy or https_proxy:
        return {"http": http_proxy, "https": https_proxy}
    return {"http": "", "https": ""}


def _urllib_opener():
    """构造 urllib opener，确保代理策略与 requests 分支一致。"""
    proxies = _proxy_config()
    if proxies is None:
        return urllib.request.build_opener()
    active = {k: v for k, v in proxies.items() if v}
    return urllib.request.build_opener(urllib.request.ProxyHandler(active))


def _throttle(host: str) -> None:
    """同一主机两次请求之间保持最小间隔，做一个有礼貌的爬虫。"""
    now = time.time()
    last = _last_request_at.get(host, 0.0)
    wait = config.REQUEST_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_at[host] = time.time()


def _decode_body(raw: bytes, encoding) -> str:
    if encoding:
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            pass
    return raw.decode("utf-8", errors="replace")


def get_text(
    url: str,
    params: dict | None = None,
    *,
    timeout: int | None = None,
    retries: int | None = None,
    accept: str = "*/*",
) -> str:
    """GET 一个 URL 并返回响应文本，失败时自动重试。"""
    timeout = timeout or config.HTTP_TIMEOUT
    retries = config.HTTP_RETRIES if retries is None else retries

    if params:
        query = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
        url = f"{url}{'&' if '?' in url else '?'}{query}"

    host = urllib.parse.urlparse(url).netloc
    last_err = None

    for attempt in range(1, retries + 1):
        _throttle(host)
        try:
            if _HAS_REQUESTS:
                proxies = _proxy_config()
                resp = requests.get(
                    url,
                    headers={
                        "User-Agent": config.USER_AGENT,
                        "Accept": accept,
                        "Accept-Encoding": "gzip, deflate",
                    },
                    timeout=timeout,
                    proxies=proxies,
                )
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} {url[:120]}")
                resp.encoding = resp.encoding or "utf-8"
                return resp.text

            opener = _urllib_opener()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept": accept,
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            with opener.open(req, timeout=timeout) as fp:
                raw = fp.read()
                enc = fp.headers.get("Content-Encoding", "")
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                return _decode_body(raw, fp.headers.get_content_charset())

        except FetchError as exc:
            last_err = exc
        except urllib.error.HTTPError as exc:
            # 4xx（除 429）通常重试也没用，直接放弃
            if exc.code < 500 and exc.code != 429:
                raise FetchError(f"HTTP {exc.code} {url[:120]}") from exc
            last_err = exc
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            last_err = exc
        except Exception as exc:  # noqa: BLE001 - requests 的各路异常
            last_err = exc

        if attempt < retries:
            delay = config.HTTP_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 1)
            time.sleep(delay)

    raise FetchError(f"获取失败（重试 {retries} 次）：{url[:140]} —— {last_err}")


def get_json(
    url: str,
    params: dict | None = None,
    *,
    timeout: int | None = None,
    retries: int | None = None,
) -> dict:
    """GET 一个 JSON 接口。"""
    text = get_text(
        url, params, timeout=timeout, retries=retries, accept="application/json"
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"返回内容不是合法 JSON：{url[:140]}") from exc


def has_network(probe_urls: list[str] | None = None) -> bool:
    """快速探测能否联网（用于给出友好提示）。"""
    urls = probe_urls or [
        "https://api.openalex.org/works?per-page=1",
        "https://api.crossref.org/works?rows=1",
    ]
    for url in urls:
        try:
            get_text(url, timeout=12, retries=1, accept="application/json")
            return True
        except Exception:
            continue
    return False
