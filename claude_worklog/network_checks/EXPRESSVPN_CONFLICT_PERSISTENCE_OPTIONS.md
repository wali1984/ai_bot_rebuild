# ExpressVPN Conflict Persistence Options

Generated: 2026-04-30T04:07 UTC

## Background

When ExpressVPN was uninstalled, its net_cls cgroup v1 kernel mount was removed.
PIA depended on this mount via a symlink:

  /opt/piavpn/etc/cgroup/net_cls -> /opt/expressvpn/etc/cgroup/net_cls  (BROKEN AFTER UNINSTALL)

This broke PIA's split tunnel mechanism — new python3.12 processes were no longer assigned
to piavpnonly cgroup, causing them to bypass VPN and hit Binance geo-block (HTTP 451).

The broken symlink has been replaced with a real directory and the cgroup remounted this session.
That fix is NOT persistent across reboot or if PIA daemon restarts and re-checks the mount.

---

## Option A — /etc/fstab entry (Recommended — simplest, persistent)

Add to /etc/fstab:

  none  /opt/piavpn/etc/cgroup/net_cls  cgroup  net_cls  0  0

Command to add (as root):
  echo "none  /opt/piavpn/etc/cgroup/net_cls  cgroup  net_cls  0  0" | sudo tee -a /etc/fstab
  sudo mount -a  # verify it works

This mounts the net_cls cgroup v1 at PIA's expected path on every boot, before PIA daemon starts.

---

## Option B — systemd mount unit (Alternative if fstab doesn't work)

Create /etc/systemd/system/opt-piavpn-etc-cgroup-net_cls.mount with:

  [Unit]
  Description=net_cls cgroup v1 mount for PIA split tunnel
  DefaultDependencies=no
  Before=piavpnd.service

  [Mount]
  What=none
  Where=/opt/piavpn/etc/cgroup/net_cls
  Type=cgroup
  Options=net_cls

  [Install]
  WantedBy=multi-user.target

Commands:
  sudo systemctl daemon-reload
  sudo systemctl enable opt-piavpn-etc-cgroup-net_cls.mount
  sudo systemctl start opt-piavpn-etc-cgroup-net_cls.mount

---

## Option C — rc.local one-liner (Fallback, not recommended)

Add to /etc/rc.local (before exit 0):
  mount -t cgroup -o net_cls none /opt/piavpn/etc/cgroup/net_cls/ 2>/dev/null || true

---

## Verification After Any Option

After applying and rebooting, verify:
  mount | grep piavpn          # should show cgroup type at /opt/piavpn/etc/cgroup/net_cls
  /usr/bin/python3.12 -c "print(open('/proc/self/cgroup').readline())"
  # Should print: 1:net_cls:/piavpnonly
  /usr/bin/python3.12 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read())"
  # Should return PIA VPN IP (181.214.244.184 or current VPN IP)

---

## Current Status

- ExpressVPN: UNINSTALLED (no processes, no /opt/expressvpn)
- net_cls cgroup v1: MOUNTED at /opt/piavpn/etc/cgroup/net_cls (manually this session)
- PIA: Connected, piavpnonly/piavpnexclusions subcgroups active
- Fresh python3.12: IN piavpnonly, gets VPN IP ✅
- Existing bot processes (started Apr25-26): NOT in piavpnonly — require restart

Do not implement any persistence option without explicit instruction.
