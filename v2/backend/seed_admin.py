#!/usr/bin/env python3
"""Seed an admin user into auth_users.json.

Run once to create the initial admin account:
  cd v2/backend
  python seed_admin.py

Reads ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL and ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD
from environment, or uses defaults for local dev.

Never logs or stores the plaintext password.
"""

from __future__ import annotations

import os
import sys

# Allow running from v2/backend directory
sys.path.insert(0, os.path.dirname(__file__))

from app.auth.users import UserStore

EMAIL    = os.environ.get("ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL",    "admin@alphaforge.local")
PASSWORD = os.environ.get("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "AlphaForge2026!")

def main() -> None:
    store = UserStore()

    # Check if admin already exists
    existing = store.get_by_email(EMAIL)
    if existing:
        print(f"[seed_admin] User already exists: {EMAIL} (role={existing.get('role')})")
        return

    user = store.create_user(
        email=EMAIL,
        username=EMAIL.split("@")[0],
        password=PASSWORD,
        role="admin",
        trader_id="admin-001",
        paper_account_id="paper-admin-001",
        watchlist=["BTCUSDT", "ETHUSDT", "SOLUSDT", "LABUSDT", "XRPUSDT"],
        alert_preferences={},
        is_active=True,
    )

    print(f"[seed_admin] Created admin user: {user['email']} (id={user['id']})")
    print(f"[seed_admin] Default password: {PASSWORD}")
    print("[seed_admin] Change this password before any production deployment.")

if __name__ == "__main__":
    main()
