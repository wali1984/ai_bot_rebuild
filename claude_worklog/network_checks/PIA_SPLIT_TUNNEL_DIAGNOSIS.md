# PIA Split Tunnel Diagnosis
Generated: 2026-04-29T23:39:27-04:00

## piactl
/usr/local/bin/piactl
3.6.1+08339
Connected
dedicated-jp-tokyo-181.214.244.184
181.214.244.184
Unknown type: publicip

## PIA help grep
Usage: piactl [options] command [parameters...]
Command-line interface to the PIA client.  Some commands, such as connect, require that the graphical client is also running.

Options:
  --timeout, -t <seconds>  Sets timeout for one-shot commands.
  --debug, -d              Prints debug logs to stderr.
  --help, -h               Displays this help.
  -v, --version            Displays version information.

Arguments:
  command                  Command to execute
  parameters               Parameters for the command

Commands:
  background
    usage: background <enable|disable>
    Allow the killswitch and/or VPN connection to remain active in the background when the GUI client is not running.
    When enabled, the PIA daemon will stay active even if the GUI client is closed or has not been started.
    This allows `piactl connect` to be used even if the GUI client is not running.
    Disabling background activation will disconnect the VPN and deactivate killswitch if the GUI client is not running.
    
  connect
    Connects to the VPN, or reconnects to apply new settings.
    To use this command, the PIA GUI client must be running, or background mode must be enabled with `piactl background enable`
    (By default, the PIA daemon is inactive when the GUI client is not running.)
    
  dedicatedip
    usage (add): dedicatedip add <token_file>
    usage (remove): dedicatedip remove <region_id>
    Add or remove a Dedicated IP.
    To add, put the dedicated IP token in a text file (by itself), and specify that file on the command line:
        DIP20000000000000000000000000000
    (This ensures the token is not visible in the process command line or environment.)
    To remove, specify the dedicated IP region ID, as shown by `piactl get regions`, such as
    `dedicated-sweden-000.000.000.000`.
    
  disconnect
    Disconnects from the VPN.
    
  get
    usage: get <type>
    Get information from the PIA daemon.
    Available types:
      - allowlan - Whether to allow LAN traffic
      - connectionstate - VPN connection state
        values: Disconnected, Connecting, Connected, Interrupted, Reconnecting, DisconnectingToReconnect, Disconnecting
      - debuglogging - State of debug logging setting
      - portforward - Forwarded port number if available, or the status of the request to forward a port
        values: [forwarded port], Inactive, Attempting, Failed, Unavailable
      - protocol - VPN connection protocol
        values: openvpn, wireguard
      - pubip - Current public IP address
      - region - Currently selected region (or "auto")
      - regions - List all available regions
      - requestportforward - Whether a forwarded port will be requested on the next connection attempt
      - vpnip - Current VPN IP address
    
  login
    usage: login <login_file>
    Log in to your PIA account.
    Put your username and password on separate lines in a text file,
    and specify that file on the command line:
        p0000000
        (yourpassword)
    
  logout
    Log out your PIA account on this computer.
    
  monitor
    usage: monitor <type>
    Monitors the PIA daemon for changes in a specific setting or state value.
    When a connection is established, the current value is printed.
    When a change is received, the new value is printed.
    Available types:
      - allowlan - Whether to allow LAN traffic
      - connectionstate - VPN connection state
        values: Disconnected, Connecting, Connected, Interrupted, Reconnecting, DisconnectingToReconnect, Disconnecting
      - debuglogging - State of debug logging setting
      - portforward - Forwarded port number if available, or the status of the request to forward a port
        values: [forwarded port], Inactive, Attempting, Failed, Unavailable
      - protocol - VPN connection protocol
        values: openvpn, wireguard
      - pubip - Current public IP address
      - region - Currently selected region (or "auto")
      - requestportforward - Whether a forwarded port will be requested on the next connection attempt
      - vpnip - Current VPN IP address
    
  resetsettings
    Resets daemon settings to the defaults (ports/protocols/etc.)
    Client settings (themes/icons/layouts) can't be set with the CLI.
    
  set
    usage: set <type> <value>
    Change settings in the PIA daemon.
    Available types:
      - allowlan - Whether to allow LAN traffic
      - debuglogging - Enable or disable debug logging
      - protocol - Select a VPN protocol
      - region - Select a region (or "auto")
      - requestportforward - Whether to request a forwarded port on the next connection attempt
    

## Interfaces
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host 
       valid_lft forever preferred_lft forever
2: enp11s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 34:5a:60:42:b5:66 brd ff:ff:ff:ff:ff:ff
    inet 10.100.10.10/24 brd 10.100.10.255 scope global dynamic noprefixroute enp11s0
       valid_lft 59641381sec preferred_lft 59641381sec
    inet6 fe80::365a:60ff:fe42:b566/64 scope link 
       valid_lft forever preferred_lft forever
3: wlp8s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether c8:a3:e8:cd:2b:a9 brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.105/24 brd 192.168.1.255 scope global dynamic noprefixroute wlp8s0
       valid_lft 2591672sec preferred_lft 2591672sec
    inet6 fe80::ef75:2716:1d61:a3be/64 scope link noprefixroute 
       valid_lft forever preferred_lft forever
8: tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1231 qdisc fq_codel state UNKNOWN group default qlen 500
    link/none 
    inet 10.178.18.2/24 scope global tun0
       valid_lft forever preferred_lft forever

## Default routes
default via 10.100.10.1 dev enp11s0 proto dhcp src 10.100.10.10 metric 100 
default via 192.168.1.1 dev wlp8s0 proto dhcp src 192.168.1.105 metric 600 
default via 10.178.18.1 dev tun0 metric 32000 

## Route to Binance API
api.binance.com resolved to: 3.168.103.185
3.168.103.185 via 10.100.10.1 dev enp11s0 src 10.100.10.10 uid 1000 
    cache 

## Public IP from shell
98.116.148.30
