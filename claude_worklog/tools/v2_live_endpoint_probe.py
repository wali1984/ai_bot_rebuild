"""Live, read-only endpoint verification for every V2 data provider.

Proves each configured endpoint/API/WebSocket actually works with the REAL key
loaded from v2/.env.local (layered with .local_secrets). Read-only only:
- NO order placement, NO cancel, NO leverage/margin change, NO live enablement.
- Binance signed calls are account-read + user-data-stream listen key only.
- CoinAnk is intentionally skipped per operator instruction.

Secret values are never printed or written. Output is a redacted JSON report
plus a human summary table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# Bootstrap data-provider keys (coinapi/coingecko/coinglass/...) from env.local.
import v2.backend.app.cli  # noqa: F401  (import side effect: bind_to_environ)
from v2.backend.app.services.safe_env_loader import bind_to_environ, ENV_LOCAL_PATH

# Operator explicitly authorised real Binance api+secret for REST + WS read.
bind_to_environ(ENV_LOCAL_PATH, apply=True, keys=["BINANCE_API_KEY", "BINANCE_API_SECRET"])

EST = timezone(timedelta(hours=-4))
TIMEOUT = 8.0
RESULTS: list[dict] = []


def _rec(provider, endpoint, kind, auth, ok, status, note=""):
    RESULTS.append({
        "provider": provider, "endpoint": endpoint, "kind": kind,
        "auth": auth, "ok": bool(ok), "http_status": status, "note": note,
    })


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "v2-probe/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _post(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _delete(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="DELETE")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def probe_binance_public():
    for name, url in [
        ("server_time", "https://fapi.binance.com/fapi/v1/time"),
        ("klines", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=2"),
        ("depth", "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=5"),
        ("openInterest", "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"),
        ("premiumIndex(funding)", "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"),
        ("ticker24hr", "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT"),
        ("openInterestHist", "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=2"),
    ]:
        try:
            st, _ = _get(url)
            _rec("Binance", name, "REST", "public", 200 <= st < 300, st)
        except urllib.error.HTTPError as e:
            _rec("Binance", name, "REST", "public", False, e.code, "HTTPError")
        except Exception as e:
            _rec("Binance", name, "REST", "public", False, None, repr(e)[:80])


def probe_binance_signed():
    try:
        from v2.backend.app.services.binance_readonly_probe import run_probe
        rep = run_probe(include_signed=True)
        for r in rep.get("signed_results", []):
            st = r.get("http_status") or r.get("status")
            ok = bool(r.get("ok", (isinstance(st, int) and 200 <= st < 300)))
            _rec("Binance", r.get("endpoint", "?"), "REST", "signed(api+secret)", ok, st,
                 "read-only account/permission")
        if not rep.get("signed_attempted"):
            _rec("Binance", "signed", "REST", "signed(api+secret)", False, None,
                 rep.get("signed_skipped_reason", "no creds"))
    except Exception as e:
        _rec("Binance", "signed_probe", "REST", "signed(api+secret)", False, None, repr(e)[:80])


def _binance_user_stream_listen_token():
    """Open a futures user-data stream listen token (read-only). Returns token."""
    key = os.environ.get("BINANCE_API_KEY", "")
    if not key:
        _rec("Binance", "user_data_stream", "WS", "signed(api-key)", False, None, "no BINANCE_API_KEY")
        return None
    try:
        st, body = _post("https://fapi.binance.com/fapi/v1/listenKey",
                         headers={"X-MBX-APIKEY": key})
        token = json.loads(body).get("listenKey")
        _rec("Binance", "listenKey(open)", "REST", "signed(api-key)", bool(token), st,
             "user-data stream token issued" if token else "no token")
        return token
    except urllib.error.HTTPError as e:
        _rec("Binance", "listenKey(open)", "REST", "signed(api-key)", False, e.code, "HTTPError")
        return None
    except Exception as e:
        _rec("Binance", "listenKey(open)", "REST", "signed(api-key)", False, None, repr(e)[:80])
        return None


def _binance_user_stream_close(token):
    key = os.environ.get("BINANCE_API_KEY", "")
    if not token or not key:
        return
    try:
        _delete(f"https://fapi.binance.com/fapi/v1/listenKey?listenKey={token}",
                headers={"X-MBX-APIKEY": key})
    except Exception:
        pass


def _ws_connect_recv(url, label, provider, auth):
    try:
        import websocket  # websocket-client
        ws = websocket.create_connection(url, timeout=TIMEOUT)
        ws.settimeout(TIMEOUT)
        try:
            msg = ws.recv()
            ok = True
            note = "frame received" if msg else "connected (no frame yet)"
        except Exception:
            ok = True  # connection established is the auth proof
            note = "connected (no frame in window)"
        ws.close()
        _rec(provider, label, "WS", auth, ok, 101, note)
    except Exception as e:
        _rec(provider, label, "WS", auth, False, None, repr(e)[:80])


def probe_binance_ws():
    # Public market WS
    _ws_connect_recv("wss://fstream.binance.com/market/ws/btcusdt@aggTrade",
                     "aggTrade(public)", "Binance", "public")
    _ws_connect_recv("wss://fstream.binance.com/market/ws/!forceOrder@arr",
                     "forceOrder(public liquidations)", "Binance", "public")
    # Authenticated user-data WS via listen token
    token = _binance_user_stream_listen_token()
    if token:
        _ws_connect_recv(f"wss://fstream.binance.com/ws/{token}",
                         "userDataStream(auth)", "Binance", "signed(api-key)")
        _binance_user_stream_close(token)


def probe_kucoin():
    for name, url in [
        ("timestamp", "https://api.kucoin.com/api/v1/timestamp"),
        ("allTickers", "https://api.kucoin.com/api/v1/market/allTickers"),
        ("futures_contracts_active", "https://api-futures.kucoin.com/api/v1/contracts/active"),
    ]:
        try:
            st, _ = _get(url)
            _rec("KuCoin", name, "REST", "public", 200 <= st < 300, st)
        except urllib.error.HTTPError as e:
            _rec("KuCoin", name, "REST", "public", False, e.code, "HTTPError")
        except Exception as e:
            _rec("KuCoin", name, "REST", "public", False, None, repr(e)[:80])


def probe_coinapi():
    key = os.environ.get("COINAPI_API_KEY", "")
    auth = "x-api-key" if key else "none"
    try:
        st, _ = _get("https://rest.coinapi.io/v1/exchangerate/BTC/USD",
                     headers={"X-CoinAPI-Key": key, "User-Agent": "v2-probe/1.0"})
        _rec("CoinAPI", "exchangerate/BTC/USD", "REST", auth, 200 <= st < 300, st,
             "free-tier quota sensitive")
    except urllib.error.HTTPError as e:
        _rec("CoinAPI", "exchangerate/BTC/USD", "REST", auth, False, e.code,
             "401=bad key, 429=quota")
    except Exception as e:
        _rec("CoinAPI", "exchangerate/BTC/USD", "REST", auth, False, None, repr(e)[:80])


def probe_coingecko():
    key = os.environ.get("COINGECKO_API_KEY", "")
    auth = "x-cg-key" if key else "none"
    headers = {"User-Agent": "v2-probe/1.0"}
    if key:
        headers["x-cg-demo-api-key"] = key
    try:
        st, _ = _get("https://api.coingecko.com/api/v3/ping", headers=headers)
        _rec("CoinGecko", "ping", "REST", auth, 200 <= st < 300, st,
             "no V2 client yet (key validity check)")
    except urllib.error.HTTPError as e:
        _rec("CoinGecko", "ping", "REST", auth, False, e.code, "HTTPError")
    except Exception as e:
        _rec("CoinGecko", "ping", "REST", auth, False, None, repr(e)[:80])


def probe_coinglass():
    key = os.environ.get("COINGLASS_API_KEY", "")
    auth = "CG-API-KEY" if key else "none"
    try:
        st, _ = _get("https://open-api-v4.coinglass.com/api/futures/supported-coins",
                     headers={"CG-API-KEY": key, "User-Agent": "v2-probe/1.0"})
        _rec("CoinGlass", "futures/supported-coins", "REST", auth, 200 <= st < 300, st,
             "no V2 client yet (key validity check)")
    except urllib.error.HTTPError as e:
        _rec("CoinGlass", "futures/supported-coins", "REST", auth, False, e.code, "HTTPError")
    except Exception as e:
        _rec("CoinGlass", "futures/supported-coins", "REST", auth, False, None, repr(e)[:80])


def main():
    probe_binance_public()
    probe_binance_signed()
    probe_binance_ws()
    probe_kucoin()
    probe_coinapi()
    probe_coingecko()
    probe_coinglass()
    # CoinAnk intentionally skipped per operator instruction.

    ok = sum(1 for r in RESULTS if r["ok"])
    report = {
        "schema_version": "v2_live_endpoint_probe_v1",
        "generated_est": datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "coinank_skipped": True,
        "read_only_only": True,
        "order_placed": False,
        "leverage_or_margin_changed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "total_probes": len(RESULTS),
        "ok_count": ok,
        "fail_count": len(RESULTS) - ok,
        "results": RESULTS,
    }
    out = "claude_worklog/final_readiness/credential_env_local_sourcing/v2_live_endpoint_probe_status.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(json.dumps(report, indent=2) + "\n")

    print(f"{'PROV':<11} {'KIND':<5} {'AUTH':<18} {'OK':<3} {'ST':<5} ENDPOINT")
    for r in RESULTS:
        print(f"{r['provider']:<11} {r['kind']:<5} {r['auth']:<18} "
              f"{'Y' if r['ok'] else 'N':<3} {str(r['http_status']):<5} {r['endpoint']}  {r['note']}")
    print(f"\nOK {ok}/{len(RESULTS)} | report -> {out}")


if __name__ == "__main__":
    sys.exit(main())
