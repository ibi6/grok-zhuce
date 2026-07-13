"""Outlook account pool and Microsoft Graph verification-mail reader."""

from __future__ import annotations

import csv
import io
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests
from filelock import FileLock

from safe_io import atomic_write_text


TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
SECRET_KEYS = ("password", "refresh_token", "access_token", "client_secret")


class OutlookError(Exception):
    pass


class OutlookAuthError(OutlookError):
    pass


def _sleep_with_cancel(seconds: float, cancel_callback=None) -> None:
    deadline = time.time() + max(float(seconds), 0)
    while time.time() < deadline:
        if cancel_callback and cancel_callback():
            raise OutlookError("操作已取消")
        time.sleep(min(0.25, max(deadline - time.time(), 0)))


@dataclass
class OutlookAccount:
    email: str
    password: str = ""
    client_id: str = ""
    refresh_token: str = ""
    status: str = "available"
    last_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def usable(self) -> bool:
        return bool(self.email and self.client_id and self.refresh_token) and self.status in {
            "available", "mail_timeout", "failed"
        }


def redact_secrets(text: str, *secrets: str) -> str:
    result = str(text or "")
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    for key in SECRET_KEYS:
        result = re.sub(
            rf'(?i)(["\']?{re.escape(key)}["\']?\s*[:=]\s*["\']?)[^\s,"\']+',
            r"\1***",
            result,
        )
    return result


def _account_from_values(values, line_number):
    values = [str(value or "").strip() for value in values]
    if len(values) < 4:
        raise ValueError(f"第 {line_number} 行格式错误，需要 email、password、client_id、refresh_token")
    email, password, client_id, refresh_token = values[:4]
    if not email or "@" not in email:
        raise ValueError(f"第 {line_number} 行邮箱地址无效")
    status = "available" if client_id and refresh_token else "needs_authorization"
    return OutlookAccount(email, password, client_id, refresh_token, status=status)


def parse_accounts_text(text: str, suffix: str = ".txt") -> list[OutlookAccount]:
    accounts = []
    errors = []
    if suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        required = {"email", "password", "client_id", "refresh_token"}
        normalized_fields = [str(x or "").strip() for x in (reader.fieldnames or [])]
        if not normalized_fields or not required.issubset(set(normalized_fields)):
            raise ValueError("CSV 必须包含 email,password,client_id,refresh_token 列")
        for line_number, row in enumerate(reader, start=2):
            try:
                normalized_row = {str(k or "").strip(): value for k, value in row.items()}
                accounts.append(_account_from_values([normalized_row.get(k, "") for k in ("email", "password", "client_id", "refresh_token")], line_number))
            except ValueError as exc:
                errors.append(str(exc))
    else:
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                accounts.append(_account_from_values(line.split("----"), line_number))
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        raise ValueError("；".join(errors))
    if not accounts:
        raise ValueError("Outlook 凭证文件中没有账号")
    seen = set()
    duplicates = set()
    for account in accounts:
        key = account.email.lower()
        if key in seen:
            duplicates.add(account.email)
        seen.add(key)
    if duplicates:
        raise ValueError(f"Outlook 凭证包含重复邮箱: {', '.join(sorted(duplicates))}")
    return accounts


def load_accounts(path: str) -> list[OutlookAccount]:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return parse_accounts_text(handle.read(), os.path.splitext(path)[1])


class OutlookAccountPool:
    def __init__(self, accounts: list[OutlookAccount], path: str = ""):
        self.accounts = accounts
        self.path = os.path.abspath(path) if path else ""
        self._lock = threading.Lock()
        self._by_email = {account.email.lower(): account for account in accounts}

    def acquire(self) -> OutlookAccount:
        with self._lock:
            for account in self.accounts:
                if account.usable and account.lock.acquire(blocking=False):
                    account.status = "in_use"
                    return account
        raise OutlookError("没有可用的 Outlook OAuth 账号")

    def get(self, email: str) -> OutlookAccount:
        account = self._by_email.get(email.lower())
        if not account:
            raise OutlookError(f"Outlook 账号不在当前账号池: {email}")
        return account

    def release(self, account: OutlookAccount, status="available", error=""):
        account.status = status
        account.last_error = redact_secrets(error, account.password, account.refresh_token)
        if account.lock.locked():
            account.lock.release()

    def persist_refresh_token(self, account: OutlookAccount) -> None:
        if not self.path:
            return
        path = self.path
        suffix = os.path.splitext(path)[1].lower()
        with FileLock(path + ".lock", timeout=30):
            with open(path, "r", encoding="utf-8-sig", newline="") as handle:
                original = handle.read()
            if suffix == ".csv":
                reader = csv.DictReader(io.StringIO(original))
                fields = [str(field or "").strip() for field in (reader.fieldnames or [])]
                if not fields:
                    raise OutlookError("Outlook CSV 缺少表头")
                rows = []
                matched = False
                for row in reader:
                    normalized = {str(k or "").strip(): value for k, value in row.items()}
                    if str(normalized.get("email") or "").strip().lower() == account.email.lower():
                        normalized["refresh_token"] = account.refresh_token
                        matched = True
                    rows.append(normalized)
                if not matched:
                    raise OutlookError(f"Outlook 凭证文件中找不到账号: {account.email}")
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
                updated = output.getvalue()
            else:
                matched = False
                lines = []
                for raw_line in original.splitlines(keepends=True):
                    newline = "\r\n" if raw_line.endswith("\r\n") else ("\n" if raw_line.endswith("\n") else "")
                    body = raw_line[:-len(newline)] if newline else raw_line
                    stripped = body.strip()
                    if stripped and not stripped.startswith("#"):
                        parts = body.split("----")
                        if len(parts) >= 4 and parts[0].strip().lower() == account.email.lower():
                            parts[3] = account.refresh_token
                            body = "----".join(parts)
                            matched = True
                    lines.append(body + newline)
                if not matched:
                    raise OutlookError(f"Outlook 凭证文件中找不到账号: {account.email}")
                updated = "".join(lines)
            atomic_write_text(path, updated, mode=0o600)
        with _cache_lock:
            _pool_cache[path] = (os.path.getmtime(path), self)


def exchange_access_token(
    account: OutlookAccount,
    session=requests,
    timeout=30,
    persist_callback: Optional[Callable[[OutlookAccount], None]] = None,
    proxies: Optional[dict] = None,
) -> str:
    request_kwargs = {
        "data": {
            "client_id": account.client_id,
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
            "scope": "https://graph.microsoft.com/.default offline_access",
        },
        "timeout": timeout,
    }
    if proxies:
        request_kwargs["proxies"] = proxies
    response = session.post(TOKEN_URL, **request_kwargs)
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if response.status_code >= 400 or not payload.get("access_token"):
        code = payload.get("error", f"http_{response.status_code}")
        description = redact_secrets(payload.get("error_description", "OAuth token exchange failed"), account.refresh_token)
        raise OutlookAuthError(f"{code}: {description}")
    if payload.get("refresh_token"):
        account.refresh_token = payload["refresh_token"]
        if persist_callback:
            try:
                persist_callback(account)
            except Exception as exc:
                account.last_error = redact_secrets(
                    f"refresh token 持久化失败: {exc}", account.password, account.refresh_token
                )
    return payload["access_token"]


def extract_code(message: dict) -> Optional[str]:
    subject = str(message.get("subject") or "")
    preview = str(message.get("bodyPreview") or "")
    body = message.get("body") or {}
    content = str(body.get("content") or "") if isinstance(body, dict) else str(body)
    text = "\n".join((subject, preview, re.sub(r"<[^>]+>", " ", content)))
    if not re.search(r"(?i)\b(xai|x\.ai|grok|verification|verify|验证码)\b", text):
        return None
    for pattern in (r"\b([A-Z0-9]{3}-[A-Z0-9]{3})\b", r"\b(\d{6})\b", r"\b(\d{4,8})\b"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def wait_for_verification_code(
    account: OutlookAccount,
    timeout=180,
    poll_interval=3,
    log_callback: Optional[Callable[[str], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    session=requests,
    persist_callback: Optional[Callable[[OutlookAccount], None]] = None,
    proxies: Optional[dict] = None,
) -> str:
    attempt_started_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    account.last_error = ""
    access_token = exchange_access_token(
        account, session=session, persist_callback=persist_callback, proxies=proxies
    )
    if account.last_error and log_callback:
        log_callback(f"[!] {account.last_error}")
    deadline = time.time() + timeout
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "$top": "25",
        "$select": "id,subject,receivedDateTime,from,bodyPreview,body",
        "$orderby": "receivedDateTime desc",
    }
    seen_message_ids = set()
    while time.time() < deadline:
        if cancel_callback and cancel_callback():
            raise OutlookError("操作已取消")
        request_kwargs = {"headers": headers, "params": params, "timeout": 30}
        if proxies:
            request_kwargs["proxies"] = proxies
        response = session.get(MESSAGES_URL, **request_kwargs)
        if response.status_code == 429:
            try:
                delay = min(int(response.headers.get("Retry-After", poll_interval)), 30)
            except (TypeError, ValueError):
                delay = min(int(poll_interval), 30)
            _sleep_with_cancel(delay, cancel_callback)
            continue
        if response.status_code == 401:
            raise OutlookAuthError("Microsoft Graph access token 已失效")
        if response.status_code >= 400:
            raise OutlookError(f"Microsoft Graph HTTP {response.status_code}")
        messages = response.json().get("value", [])
        if log_callback:
            log_callback(f"[Debug] Outlook 本轮检查 {len(messages)} 封邮件")
        for message in messages:
            message_id = str(message.get("id") or "")
            if message_id and message_id in seen_message_ids:
                continue
            if message_id:
                seen_message_ids.add(message_id)
            received_raw = str(message.get("receivedDateTime") or "")
            if received_raw:
                try:
                    received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
                    if received_at < attempt_started_at:
                        continue
                except ValueError:
                    pass
            code = extract_code(message)
            if code:
                return code
        _sleep_with_cancel(poll_interval, cancel_callback)
    raise OutlookError(f"Outlook 在 {timeout}s 内未收到验证码邮件")


_pool_cache = {}
_cache_lock = threading.Lock()


def get_pool(path: str) -> OutlookAccountPool:
    absolute = os.path.abspath(path)
    mtime = os.path.getmtime(absolute)
    with _cache_lock:
        cached = _pool_cache.get(absolute)
        if cached and cached[0] == mtime:
            return cached[1]
        pool = OutlookAccountPool(load_accounts(absolute), path=absolute)
        _pool_cache[absolute] = (mtime, pool)
        return pool
