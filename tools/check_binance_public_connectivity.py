#!/usr/bin/env python3
"""
Binance public connectivity checker — stdlib only, no API keys, no orders.
Exit 0 = all pass, Exit 2 = one or more failures.
"""
import json
import os
import base64
import socket
import ssl
import sys
import time
import urllib.request
import urllib.error

HOSTS = [
    "api.binance.com",
    "fapi.binance.com",
    "stream.binance.com",
    "fstream.binance.com",
    "ws-api.binance.com",
    "ws-fapi.binance.com",
]

REST_FALLBACK_ENV = "BINANCE_REST_FALLBACK_ALLOWED"

REST_FALLBACK_ENDPOINTS = [
    ("https://api.binance.com/api/v3/time",         "spot_time"),
    ("https://fapi.binance.com/fapi/v1/time",       "futures_time"),
    ("https://api.binance.com/api/v3/exchangeInfo", "spot_exchangeInfo"),
    ("https://fapi.binance.com/fapi/v1/exchangeInfo","futures_exchangeInfo"),
]

PUBLIC_IP_URLS = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
]

WS_HANDSHAKE_TARGETS = [
    ("fstream.binance.com", 443, "/ws/btcusdt@bookTicker", "usdm_bookticker_stream"),
    ("fstream.binance.com", 443, "/ws/btcusdt@aggTrade", "usdm_agg_trade_stream"),
    ("ws-fapi.binance.com", 443, "/ws-fapi/v1", "usdm_websocket_api"),
]

TIMEOUT = 10


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


def dns_check(host: str) -> dict:
    t0 = time.monotonic()
    try:
        addrs = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ip = addrs[0][4][0]
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "OK", "host": host, "ip": ip, "elapsed_ms": elapsed_ms}
    except Exception as e:
        return {"status": "FAIL", "host": host, "error": str(e)}


def tls_check(host: str, port: int = 443) -> dict:
    t0 = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=TIMEOUT) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                cert = s.getpeercert()
                subject = dict(x[0] for x in cert.get("subject", []))
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                return {
                    "status": "OK",
                    "host": host,
                    "port": port,
                    "tls_version": s.version(),
                    "cert_cn": subject.get("commonName", ""),
                    "elapsed_ms": elapsed_ms,
                }
    except Exception as e:
        return {"status": "FAIL", "host": host, "port": port, "error": str(e)}


def websocket_handshake_check(host: str, port: int, path: str, label: str) -> dict:
    t0 = time.monotonic()
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: BinanceConnectivityCheck/1.0\r\n"
        "\r\n"
    ).encode("ascii")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=TIMEOUT) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                s.settimeout(TIMEOUT)
                s.sendall(request)
                response = s.recv(2048).decode("iso-8859-1", errors="replace")
        status_line = response.splitlines()[0] if response else ""
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        ok = " 101 " in f" {status_line} "
        return {
            "status": "OK" if ok else "FAIL",
            "label": label,
            "host": host,
            "port": port,
            "path": path,
            "status_line": status_line,
            "elapsed_ms": elapsed_ms,
            "transport_role": "websocket_primary",
            "rest_fallback_used": False,
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "label": label,
            "host": host,
            "port": port,
            "path": path,
            "error": str(e),
            "transport_role": "websocket_primary",
            "rest_fallback_used": False,
        }


def fetch_url(url: str, label: str) -> dict:
    fallback = binance_rest_fallback_decision(
        url,
        fallback_reason=f"connectivity_check_websocket_primary_{label}_rest_fallback",
    )
    if "binance.com" in url and not fallback["request_allowed"]:
        return {
            "status": "SKIPPED",
            "label": label,
            "url": url,
            "request_attempted": False,
            "transport_role": "rest_fallback_only",
            "skip_reason": "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "rest_used_as_primary": False,
            "rest_fallback_reason": fallback["rest_fallback_reason"],
            "required_env": f"{REST_FALLBACK_ENV}=true",
        }
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BinanceConnectivityCheck/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            # Try parsing as JSON
            try:
                data = json.loads(body)
                parsed = True
            except Exception:
                data = body[:200]
                parsed = False
            return {
                "status": "OK",
                "label": label,
                "url": url,
                "http_status": resp.status,
                "json_parsed": parsed,
                "elapsed_ms": elapsed_ms,
                "sample": str(data)[:200],
                "request_attempted": True,
                "transport_role": "rest_fallback_only" if "binance.com" in url else "public_ip_probe",
            }
    except Exception as e:
        return {
            "status": "FAIL",
            "label": label,
            "url": url,
            "error": str(e),
            "request_attempted": True,
            "transport_role": "rest_fallback_only" if "binance.com" in url else "public_ip_probe",
        }


def public_ip() -> dict:
    for url in PUBLIC_IP_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BinanceConnectivityCheck/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                ip = resp.read(64).decode("utf-8", errors="replace").strip()
                return {"status": "OK", "ip": ip, "source": url}
        except Exception:
            continue
    return {"status": "FAIL", "error": "All public IP sources failed"}


def main():
    results = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "executable": sys.executable,
        "dns": [],
        "tls": [],
        "websocket": [],
        "rest": [],
        "public_ip": {},
        "summary": {},
    }

    print("[DNS] Checking hosts...", file=sys.stderr)
    for host in HOSTS:
        r = dns_check(host)
        results["dns"].append(r)
        print(f"  DNS {host}: {r['status']}", file=sys.stderr)

    print("[TLS] Checking TLS handshakes...", file=sys.stderr)
    for host in HOSTS:
        r = tls_check(host, 443)
        results["tls"].append(r)
        print(f"  TLS {host}:443 {r['status']}", file=sys.stderr)

    print("[WEBSOCKET] Checking primary Binance WebSocket handshakes...", file=sys.stderr)
    for host, port, path, label in WS_HANDSHAKE_TARGETS:
        r = websocket_handshake_check(host, port, path, label)
        results["websocket"].append(r)
        print(f"  WS {label}: {r['status']}", file=sys.stderr)

    print("[REST-FALLBACK] Checking whether public REST fallback is allowed...", file=sys.stderr)
    for url, label in REST_FALLBACK_ENDPOINTS:
        r = fetch_url(url, label)
        results["rest"].append(r)
        print(f"  REST fallback {label}: {r['status']}", file=sys.stderr)

    print("[IP] Detecting public IP...", file=sys.stderr)
    results["public_ip"] = public_ip()
    print(f"  Public IP: {results['public_ip']}", file=sys.stderr)

    # Summary
    dns_fail  = sum(1 for r in results["dns"]  if r["status"] != "OK")
    tls_fail  = sum(1 for r in results["tls"]  if r["status"] != "OK")
    websocket_fail = sum(1 for r in results["websocket"] if r["status"] != "OK")
    rest_attempted = sum(1 for r in results["rest"] if r.get("request_attempted") is True)
    rest_skipped = sum(1 for r in results["rest"] if r["status"] == "SKIPPED")
    rest_fail = sum(1 for r in results["rest"] if r.get("request_attempted") is True and r["status"] != "OK")
    ip_fail   = 1 if results["public_ip"]["status"] != "OK" else 0
    total_fail = dns_fail + tls_fail + websocket_fail + rest_fail + ip_fail

    results["summary"] = {
        "dns_fail":  dns_fail,
        "tls_fail":  tls_fail,
        "websocket_fail": websocket_fail,
        "rest_fail": rest_fail,
        "rest_attempted": rest_attempted,
        "rest_skipped_websocket_primary": rest_skipped,
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "primary_transport": "binance_public_websocket_tls",
        "rest_transport_role": "fallback_only",
        "ip_fail":   ip_fail,
        "total_fail": total_fail,
        "verdict": "PASS" if total_fail == 0 else "FAIL",
    }

    print(json.dumps(results, indent=2))
    sys.exit(0 if total_fail == 0 else 2)


if __name__ == "__main__":
    main()
