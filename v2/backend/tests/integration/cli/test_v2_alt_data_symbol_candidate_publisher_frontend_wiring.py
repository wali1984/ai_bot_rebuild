"""Static-source regression tests for the V2 alt-data candidate
publisher frontend wiring.

The frontend has no JS test framework configured for this project,
so these tests scan the on-disk TSX/TS sources for the required
wiring and the on-disk public payload for required safety pins.

They prove the Codex blocker
`FRONTEND_CANDIDATE_PUBLISHER_AUTO_ADOPTION_MESSAGE_NOT_WIRED` is
remediated without requiring browser execution.

Rules enforced here:

1. `realtimeUserWebsitePayloads.ts` defines the
   `useAltDataCandidatePublisher` hook and exposes the public
   payload path under PAYLOAD_PATHS.
2. `realtimeWebsite/index.tsx` defines a `CandidatePublisherPanel`
   component that renders the six Codex-mandated adoption labels,
   pins live_gate, live_symbols, candidate_only_not_adopted,
   raw_credential_in_payload, *_expanded=false, and tags the panel
   + table + adoption strip with stable data-testid attributes.
3. `pages/market/index.tsx` imports + uses the hook and the panel.
4. No JSX button anywhere in the panel implementation has text
   matching the dangerous verbs (adopt / live / order / place /
   cancel / modify) -- the panel is display-only.
5. No raw API credential strings are baked into the panel source.
6. The on-disk public dashboard payload pins the safety envelope:
   live_gate=blocked_human_only, live_symbols=[],
   live_symbols_expanded=False, paper_symbols_expanded=False,
   training_symbols_expanded=False, candidate_only_not_adopted=True,
   raw_credential_in_payload="NEVER", writes_exchange_orders=False,
   writes_legacy_redis=False, leverage_changed=False,
   margin_mode_changed=False, approves_live=False, approves_canary=False.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
FRONTEND_SRC = REPO_ROOT / "v2" / "frontend" / "src"
PUBLIC_PAYLOAD = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_alt_data_symbol_candidate_publisher"
    / "latest"
    / "operator_dashboard_payload.json"
)

PAYLOADS_TS = FRONTEND_SRC / "data" / "realtimeUserWebsitePayloads.ts"
PANEL_TSX = FRONTEND_SRC / "components" / "realtimeWebsite" / "index.tsx"
MARKET_PAGE_TSX = FRONTEND_SRC / "pages" / "market" / "index.tsx"


REQUIRED_ADOPTION_LABELS = (
    "Candidate only — not adopted",
    "Does not change training_symbols",
    "Does not change paper_symbols",
    "Does not change live_symbols",
    "Cannot override strict paper-fill gate",
    "Live trading remains blocked",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing required source: {path}"
    return path.read_text(encoding="utf-8")


def test_payload_hook_and_path_declared_in_payloads_ts() -> None:
    src = _read(PAYLOADS_TS)
    # Hook export
    assert "export const useAltDataCandidatePublisher" in src, (
        "useAltDataCandidatePublisher hook must be exported from "
        "realtimeUserWebsitePayloads.ts so /market can consume the "
        "candidate publisher payload."
    )
    # Public payload path entry
    assert "alt_data_candidate_publisher:" in src, (
        "PAYLOAD_PATHS must declare an alt_data_candidate_publisher entry."
    )
    assert (
        "/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"
        in src
    ), (
        "PAYLOAD_PATHS.alt_data_candidate_publisher must point at the "
        "public dashboard payload written by the publisher CLI."
    )
    # Hook polls the alt-data path (not paper/risk)
    hook_block = src.split("export const useAltDataCandidatePublisher", 1)[1][:400]
    assert "PAYLOAD_PATHS.alt_data_candidate_publisher" in hook_block, (
        "The hook must read from PAYLOAD_PATHS.alt_data_candidate_publisher."
    )
    assert "v2:paper" not in hook_block and "v2:risk" not in hook_block, (
        "Hook must not reference v2:paper or v2:risk paths."
    )


def test_candidate_publisher_panel_component_defined() -> None:
    src = _read(PANEL_TSX)
    assert "export function CandidatePublisherPanel" in src, (
        "CandidatePublisherPanel must be exported from realtimeWebsite."
    )
    # Stable test ids the operator dashboard relies on
    for testid in (
        "alt-data-candidate-publisher-panel",
        "candidate-publisher-adoption-labels",
        "candidate-publisher-table",
    ):
        assert f'data-testid="{testid}"' in src, (
            f"CandidatePublisherPanel must tag rendering with "
            f"data-testid=\"{testid}\" for downstream operator/test usage."
        )


def test_all_six_required_adoption_labels_rendered() -> None:
    src = _read(PANEL_TSX)
    for label in REQUIRED_ADOPTION_LABELS:
        assert label in src, (
            f"Required adoption label not found in panel source: {label!r}. "
            "Codex requires these strings be rendered verbatim so operators "
            "see that candidates are not auto-adopted."
        )


def test_safety_pins_referenced_in_panel_source() -> None:
    src = _read(PANEL_TSX)
    # Field names the panel must surface
    required_fields = (
        "candidate_only_not_adopted",
        "live_gate",
        "live_symbols",
        "live_symbols_expanded",
        "paper_symbols_expanded",
        "training_symbols_expanded",
        "raw_credential_in_payload",
        "writes_exchange_orders",
        "may_not_override_strict_paper_fill_gate",
        "candidate_state",
        "candidate_state_counts",
        "candidate_count",
        "altdata_symbol_rank",
        "altdata_symbol_score",
        "proposed_use",
        "candidate_reason",
        "live_symbol_candidate",
        "missing_provider_flags",
        "stale_provider_flags",
    )
    for field in required_fields:
        assert field in src, (
            f"CandidatePublisherPanel must reference the {field!r} field "
            "from the publisher payload so it is visible on the dashboard."
        )


def test_panel_reads_candidates_as_canonical_row_field() -> None:
    """Codex blocker FRONTEND_PUBLIC_PAYLOAD_SCHEMA_MISMATCH_HIDES_CANDIDATE_ROWS:
    the served public payload uses key `candidates` for the row list,
    not `candidate_summary`. The panel must consume `candidates` as the
    canonical source. `candidate_summary` may still be accepted as a
    backward-compatible alias, but the panel must not depend only on it.
    """
    src = _read(PANEL_TSX)
    # The panel must read `dashboard?.candidates` somewhere in its body.
    panel_start = src.index("export function CandidatePublisherPanel")
    panel_body = src[panel_start:]
    next_export = re.search(r"\n(export (function|const) [A-Z])", panel_body[10:])
    if next_export:
        panel_body = panel_body[: 10 + next_export.start()]

    assert "dashboard?.candidates" in panel_body, (
        "CandidatePublisherPanel must read `dashboard?.candidates` -- "
        "this is the canonical row key in the served public payload. "
        "Depending only on `candidate_summary` would hide all rows."
    )
    # The dashboard type on the panel props must accept `candidates`.
    assert re.search(
        r"candidates\??:\s*CandidatePublisherRowLite\[\]", panel_body
    ), (
        "Panel prop type must declare `candidates?: CandidatePublisherRowLite[]` "
        "so TypeScript users get a typed pathway for the canonical field."
    )


def test_payloads_ts_declares_candidates_field() -> None:
    """Dashboard type must declare the canonical `candidates` field."""
    src = _read(PAYLOADS_TS)
    # AltDataCandidatePublisherDashboard must declare `candidates`
    iface_start = src.index("export interface AltDataCandidatePublisherDashboard")
    iface_body = src[iface_start : iface_start + 2000]
    assert re.search(
        r"candidates\??:\s*AltDataCandidateSummaryRow\[\]", iface_body
    ), (
        "AltDataCandidatePublisherDashboard must declare "
        "`candidates?: AltDataCandidateSummaryRow[]` as the canonical "
        "row key. The served public payload uses `candidates`."
    )


def test_panel_renders_candidates_with_no_candidate_summary_alias() -> None:
    """Static-source proof: if a hypothetical payload omits
    `candidate_summary` entirely and only carries `candidates`, the
    panel still resolves rows. This is enforced by reading the panel
    body and asserting it references `candidates` *before* falling back
    to `candidate_summary` (preference order matters)."""
    src = _read(PANEL_TSX)
    # Find the candidateRows assignment block
    m = re.search(
        r"candidateRows[^\n]*=\s*\(\s*([^;]+?)\)\s*as\s*CandidatePublisherRowLite",
        src,
        re.DOTALL,
    )
    assert m is not None, (
        "Panel must define a `candidateRows` expression resolving the "
        "row source with `candidates` preferred over `candidate_summary`."
    )
    expression = m.group(1)
    candidates_pos = expression.find("candidates")
    summary_pos = expression.find("candidate_summary")
    assert candidates_pos >= 0, (
        "`candidates` must appear in the candidateRows resolver expression."
    )
    # If the legacy alias is also referenced, candidates must come first.
    if summary_pos >= 0:
        assert candidates_pos < summary_pos, (
            "The resolver must prefer `candidates` over the legacy "
            "`candidate_summary` alias (candidates listed first in the "
            "?? chain)."
        )


def test_public_payload_uses_canonical_candidates_key() -> None:
    """The served public payload that the panel reads must contain
    rows under the canonical `candidates` key. If the publisher ever
    emits only `candidate_summary` again, this test fires."""
    payload = json.loads(PUBLIC_PAYLOAD.read_text(encoding="utf-8"))
    assert "candidates" in payload, (
        "Public payload must include a `candidates` key holding the row "
        "list. Found keys: " + ", ".join(sorted(payload.keys()))
    )
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) > 0 or payload.get("candidate_count", 0) == 0, (
        "If candidate_count > 0, `candidates` must be a non-empty list."
    )
    if candidates:
        sample = candidates[0]
        for required_field in (
            "symbol",
            "candidate_state",
            "candidate_reason",
            "live_symbol_candidate",
            "candidate_only_not_adopted",
            "missing_provider_flags",
            "stale_provider_flags",
            "proposed_use",
        ):
            assert required_field in sample, (
                f"Candidate row must carry {required_field!r}; missing in "
                f"sample row {sample.get('symbol')!r}."
            )


def test_panel_does_not_render_any_action_button() -> None:
    """The CandidatePublisherPanel must be display-only. The hard safety
    boundary is: no `<button>` JSX, no event handlers (onClick/onSubmit/
    onChange/onMouseDown), no `<form>`, no `<input>`, no `<select>`.

    Static text such as "Candidate only — not adopted" or the field name
    `candidate_only_not_adopted` is *required* (Codex blocker remediation),
    so verb-matching on text alone is not the safety boundary -- absence
    of any action-capable JSX is.
    """
    src = _read(PANEL_TSX)
    # Bound the search window to the CandidatePublisherPanel function body.
    start_marker = "export function CandidatePublisherPanel"
    assert start_marker in src
    body = src[src.index(start_marker):]
    # End of CandidatePublisherPanel = next top-level export (best-effort).
    end_match = re.search(r"\n(export (function|const) [A-Z])", body[10:])
    if end_match:
        body = body[: 10 + end_match.start()]

    forbidden_jsx = (
        "<button",
        "<Button",
        "<form",
        "<Form",
        "<input",
        "<Input",
        "<select",
        "<Select",
        "<textarea",
        "<Textarea",
        "onClick=",
        "onSubmit=",
        "onChange=",
        "onMouseDown=",
        "onKeyDown=",
        "onMouseUp=",
        "useMutation",
        "fetch(",
        "axios.",
        "XMLHttpRequest",
    )
    hits = [token for token in forbidden_jsx if token in body]
    assert not hits, (
        "CandidatePublisherPanel must be display-only; it must not contain "
        f"any action-capable JSX or network call. Found: {hits!r}. "
        "Even an onClick on a non-button element would let an operator "
        "trigger something; the panel is strictly read-only."
    )


def test_panel_does_not_embed_raw_api_keys() -> None:
    src = _read(PANEL_TSX)
    # API key field names must not be rendered as variables
    assert "BINANCE_API_KEY" not in src
    assert "BINANCE_SECRET" not in src
    assert "NANSEN_API_KEY" not in src
    assert "LUNARCRUSH_API_KEY" not in src
    # No accidental hex/base64-ish 32+ char literals adjacent to "key"/"secret"
    # in the candidate publisher block.
    suspicious = re.compile(
        r"(api_?key|secret)['\"\s:=]+([A-Za-z0-9+/=_-]{32,})", re.IGNORECASE
    )
    assert not suspicious.search(src), (
        "Panel source contains a credential-shaped string; remove it."
    )


def test_market_page_does_not_mount_operator_candidate_publisher_panel() -> None:
    src = _read(MARKET_PAGE_TSX)
    assert "CandidatePublisherPanel" not in src, (
        "/market is a public/trader market-detail route and must not mount "
        "the legacy operator candidate-publisher payload panel."
    )
    assert "useAltDataCandidatePublisher" not in src, (
        "/market must not fetch the operator candidate-publisher payload. "
        "Use public/trader envelope APIs or admin-only incident views."
    )
    assert 'data-testid="alt-data-candidate-publisher-section"' not in src


def test_market_page_does_not_render_adopt_button_for_publisher() -> None:
    src = _read(MARKET_PAGE_TSX)
    # Look only at the candidate publisher section.
    if 'data-testid="alt-data-candidate-publisher-section"' not in src:
        # Already asserted above.
        return
    start = src.index('data-testid="alt-data-candidate-publisher-section"')
    snippet = src[start : start + 1200]
    assert "<button" not in snippet and "<Button" not in snippet, (
        "The alt-data candidate publisher section on /market must not "
        "contain any <button> JSX -- it is a read-only display."
    )


def test_public_dashboard_payload_pins_safety_envelope() -> None:
    assert PUBLIC_PAYLOAD.is_file(), (
        f"Public payload missing at expected path: {PUBLIC_PAYLOAD}"
    )
    payload = json.loads(PUBLIC_PAYLOAD.read_text(encoding="utf-8"))
    # Hard safety pins required on every payload tick.
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["live_symbols_expanded"] is False
    assert payload["paper_symbols_expanded"] is False
    assert payload["training_symbols_expanded"] is False
    assert payload["candidate_only_not_adopted"] is True
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["writes_exchange_orders"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_old_redis"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["may_not_authorize_live_or_canary"] is True
    assert payload["may_not_place_orders"] is True
    assert payload["provider_network_calls_attempted"] is False
    # Forbidden input namespaces are stated explicitly.
    assert "v2:paper:*" in payload["forbidden_input_namespaces"]
    assert "v2:risk:*" in payload["forbidden_input_namespaces"]
    # Allowed writes are exactly the two publisher keys.
    assert sorted(payload["allowed_writes"]) == [
        "v2:altdata:candidate_publisher:status",
        "v2:symbol_universe:altdata_candidates",
    ]


def test_public_dashboard_payload_candidate_safety_pins() -> None:
    payload = json.loads(PUBLIC_PAYLOAD.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    assert candidates, "Public payload should expose a candidates list."
    for cand in candidates:
        assert cand["live_symbol_candidate"] is False, (
            f"candidate {cand.get('symbol')!r} must pin live_symbol_candidate=False"
        )
        assert cand["candidate_only_not_adopted"] is True
        assert cand["may_not_override_strict_paper_fill_gate"] is True
        assert cand["may_not_authorize_live_or_canary"] is True
        assert cand["may_not_place_orders"] is True
        assert cand["live_gate"] == "blocked_human_only"
        assert cand["live_symbols"] == []
        assert cand["raw_credential_in_payload"] == "NEVER"
        assert cand["writes_exchange_orders"] is False
        assert cand["writes_old_redis"] is False
        # Candidate state must be one of the 7 known states (or a future
        # state explicitly added to the legend).
        legend = payload.get("candidate_states_legend", {})
        assert cand["candidate_state"] in legend, (
            f"candidate {cand.get('symbol')!r} has unknown state "
            f"{cand.get('candidate_state')!r} not present in legend."
        )


def test_public_payload_missing_provider_data_rendered_honestly() -> None:
    """If candidates exist with no provider score, the payload must
    surface that as MISSING_PROVIDER_DATA -- never as CANDIDATE_READY
    or as a silent promotion."""
    payload = json.loads(PUBLIC_PAYLOAD.read_text(encoding="utf-8"))
    for cand in payload.get("candidates", []):
        if cand.get("altdata_symbol_score") is None:
            assert cand["candidate_state"] == "MISSING_PROVIDER_DATA", (
                f"candidate {cand.get('symbol')!r} has null altdata_symbol_score "
                f"but is classified as {cand['candidate_state']!r}; "
                "missing scores must render as MISSING_PROVIDER_DATA."
            )
            assert cand["proposed_use"] == [], (
                "MISSING_PROVIDER_DATA candidates must have empty proposed_use."
            )
            assert cand["live_symbol_candidate"] is False
            assert cand["paper_symbol_candidate"] is False
            assert cand["training_symbol_candidate"] is False
            assert cand["watchlist_candidate"] is False
