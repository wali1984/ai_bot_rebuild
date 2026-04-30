#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def fetch(url: str, timeout: float = 12.0) -> dict:
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
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
            "body_prefix": "",
            "error": repr(e),
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
        },
        "tls": {
            "api.binance.com": tls("api.binance.com", 443),
            "fapi.binance.com": tls("fapi.binance.com", 443),
            "stream.binance.com_443": tls("stream.binance.com", 443),
            "fstream.binance.com_443": tls("fstream.binance.com", 443),
        },
        "rest": {
            "spot_time": fetch("https://api.binance.com/api/v3/time"),
            "futures_time": fetch("https://fapi.binance.com/fapi/v1/time"),
        },
    }

    result["summary"] = {
        "public_ip": result["public_ip"].get("body_prefix", "").strip(),
        "spot_status": result["rest"]["spot_time"].get("status"),
        "futures_status": result["rest"]["futures_time"].get("status"),
        "rest_ok": result["rest"]["spot_time"]["ok"] and result["rest"]["futures_time"]["ok"],
    }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["rest_ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
