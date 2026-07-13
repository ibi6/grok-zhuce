"""Safe task-level proxy profiles, health checks, and failure cooldowns."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests


SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5"}
DEFAULT_CHECK_URL = "https://accounts.x.ai/"


class ProxyPoolError(Exception):
    pass


class NoProxyAvailable(ProxyPoolError):
    pass


class ProxyConnectionError(ProxyPoolError):
    pass


def normalize_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("代理地址不能为空")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError(f"不支持的代理协议: {parsed.scheme or '(empty)'}")
    if parsed.username or parsed.password:
        raise ValueError("当前版本不支持带用户名密码的浏览器代理")
    if not parsed.hostname:
        raise ValueError("代理地址缺少主机名")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("代理端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("代理地址必须包含 1-65535 端口")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return urlunparse((scheme, f"{host}:{port}", "", "", "", ""))


def redact_proxy_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else "http://" + raw)
        host = parsed.hostname or "?"
        port = f":{parsed.port}" if parsed.port else ""
        auth = "user:***@" if parsed.username else ""
        return f"{parsed.scheme or 'http'}://{auth}{host}{port}"
    except Exception:
        return "(invalid proxy)"


def parse_proxy_text(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            url = normalize_proxy_url(line)
        except ValueError as exc:
            errors.append(f"第 {line_number} 行: {exc}")
            continue
        if url in seen:
            continue
        seen.add(url)
        entries.append({"name": "", "url": url, "enabled": True, "priority": 0})
    if errors:
        raise ValueError("；".join(errors))
    return entries


def normalize_proxy_entries(values: Iterable[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values or []:
        raw = {"url": value} if isinstance(value, str) else dict(value or {})
        url = normalize_proxy_url(str(raw.get("url") or ""))
        if url in seen:
            continue
        seen.add(url)
        entries.append(
            {
                "name": str(raw.get("name") or "").strip(),
                "url": url,
                "enabled": bool(raw.get("enabled", True)),
                "priority": int(raw.get("priority") or 0),
            }
        )
    return entries


def is_proxy_connection_error(error: BaseException | str, proxy_url: str = "") -> bool:
    text = str(error or "").lower()
    markers = (
        "proxy connection",
        "proxyconnect",
        "could not connect to proxy",
        "failed to connect to proxy",
        "err_proxy_connection_failed",
        "proxy tunnel",
        "socks5",
        "curl: (5)",
        "curl: (97)",
    )
    if any(marker in text for marker in markers):
        return True
    if proxy_url:
        try:
            parsed = urlparse(proxy_url)
            endpoint = f"{parsed.hostname}:{parsed.port}".lower()
            host = str(parsed.hostname or "").lower()
            connection_markers = ("connection refused", "could not connect", "failed to connect", "curl: (7)")
            return (endpoint in text or (host and host in text)) and any(
                marker in text for marker in connection_markers
            )
        except Exception:
            return False
    return False


@dataclass
class ProxyRuntimeState:
    healthy: bool | None = None
    latency_ms: int | None = None
    last_checked: float = 0.0
    last_error: str = ""
    failures: int = 0
    cooldown_until: float = 0.0


class ProxyPoolManager:
    def __init__(
        self,
        entries: Iterable[Any] = (),
        *,
        selected_url: str = "",
        failure_threshold: int = 2,
        cooldown_seconds: int = 300,
        check_url: str = DEFAULT_CHECK_URL,
    ):
        self.entries = normalize_proxy_entries(entries)
        self.selected_url = normalize_proxy_url(selected_url) if selected_url else ""
        self.failure_threshold = max(int(failure_threshold), 1)
        self.cooldown_seconds = max(int(cooldown_seconds), 1)
        self.check_url = str(check_url or DEFAULT_CHECK_URL).strip()
        self.states = {entry["url"]: ProxyRuntimeState() for entry in self.entries}

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        runtime_states: dict[str, Any] | None = None,
    ) -> "ProxyPoolManager":
        entries = list(config.get("proxy_pool") or [])
        legacy = str(config.get("proxy") or "").strip()
        if not entries and legacy:
            entries = [{"name": "当前代理", "url": legacy, "enabled": True, "priority": 0}]
        manager = cls(
            entries,
            selected_url=str(config.get("proxy_pool_selected") or "").strip(),
            failure_threshold=int(config.get("proxy_failure_threshold") or 2),
            cooldown_seconds=int(config.get("proxy_cooldown_seconds") or 300),
            check_url=str(config.get("proxy_check_url") or DEFAULT_CHECK_URL),
        )
        manager.apply_runtime_states(runtime_states or {})
        return manager

    def apply_runtime_states(self, states: dict[str, Any]) -> None:
        for url, raw in states.items():
            if url not in self.states:
                continue
            if isinstance(raw, ProxyRuntimeState):
                self.states[url] = ProxyRuntimeState(**vars(raw))
            elif isinstance(raw, dict):
                allowed = {key: raw[key] for key in vars(ProxyRuntimeState()) if key in raw}
                self.states[url] = ProxyRuntimeState(**allowed)

    @property
    def configured(self) -> bool:
        return bool(self.entries)

    def to_config_entries(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self.entries]

    def select(self, *, exclude: str = "", now: float | None = None) -> str:
        now = time.time() if now is None else now
        candidates = []
        for index, entry in enumerate(self.entries):
            url = entry["url"]
            state = self.states[url]
            if not entry["enabled"] or url == exclude or state.cooldown_until > now:
                continue
            candidates.append((index, entry, state))
        if self.selected_url:
            for _, entry, _ in candidates:
                if entry["url"] == self.selected_url:
                    return entry["url"]
        if not candidates:
            raise NoProxyAvailable("代理池中没有可用代理，且不会回退直连")
        candidates.sort(
            key=lambda item: (
                0 if item[2].healthy is True else (1 if item[2].healthy is None else 2),
                -int(item[1].get("priority") or 0),
                item[2].latency_ms if item[2].latency_ms is not None else 10**9,
                item[0],
            )
        )
        return candidates[0][1]["url"]

    def mark_success(self, url: str, *, latency_ms: int | None = None) -> None:
        state = self.states.get(url)
        if not state:
            return
        state.healthy = True
        state.failures = 0
        state.cooldown_until = 0
        state.last_error = ""
        if latency_ms is not None:
            state.latency_ms = int(latency_ms)

    def mark_failure(self, url: str, error: BaseException | str, *, now: float | None = None) -> None:
        state = self.states.get(url)
        if not state:
            return
        now = time.time() if now is None else now
        state.healthy = False
        state.failures += 1
        state.last_error = str(error or "")[:240]
        if state.failures >= self.failure_threshold:
            state.cooldown_until = now + self.cooldown_seconds

    def next_after_failure(self, current_url: str, error: BaseException | str) -> str:
        self.mark_failure(current_url, error)
        try:
            return self.select(exclude=current_url)
        except NoProxyAvailable:
            state = self.states.get(current_url)
            if state and state.failures < self.failure_threshold and state.cooldown_until <= time.time():
                return current_url
            raise

    def check(self, url: str, *, session=requests, timeout: float = 8.0) -> ProxyRuntimeState:
        normalized = normalize_proxy_url(url)
        if normalized not in self.states:
            self.states[normalized] = ProxyRuntimeState()
        state = self.states[normalized]
        started = time.perf_counter()
        try:
            response = session.get(
                self.check_url,
                proxies={"http": normalized, "https": normalized},
                timeout=timeout,
                allow_redirects=False,
            )
            latency = int((time.perf_counter() - started) * 1000)
            state.healthy = 100 <= int(response.status_code) <= 599 and int(response.status_code) != 407
            state.latency_ms = latency
            state.last_error = "" if state.healthy else f"HTTP {response.status_code}"
            state.failures = 0 if state.healthy else state.failures + 1
            state.cooldown_until = 0 if state.healthy else state.cooldown_until
        except Exception as exc:
            state.healthy = False
            state.latency_ms = None
            state.failures += 1
            state.last_error = str(exc)[:240]
            if state.failures >= self.failure_threshold:
                state.cooldown_until = time.time() + self.cooldown_seconds
        state.last_checked = time.time()
        return state

    def check_all(self, *, session=requests, timeout: float = 8.0) -> dict[str, ProxyRuntimeState]:
        for entry in self.entries:
            if entry["enabled"]:
                self.check(entry["url"], session=session, timeout=timeout)
        return self.states
