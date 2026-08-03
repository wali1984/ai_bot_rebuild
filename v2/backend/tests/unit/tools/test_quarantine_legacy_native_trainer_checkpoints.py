from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOL = REPO_ROOT / "tools/quarantine_legacy_native_trainer_checkpoints.sh"
MODEL_REL = Path(".local_models/v2_native_rl_masa_ppo")
QUARANTINE_REL = Path(".local_models/quarantine")
TIMESTAMP = "20260718T120000Z"
DEST_NAME = f"v2_native_rl_masa_ppo_legacy_{TIMESTAMP}"
RECEIPT_NAME = "v2_native_rl_masa_ppo_legacy_quarantine_active.receipt"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture()
def checkpoint_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo with spaces"
    model_root = repo / MODEL_REL
    (model_root / "nested").mkdir(parents=True)
    (model_root / "manifest.json").write_text('{"legacy":true}\n', encoding="utf-8")
    (model_root / "nested/checkpoint.npz").write_bytes(b"legacy-checkpoint-bytes\x00\xff")
    return repo, model_root


@pytest.fixture()
def fake_commands(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
set -euo pipefail
unit=""
for arg in "$@"; do
  case "$arg" in
    ai-bot-v2-*.service) unit=$arg ;;
  esac
done
[[ -n "$unit" ]] || exit 41
if [[ "${FAKE_SYSTEMCTL_FAIL:-}" == "$unit" ]]; then
  echo "simulated systemctl failure" >&2
  exit 42
fi
state=inactive
if [[ "$unit" == "ai-bot-v2-native-cuda-trainer-persistent.service" ]]; then
  state=${FAKE_TRAINER_STATE:-inactive}
elif [[ "$unit" == "ai-bot-v2-trainer-checkpoint-evidence.service" ]]; then
  state=${FAKE_EVIDENCE_STATE:-inactive}
else
  exit 43
fi
printf 'LoadState=%s\n' "${FAKE_LOAD_STATE:-loaded}"
printf 'ActiveState=%s\n' "$state"
""",
    )
    _write_executable(
        fake_bin / "lsof",
        """#!/usr/bin/env bash
set -euo pipefail
case "${FAKE_LSOF_MODE:-clear}" in
  clear) exit 1 ;;
  open)
    printf 'p4242\nfcwd\nn%s\n' "${*: -1}"
    exit 0
    ;;
  incomplete)
    echo 'lsof: cannot inspect checkpoint root' >&2
    exit 1
    ;;
  error)
    echo 'lsof: simulated failure' >&2
    exit 2
    ;;
  *) exit 44 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "date",
        f"""#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == "-u +%Y%m%dT%H%M%SZ" ]] || exit 45
printf '%s\n' '{TIMESTAMP}'
""",
    )
    _write_executable(
        fake_bin / "sync",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${FAKE_SYNC_MODE:-pass}" == "fail" ]]; then
  echo 'simulated sync failure' >&2
  exit 46
fi
exec /usr/bin/sync "$@"
""",
    )
    return fake_bin


def _run(
    repo: Path,
    fake_bin: Path,
    *arguments: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # noqa: S603 - fixed tool with isolated test paths
        ["/usr/bin/bash", str(TOOL), *arguments, "--repo-root", str(repo)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=30,
    )


def _apply(repo: Path, fake_bin: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return _run(
        repo,
        fake_bin,
        "--apply",
        "--ack-legacy-checkpoint-quarantine",
        extra_env=env,
    )


def test_default_dry_run_inventories_every_file_without_mutation(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    before = {
        path.relative_to(model_root): path.read_bytes()
        for path in model_root.rglob("*")
        if path.is_file()
    }

    result = _run(repo, fake_commands)

    assert result.returncode == 0, result.stderr
    assert "APPLY READINESS: READY" in result.stdout
    assert "DRY RUN ONLY" in result.stdout
    assert "sha256\tbytes\tmtime\trelative_path" in result.stdout
    for relative_path, content in before.items():
        assert hashlib.sha256(content).hexdigest() in result.stdout
        assert str(relative_path) in result.stdout
    after = {
        path.relative_to(model_root): path.read_bytes()
        for path in model_root.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (repo / QUARANTINE_REL).exists()


def test_apply_requires_exact_acknowledgement(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo

    result = _run(repo, fake_commands, "--apply")

    assert result.returncode == 2
    assert "requires --ack-legacy-checkpoint-quarantine" in result.stderr
    assert (model_root / "manifest.json").exists()


@pytest.mark.parametrize(
    ("environment", "expected_unit"),
    [
        (
            {"FAKE_TRAINER_STATE": "active"},
            "ai-bot-v2-native-cuda-trainer-persistent.service",
        ),
        (
            {"FAKE_EVIDENCE_STATE": "active"},
            "ai-bot-v2-trainer-checkpoint-evidence.service",
        ),
    ],
)
def test_apply_refuses_when_either_required_service_is_active(
    checkpoint_repo: tuple[Path, Path],
    fake_commands: Path,
    environment: dict[str, str],
    expected_unit: str,
) -> None:
    repo, model_root = checkpoint_repo

    result = _apply(repo, fake_commands, **environment)

    assert result.returncode == 11
    assert expected_unit in result.stdout
    assert "active=active" in result.stdout
    assert "requires both service gates" in result.stderr
    assert (model_root / "manifest.json").exists()
    assert not (repo / QUARANTINE_REL).exists()


@pytest.mark.parametrize("lsof_mode", ["open", "incomplete", "error"])
def test_apply_refuses_open_handles_or_an_incomplete_handle_scan(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path, lsof_mode: str
) -> None:
    repo, model_root = checkpoint_repo

    result = _apply(repo, fake_commands, FAKE_LSOF_MODE=lsof_mode)

    assert result.returncode == 11
    assert "OPEN-HANDLE GATE" in result.stderr
    assert (model_root / "nested/checkpoint.npz").exists()
    assert not (repo / QUARANTINE_REL).exists()


def test_apply_atomically_quarantines_whole_tree_and_creates_empty_0775_root(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    expected = {
        path.relative_to(model_root): path.read_bytes()
        for path in model_root.rglob("*")
        if path.is_file()
    }

    result = _apply(repo, fake_commands)

    assert result.returncode == 0, result.stderr
    destination = repo / QUARANTINE_REL / DEST_NAME
    inventory = destination.with_name(f"{destination.name}.inventory.tsv")
    receipt = repo / QUARANTINE_REL / RECEIPT_NAME
    assert destination.is_dir()
    actual = {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    assert model_root.is_dir()
    assert list(model_root.iterdir()) == []
    assert stat.S_IMODE(model_root.stat().st_mode) == 0o775
    assert inventory.is_file()
    inventory_text = inventory.read_text(encoding="utf-8")
    for relative_path, content in expected.items():
        assert hashlib.sha256(content).hexdigest() in inventory_text
        assert str(relative_path) in inventory_text
    assert receipt.is_file()
    receipt_text = receipt.read_text(encoding="utf-8")
    assert f"quarantine_root={destination}" in receipt_text
    assert "inventory_file_count=2" in receipt_text
    assert "legacy_checkpoint_migration=NONE" in receipt_text
    assert "ROLLBACK INSTRUCTIONS" in result.stdout
    assert "mv --no-copy -T" in result.stdout
    assert "No service, Redis key, or individual checkpoint" in result.stdout


def test_successful_apply_is_idempotently_fail_closed_on_rerun(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    first = _apply(repo, fake_commands)
    assert first.returncode == 0, first.stderr
    destination = repo / QUARANTINE_REL / DEST_NAME
    first_tree = {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }

    second = _apply(repo, fake_commands)

    assert second.returncode == 6
    assert "active legacy-quarantine receipt already exists" in second.stderr
    assert list(model_root.iterdir()) == []
    second_tree = {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert second_tree == first_tree


def test_apply_refuses_abandoned_global_transaction_reservation(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    reservation = repo / QUARANTINE_REL / ".v2_native_rl_masa_ppo_legacy_quarantine.transaction"
    reservation.mkdir(parents=True)

    result = _apply(repo, fake_commands)

    assert result.returncode == 6
    assert "transaction reservation requires manual review" in result.stderr
    assert (model_root / "manifest.json").exists()
    assert reservation.is_dir()


def test_apply_refuses_symlink_or_special_entries_without_partial_inventory(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    (model_root / "unsafe-link").symlink_to(model_root / "manifest.json")

    result = _apply(repo, fake_commands)

    assert result.returncode == 7
    assert "symlink or special entry" in result.stderr
    assert model_root.is_dir()
    assert not (repo / QUARANTINE_REL).exists()


def test_apply_refuses_unloaded_service(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo

    result = _apply(repo, fake_commands, FAKE_LOAD_STATE="not-found")

    assert result.returncode == 11
    assert "load=not-found" in result.stdout
    assert model_root.is_dir()
    assert not (repo / QUARANTINE_REL).exists()


def test_apply_refuses_a_service_state_query_failure(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo

    result = _apply(
        repo,
        fake_commands,
        FAKE_SYSTEMCTL_FAIL="ai-bot-v2-trainer-checkpoint-evidence.service",
    )

    assert result.returncode == 11
    assert "QUERY_FAILED" in result.stderr
    assert "simulated systemctl failure" in result.stderr
    assert (model_root / "manifest.json").exists()
    assert not (repo / QUARANTINE_REL).exists()


def test_internal_post_rename_failure_restores_original_tree(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    before = {
        path.relative_to(model_root): path.read_bytes()
        for path in model_root.rglob("*")
        if path.is_file()
    }

    result = _apply(repo, fake_commands, FAKE_SYNC_MODE="fail")

    assert result.returncode == 46
    assert "Automatic rollback restored the original checkpoint root" in result.stderr
    after = {
        path.relative_to(model_root): path.read_bytes()
        for path in model_root.rglob("*")
        if path.is_file()
    }
    assert after == before
    quarantine_parent = repo / QUARANTINE_REL
    assert not (quarantine_parent / DEST_NAME).exists()
    assert not (quarantine_parent / ".v2_native_rl_masa_ppo_legacy_quarantine.transaction").exists()
    assert not (quarantine_parent / RECEIPT_NAME).exists()


def test_apply_refuses_empty_bootstrap_like_source_root(
    checkpoint_repo: tuple[Path, Path], fake_commands: Path
) -> None:
    repo, model_root = checkpoint_repo
    for path in sorted(model_root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()

    result = _apply(repo, fake_commands)

    assert result.returncode == 9
    assert "contains no regular files" in result.stderr
    assert model_root.is_dir()
    assert not (repo / QUARANTINE_REL).exists()
