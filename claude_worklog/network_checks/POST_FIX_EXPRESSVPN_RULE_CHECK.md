# Post-Fix ExpressVPN Rule Check
Generated: 2026-04-30T00:02:39-04:00

## ExpressVPN processes
wali     2402556  0.0  0.0   8308  2084 pts/22   S+   00:02   0:00 tee claude_worklog/network_checks/POST_FIX_EXPRESSVPN_RULE_CHECK.md

## ExpressVPN service
inactive
unit not found
not-found
unit not found

## Problem chain
chain not found

## Search for cgroup 1384 reject
-A piavpn.r.100.tagVpnOnly -m cgroup --cgroup 1384 -j MARK --set-xmark 0x3212/0xffffffff
-A piavpn.r.100.blockAll -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.100.protectLoopback ! -i lo -o lo -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.310.blockDNS -p udp -m udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.310.blockDNS -p tcp -m tcp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.320.allowDNS -d 10.0.0.243/32 -p udp -m cgroup --cgroup 1384 -m udp --dport 53 -j ACCEPT
-A piavpn.r.320.allowDNS -d 10.0.0.243/32 -p tcp -m cgroup --cgroup 1384 -m tcp --dport 53 -j ACCEPT
-A piavpn.r.320.allowDNS -p udp -m cgroup --cgroup 1384 -m udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.320.allowDNS -p tcp -m cgroup --cgroup 1384 -m tcp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.320.allowDNS -d 10.0.0.243/32 -p udp -m cgroup ! --cgroup 1384 -m udp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.320.allowDNS -d 10.0.0.243/32 -p tcp -m cgroup ! --cgroup 1384 -m tcp --dport 53 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.340.blockVpnOnly -m cgroup --cgroup 1384 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.350.allowHnsd -m owner --gid-owner 1004 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.350.cgAllowHnsd -p tcp -m owner --gid-owner 1004 -m cgroup --cgroup 1384 -m multiport --dports 53,13038 -j ACCEPT
-A piavpn.r.350.cgAllowHnsd -p udp -m owner --gid-owner 1004 -m cgroup --cgroup 1384 -m multiport --dports 53,13038 -j ACCEPT
-A piavpn.r.350.cgAllowHnsd -m owner --gid-owner 1004 -j REJECT --reject-with icmp-port-unreachable
-A piavpn.r.80.splitDNS -p udp -m cgroup --cgroup 1384 -m udp --dport 53 -j DNAT --to-destination 10.0.0.243:53
-A piavpn.r.80.splitDNS -p tcp -m cgroup --cgroup 1384 -m tcp --dport 53 -j DNAT --to-destination 10.0.0.243:53
-A piavpn.r.90.snatDNS -p udp -m cgroup --cgroup 1384 -m udp --dport 53 -j SNAT --to-source 10.178.18.2
-A piavpn.r.90.snatDNS -p tcp -m cgroup --cgroup 1384 -m tcp --dport 53 -j SNAT --to-source 10.178.18.2
