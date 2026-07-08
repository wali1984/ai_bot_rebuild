"""Shared fixtures for integration CLI tests.

CG-F044 (2026-07-08): integration tests that drive
``v2_trade_management_paper_loop.run_once()`` patched the Redis client and the
state-file READ, but the loop's ``write_payload`` calls still wrote the REAL
runtime state files under ``v2/frontend/public/operator_runtime/...``. A test
fixture close row written that way was later merged over the live 18-row
closed-trades history by the production loop, destroying it. This autouse
fixture redirects every paper-loop state path to a per-test tmp directory so
tests can never touch the production runtime state again.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _isolate_paper_loop_state_files(monkeypatch, tmp_path):
    paper = importlib.import_module(
        "v2.backend.app.cli.v2_trade_management_paper_loop"
    )
    public_dir = tmp_path / "paper_trade_management_public"
    monkeypatch.setattr(paper, "TRADE_MANAGEMENT_PUBLIC_DIR", public_dir)
    monkeypatch.setattr(
        paper,
        "PAPER_ACCEPTED_FILLS_STATE_PATH",
        public_dir / "paper_accepted_fills_state.json",
    )
    monkeypatch.setattr(
        paper,
        "PAPER_ACCEPTED_FILLS_QUARANTINE_STATE_PATH",
        public_dir / "paper_accepted_fills_quarantine_state.json",
    )
    monkeypatch.setattr(
        paper,
        "PAPER_LIFECYCLE_STATE_PATH",
        public_dir / "paper_lifecycle_state.json",
    )
    yield
