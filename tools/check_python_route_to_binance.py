#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import base64
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REST_FALLBACK_ENV = "BINANCE_REST_FALLBACK_ALLOWED"


def binance_rest_fallback_allowed() -> bool:
    return os.environ.get(REST_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def binance_rest_fallback_decision(url: str, *, fallback_reason: str) -> dict:
    allowed = binance_rest_fallback_allowed() and bool(fallback_reason)
    return {
        "request_allowed": allowed,
        "rest_fallback_reason": fallback_reason,
        "rest_used_as_primary": False,
        "blocked_reason": None if allowed else "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
    }


def fetch(
    url: str,
    timeout: float = 12.0,
    *,
    fallback_reason: str = "route_check_websocket_primary_probe_rest_fallback",
) -> dict:
    fallback = binance_rest_fallback_decision(url, fallback_reason=fallback_reason)
    if "binance.com" in url and not fallback["request_allowed"]:
        return {
            "ok": False,
            "status": "SKIPPED",
            "elapsed_ms": 0.0,
            "body_prefix": "",
            "error": "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "request_attempted": False,
            "transport_role": "rest_fallback_only",
            "rest_used_as_primary": False,
            "rest_fallback_reason": fallback["rest_fallback_reason"],
            "required_env": f"{REST_FALLBACK_ENV}=true",
        }
    start = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-bot-route-check/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(300).decode("utf-8", errors="replace")
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "elapsed_ms": round((time.time() - start) * 1000, 2),
                "body_prefix": body,
                "error": None,
                "request_attempted": True,
                "transport_role": "rest_fallback_only" if "binance.com" in url else "public_ip_probe",
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(300).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "status": e.code,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "body_prefix": body,
            "error": repr(e),
            "request_attempted": True,
            "transport_role": "rest_fallback_only" if "binance.com" in url else "public_ip_probe",
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "body_prefix": "",
            "error": repr(e),
            "request_attempted": True,
            "transport_role": "rest_fallback_only" if "binance.com" in url else "public_ip_probe",
        }


def dns(host: str) -> dict:
    try:
        return {
            "ok": True,
            "host": host,
            "ips": sorted({x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})[:10],
        }
    except Exception as e:
        return {"ok": False, "host": host, "error": repr(e)}


def tls(host: str, port: int = 443) -> dict:
    start = time.time()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=12) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                return {
                    "ok": True,
                    "host": host,
                    "port": port,
                    "tls_version": ssock.version(),
                    "elapsed_ms": round((time.time() - start) * 1000, 2),
                }
    except Exception as e:
        return {
            "ok": False,
            "host": host,
            "port": port,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "error": repr(e),
        }


def websocket_handshake(host: str, path: str, *, port: int = 443, timeout: float = 12.0) -> dict:
    start = time.time()
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: ai-bot-route-check/1.0\r\n"
        "\r\n"
    ).encode("ascii")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.settimeout(timeout)
                ssock.sendall(request)
                response = ssock.recv(2048).decode("iso-8859-1", errors="replace")
        status_line = response.splitlines()[0] if response else ""
        ok = " 101 " in f" {status_line} "
        return {
            "ok": ok,
            "status": "OK" if ok else "FAIL",
            "host": host,
            "path": path,
            "port": port,
            "status_line": status_line,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "transport_role": "websocket_primary",
            "rest_fallback_used": False,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "FAIL",
            "host": host,
            "path": path,
            "port": port,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "error": repr(e),
            "transport_role": "websocket_primary",
            "rest_fallback_used": False,
        }


def main() -> int:
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "version": sys.version,
        "public_ip": fetch("https://api.ipify.org"),
        "dns": {
            "api.binance.com": dns("api.binance.com"),
            "fapi.binance.com": dns("fapi.binance.com"),
            "stream.binance.com": dns("stream.binance.com"),
            "fstream.binance.com": dns("fstream.binance.com"),
            "ws-fapi.binance.com": dns("ws-fapi.binance.com"),
        },
        "tls": {
            "api.binance.com": tls("api.binance.com", 443),
            "fapi.binance.com": tls("fapi.binance.com", 443),
            "stream.binance.com_443": tls("stream.binance.com", 443),
            "fstream.binance.com_443": tls("fstream.binance.com", 443),
            "ws-fapi.binance.com_443": tls("ws-fapi.binance.com", 443),
        },
        "websocket_primary": {
            "usdm_bookticker_stream": websocket_handshake("fstream.binance.com", "/ws/btcusdt@bookTicker"),
            "usdm_agg_trade_stream": websocket_handshake("fstream.binance.com", "/ws/btcusdt@aggTrade"),
            "usdm_websocket_api": websocket_handshake("ws-fapi.binance.com", "/ws-fapi/v1"),
        },
        "rest_fallback": {
            "spot_time": fetch("https://api.binance.com/api/v3/time"),
            "futures_time": fetch("https://fapi.binance.com/fapi/v1/time"),
        },
    }

    ws_ok = all(row["ok"] for row in result["websocket_primary"].values())
    rest_rows = result["rest_fallback"]
    rest_attempted = any(row.get("request_attempted") is True for row in rest_rows.values())
    rest_ok = all(row["ok"] for row in rest_rows.values()) if rest_attempted else True
    result["summary"] = {
        "public_ip": result["public_ip"].get("body_prefix", "").strip(),
        "spot_rest_fallback_status": result["rest_fallback"]["spot_time"].get("status"),
        "futures_rest_fallback_status": result["rest_fallback"]["futures_time"].get("status"),
        "primary_transport": "binance_websocket_tls",
        "websocket_primary_ok": ws_ok,
        "rest_transport_role": "fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_attempted": rest_attempted,
        "rest_ok": rest_ok,
    }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["websocket_primary_ok"] and result["summary"]["rest_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
