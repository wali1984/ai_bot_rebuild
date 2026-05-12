# Stale Proof Dump Cleanup Report

Generated at: 2026-05-12T20:32:41Z

Before crawl failures:

[
  {
    "route": "/landing",
    "http_status": 200,
    "screenshot": "screenshots/before/_landing.png",
    "classification": {
      "production_ready": false,
      "route_404": false,
      "final_url": "https://dashboard.wajidali.us/landing",
      "placeholder_only": false,
      "evidence_gap_only": false,
      "proof_dump_primary": true,
      "static_fixture_as_current": false,
      "stale_payload_hidden": false,
      "current_runtime_truth_visible": true,
      "source_freshness_visible": true,
      "live_block_banner_visible": true,
      "chart_exists": true,
      "chart_broken": false,
      "duplicate_headings": [],
      "nav_link_count": 6,
      "link_failure_count": 0,
      "console_error_count": 0,
      "network_error_count": 0,
      "dangerous_control_enabled": false,
      "needs_repair": true
    }
  },
  {
    "route": "/status",
    "http_status": 200,
    "screenshot": "screenshots/before/_status.png",
    "classification": {
      "production_ready": false,
      "route_404": false,
      "final_url": "https://dashboard.wajidali.us/status",
      "placeholder_only": false,
      "evidence_gap_only": true,
      "proof_dump_primary": false,
      "static_fixture_as_current": false,
      "stale_payload_hidden": false,
      "current_runtime_truth_visible": true,
      "source_freshness_visible": true,
      "live_block_banner_visible": true,
      "chart_exists": false,
      "chart_broken": false,
      "duplicate_headings": [],
      "nav_link_count": 0,
      "link_failure_count": 0,
      "console_error_count": 0,
      "network_error_count": 0,
      "dangerous_control_enabled": false,
      "needs_repair": true
    }
  },
  {
    "route": "/login",
    "http_status": 200,
    "screenshot": "screenshots/before/_login.png",
    "classification": {
      "production_ready": false,
      "route_404": false,
      "final_url": "https://dashboard.wajidali.us/login",
      "placeholder_only": false,
      "evidence_gap_only": true,
      "proof_dump_primary": false,
      "static_fixture_as_current": false,
      "stale_payload_hidden": false,
      "current_runtime_truth_visible": true,
      "source_freshness_visible": true,
      "live_block_banner_visible": true,
      "chart_exists": false,
      "chart_broken": false,
      "duplicate_headings": [],
      "nav_link_count": 0,
      "link_failure_count": 0,
      "console_error_count": 0,
      "network_error_count": 0,
      "dangerous_control_enabled": false,
      "needs_repair": true
    }
  }
]

After crawl failures:

[]

Static proof and historical examples remain archive-only. Public landing/status/access pages now lead with current paper/shadow runtime state rather than Mission Control proof sections or evidence-gap contract text.
