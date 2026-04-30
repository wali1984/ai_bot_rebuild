#!/usr/bin/env python3
"""
WebSocket TLS port checker — stdlib only.
Checks TLS connectivity to Binance WS endpoints on ports 443 and 9443.
"""
import json
import socket
import ssl
import sys
import time

WS_TARGETS = [
    ("stream.binance.com",  443),
    ("stream.binance.com",  9443),
    ("fstream.binance.com", 443),
    ("ws-api.binance.com",  443),
]

TIMEOUT = 10


def ws_tls_check(host: str, port: int) -> dict:
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


def main():
    results = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "executable": sys.executable,
        "ws_tls": [],
        "summary": {},
    }

    for host, port in WS_TARGETS:
        r = ws_tls_check(host, port)
        results["ws_tls"].append(r)
        print(f"WS TLS {host}:{port} → {r['status']}", file=sys.stderr)

    fail = sum(1 for r in results["ws_tls"] if r["status"] != "OK")
    results["summary"] = {
        "fail": fail,
        "verdict": "PASS" if fail == 0 else "FAIL",
    }

    print(json.dumps(results, indent=2))
    sys.exit(0 if fail == 0 else 2)


if __name__ == "__main__":
    main()
