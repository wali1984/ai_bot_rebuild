# PIA GUI Action Required

The bot Python traffic is **not** using the PIA VPN IP.

## Root Cause (confirmed by cgroup inspection)

PIA split tunnel IS enabled in settings with `mode=include` for the correct Python paths.
However, `/opt/piavpn/etc/cgroup/net_cls/piavpnonly/tasks` is **EMPTY** (0 PIDs).

This means PIA is not routing any process through the VPN tunnel.

Two sub-causes:

1. `/usr/bin/python3.12` — the actual binary realpath for ALL Python executables — is **NOT** in the
   PIA split tunnel rules. Only `/usr/bin/python3` (symlink) is in the rules. PIA's process monitor
   matches by EXE path from `/proc/PID/exe`, which resolves to `/usr/bin/python3.12`, not the symlink.

2. All existing bot processes were launched before PIA's split tunnel could track them.
   PIA's daemon only catches processes at launch time using `execve` interception.

## Fix: PIA GUI Steps

**Step A — Disconnect VPN first**

Open PIA GUI → click Disconnect (or `piactl disconnect`).

**Step B — Add `/usr/bin/python3.12` to split tunnel**

1. Open PIA GUI → Settings → Split Tunnel.
2. Confirm Split Tunnel is **Enabled**.
3. The "mode" for existing Python rules should be **Only VPN** (Include).
4. Add the following **additional** path and set to **Only VPN**:
   - `/usr/bin/python3.12`
5. Existing rules to verify are already present:
   - `/home/wali/Desktop/AI BOT/venv/bin/python3`  → Only VPN
   - `/home/wali/Desktop/AI BOT/venv/bin/python`   → Only VPN
   - `/home/wali/Desktop/AI BOT/venv/bin/python3.12` → Only VPN
   - `/usr/bin/python3`  → Only VPN
   - `/usr/bin/python`   → Only VPN (if present)
6. Set "All Other Apps" / default to: **Bypass VPN** (regular internet).

**Step C — Reconnect VPN**

1. Reconnect PIA to Japan/Tokyo (`dedicated-jp-tokyo-181.214.244.184`).
2. Wait 5–10 seconds for PIA daemon to re-apply cgroup rules.

**Step D — Immediate fix for already-running bot processes (requires sudo)**

After reconnecting, existing Python processes are STILL not in the VPN cgroup because
PIA only tracks new process launches. Use this command to move them immediately:

```bash
sudo bash -c '
CGROUP=/opt/piavpn/etc/cgroup/net_cls/piavpnonly/tasks
for pid in 5131 142712 142970 143125 143308 146815 146816 146817 148574 148810 148941 148942 148943 149049 149111 149186 149257 2254001; do
  kill -0 $pid 2>/dev/null && echo $pid > "$CGROUP" && echo "Added PID $pid" || echo "PID $pid gone"
done
'
```

**Step E — Verify**

```bash
# Check tasks count is now > 0
wc -l /opt/piavpn/etc/cgroup/net_cls/piavpnonly/tasks

# Test public IP from venv Python (should now show 181.214.244.184, not 98.116.148.30)
"/home/wali/Desktop/AI BOT/venv/bin/python3" "$HOME/Desktop/AI BOT REBUILD/tools/check_python_route_to_binance.py" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
```

Expected after fix:
- `public_ip` = `181.214.244.184` (PIA Tokyo VPN IP)
- `spot_status` = `200`
- `futures_status` = `200`

## Do NOT

- Do not apply a permanent `ip route` default metric change.
- Do not add `default via 10.178.18.1 dev tun0 metric 50` permanently.
- Do not restart trainer/trader/orchestrator until it is safe and explicitly approved.

## Current PIA Settings Confirmed

```
defaultRoute:         false  ← correct for split tunnel mode
splitTunnelEnabled:   true
splitTunnelDNS:       true
routedPacketsOnVPN:   true
allowLAN:             true
splitTunnelRules:
  /home/wali/Desktop/AI BOT/venv/bin/python   include (Only VPN)
  /home/wali/Desktop/AI BOT/venv/bin/python3  include (Only VPN)
  /home/wali/Desktop/AI BOT/venv/bin/python3.12 include (Only VPN)
  /usr/bin/python   include (Only VPN)
  /usr/bin/python3  include (Only VPN)
  MISSING: /usr/bin/python3.12  ← this is what all of the above resolve to
```
