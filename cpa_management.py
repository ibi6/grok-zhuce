"""Secure CLIProxyAPI/CPA management API client for auth-file uploads."""

from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests


MAX_AUTH_FILE_BYTES = 2 * 1024 * 1024
DPAPI_PREFIX = "dpapi:"
_SESSION_MANAGEMENT_KEY = ""


class CPAManagementError(RuntimeError):
    """Base error for safe, user-facing CPA management failures."""


class CPAManagementConfigError(CPAManagementError):
    pass


class CPAManagementAuthError(CPAManagementError):
    pass


class CPASecretError(CPAManagementError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def set_session_management_key(value: str) -> None:
    global _SESSION_MANAGEMENT_KEY
    _SESSION_MANAGEMENT_KEY = str(value or "").strip()


def _data_blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _dpapi_transform(data: bytes, *, protect: bool) -> bytes:
    if os.name != "nt":
        raise CPASecretError("Windows DPAPI 仅支持 Windows")
    if not data:
        return b""

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    input_blob, input_buffer = _data_blob(data)
    output_blob = _DataBlob()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN

    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Grok CPA Management Key",
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    if not ok:
        raise CPASecretError(f"DPAPI 操作失败（错误码 {ctypes.get_last_error()}）")

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if output_blob.pbData:
            kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def protect_secret(value: str) -> str:
    secret = str(value or "")
    if not secret:
        return ""
    encrypted = _dpapi_transform(secret.encode("utf-8"), protect=True)
    return DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not raw.startswith(DPAPI_PREFIX):
        raise CPASecretError("管理密钥不是有效的 DPAPI 密文")
    try:
        encrypted = base64.b64decode(raw[len(DPAPI_PREFIX):], validate=True)
    except Exception as exc:
        raise CPASecretError("管理密钥密文格式无效") from exc
    try:
        return _dpapi_transform(encrypted, protect=False).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CPASecretError("管理密钥解密结果无效") from exc


def configured_management_key(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    encrypted = str(cfg.get("cpa_management_key_encrypted") or "").strip()
    return unprotect_secret(encrypted) if encrypted else ""


def resolve_management_key(
    config: dict[str, Any] | None = None,
    *,
    explicit_key: str = "",
) -> str:
    env_key = str(os.environ.get("CPA_MANAGEMENT_KEY") or "").strip()
    if env_key:
        return env_key
    direct = str(explicit_key or "").strip()
    if direct:
        return direct
    if _SESSION_MANAGEMENT_KEY:
        return _SESSION_MANAGEMENT_KEY
    return configured_management_key(config)


def persist_management_key(
    config: dict[str, Any],
    value: str,
    *,
    remember: bool,
) -> None:
    secret = str(value or "").strip()
    set_session_management_key(secret)
    config["cpa_management_remember_key"] = bool(remember)
    if remember and secret:
        config["cpa_management_key_encrypted"] = protect_secret(secret)
    elif not remember:
        config["cpa_management_key_encrypted"] = ""


def _is_loopback(hostname: str) -> bool:
    host = str(hostname or "").strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_management_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise CPAManagementConfigError("CPA 管理地址不能为空")
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise CPAManagementConfigError("CPA 管理地址必须使用 HTTP 或 HTTPS")
    if not parsed.hostname:
        raise CPAManagementConfigError("CPA 管理地址缺少主机名")
    if parsed.username or parsed.password:
        raise CPAManagementConfigError("CPA 管理地址不能包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise CPAManagementConfigError("CPA 管理地址不能包含查询参数或片段")
    if scheme == "http" and not _is_loopback(parsed.hostname):
        raise CPAManagementConfigError("远程 CPA 管理地址必须使用 HTTPS")

    path = parsed.path.rstrip("/")
    lower_path = path.lower()
    if lower_path.endswith("/v0/management/auth-files"):
        final_path = path
    elif lower_path.endswith("/v0/management"):
        final_path = path + "/auth-files"
    else:
        final_path = (path if path else "") + "/v0/management/auth-files"
    return urlunsplit((scheme, parsed.netloc, final_path, "", ""))


def redact_management_url(value: str) -> str:
    try:
        parsed = urlsplit(normalize_management_url(value))
        port = f":{parsed.port}" if parsed.port else ""
        host = parsed.hostname or "?"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}{port}"
    except Exception:
        return "(invalid CPA URL)"


def _headers(key: str) -> dict[str, str]:
    if not key:
        raise CPAManagementAuthError("CPA Management Key 未配置")
    return {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


def _safe_status_error(status_code: int) -> CPAManagementError:
    if status_code == 400:
        return CPAManagementConfigError("CPA 拒绝了认证文件或文件名（HTTP 400）")
    if status_code == 401:
        return CPAManagementAuthError("CPA Management Key 缺失或错误（HTTP 401）")
    if status_code == 403:
        return CPAManagementAuthError("CPA 远程管理未开启或当前来源被拒绝（HTTP 403）")
    if status_code == 404:
        return CPAManagementConfigError("CPA 管理接口不存在（HTTP 404）")
    return CPAManagementError(f"CPA 管理接口返回 HTTP {status_code}")


def test_connection(
    base_url: str,
    *,
    key: str = "",
    config: dict[str, Any] | None = None,
    session: Any = requests,
    timeout: float = 20.0,
) -> dict[str, Any]:
    url = normalize_management_url(base_url)
    management_key = resolve_management_key(config, explicit_key=key)
    try:
        response = session.get(url, headers=_headers(management_key), timeout=timeout)
    except Exception as exc:
        raise CPAManagementError("无法连接 CPA 管理接口") from exc
    if int(response.status_code) != 200:
        raise _safe_status_error(int(response.status_code))
    try:
        payload = response.json()
    except Exception as exc:
        raise CPAManagementError("CPA 管理接口返回了无效 JSON") from exc
    return {
        "ok": True,
        "url": redact_management_url(url),
        "version": str(response.headers.get("X-CPA-VERSION") or "").strip(),
        "count": len(payload.get("files") or []) if isinstance(payload, dict) else 0,
    }


def _read_auth_file(path: str | os.PathLike[str]) -> tuple[Path, bytes]:
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise CPAManagementConfigError("CPA 认证文件不存在")
    if file_path.suffix.lower() != ".json" or file_path.name in {".", ".."}:
        raise CPAManagementConfigError("CPA 认证文件必须是 .json")
    size = file_path.stat().st_size
    if size <= 0:
        raise CPAManagementConfigError("CPA 认证文件为空")
    if size > MAX_AUTH_FILE_BYTES:
        raise CPAManagementConfigError("CPA 认证文件超过 2 MiB")
    data = file_path.read_bytes()
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise CPAManagementConfigError("CPA 认证文件不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise CPAManagementConfigError("CPA 认证文件必须是 JSON 对象")
    return file_path, data


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


def upload_auth_file(
    local_path: str | os.PathLike[str],
    *,
    config: dict[str, Any] | None = None,
    key: str = "",
    session: Any = requests,
    sleep: Callable[[float], None] = time.sleep,
    log_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cfg = config or {}
    log = log_callback or (lambda _message: None)
    try:
        file_path, data = _read_auth_file(local_path)
        base_url = str(cfg.get("cpa_management_base_url") or "").strip()
        url = normalize_management_url(base_url)
        management_key = resolve_management_key(cfg, explicit_key=key)
        headers = _headers(management_key)
        headers["Content-Type"] = "application/json"
        timeout = max(float(cfg.get("cpa_management_timeout_sec") or 20), 1.0)
        retries = max(int(cfg.get("cpa_management_retry_count") or 3), 0)
    except CPAManagementError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "CPA 管理上传配置无效"}

    safe_target = redact_management_url(url)
    for attempt in range(retries + 1):
        try:
            response = session.post(
                url,
                params={"name": file_path.name},
                data=data,
                headers=headers,
                timeout=timeout,
            )
            status = int(response.status_code)
            if status == 200:
                try:
                    payload = response.json()
                except Exception:
                    payload = None
                if isinstance(payload, dict) and payload.get("status") == "ok":
                    log(f"[cpa] 管理 API 上传成功: {safe_target} file={file_path.name}")
                    return {
                        "ok": True,
                        "name": file_path.name,
                        "target": safe_target,
                        "attempts": attempt + 1,
                    }
                return {"ok": False, "error": "CPA 上传响应格式无效"}
            if not _retryable_status(status):
                return {"ok": False, "error": str(_safe_status_error(status)), "status": status}
            error_text = f"CPA 管理接口返回 HTTP {status}"
        except Exception:
            error_text = "无法连接 CPA 管理接口"

        if attempt >= retries:
            log(f"[cpa] 管理 API 上传失败，本地文件已保留: {file_path.name} ({error_text})")
            return {"ok": False, "error": error_text, "attempts": attempt + 1}
        delay = 2**attempt
        log(f"[cpa] 管理 API 暂时不可用，{delay}s 后重试（{attempt + 1}/{retries}）")
        sleep(delay)

    return {"ok": False, "error": "CPA 管理上传失败"}
