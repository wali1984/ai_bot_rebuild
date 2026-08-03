"""Systemd notify helpers for Type=notify units.

The helper intentionally degrades gracefully when systemd is not
managing the process or when ``sd_notify`` isn't available.
"""

from __future__ import annotations

import os
import socket


def _notify_socket() -> str | None:
    return os.environ.get("NOTIFY_SOCKET")


def send(message: str) -> bool:
    """Send a raw systemd notify message.

    Returns ``True`` when a socket was reached and transmission succeeded.
    """
    notify_socket = _notify_socket()
    if not notify_socket:
        return False

    address = notify_socket
    if notify_socket.startswith("@"):
        address = "\0" + notify_socket[1:]

    sock = socket.socket(family=socket.AF_UNIX, type=socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(message.encode("utf-8"))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def notify_ready() -> bool:
    return send("READY=1")


def notify_status(status: str) -> bool:
    return send(f"STATUS={status}")


def notify_watchdog() -> bool:
    return send("WATCHDOG=1")

