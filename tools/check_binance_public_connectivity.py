#!/usr/bin/env python3
"""
Binance public connectivity checker — stdlib only, no API keys, no orders.
Exit 0 = all pass, Exit 2 = one or more failures.
"""
import json
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
]

REST_ENDPOINTS = [
    ("https://api.binance.com/api/v3/time",         "spot_time"),
    ("https://fapi.binance.com/fapi/v1/time",       "futures_time"),
    ("https://api.binance.com/api/v3/exchangeInfo", "spot_exchangeInfo"),
    ("https://fapi.binance.com/fapi/v1/exchangeInfo","futures_exchangeInfo"),
]

PUBLIC_IP_URLS = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
]

TIMEOUT = 10


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


def fetch_url(url: str, label: str) -> dict:
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
            }
    except Exception as e:
        return {"status": "FAIL", "label": label, "url": url, "error": str(e)}


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

    print("[REST] Fetching public endpoints...", file=sys.stderr)
    for url, label in REST_ENDPOINTS:
        r = fetch_url(url, label)
        results["rest"].append(r)
        print(f"  REST {label}: {r['status']}", file=sys.stderr)

    print("[IP] Detecting public IP...", file=sys.stderr)
    results["public_ip"] = public_ip()
    print(f"  Public IP: {results['public_ip']}", file=sys.stderr)

    # Summary
    dns_fail  = sum(1 for r in results["dns"]  if r["status"] != "OK")
    tls_fail  = sum(1 for r in results["tls"]  if r["status"] != "OK")
    rest_fail = sum(1 for r in results["rest"] if r["status"] != "OK")
    ip_fail   = 1 if results["public_ip"]["status"] != "OK" else 0
    total_fail = dns_fail + tls_fail + rest_fail + ip_fail

    results["summary"] = {
        "dns_fail":  dns_fail,
        "tls_fail":  tls_fail,
        "rest_fail": rest_fail,
        "ip_fail":   ip_fail,
        "total_fail": total_fail,
        "verdict": "PASS" if total_fail == 0 else "FAIL",
    }

    print(json.dumps(results, indent=2))
    sys.exit(0 if total_fail == 0 else 2)


if __name__ == "__main__":
    main()
