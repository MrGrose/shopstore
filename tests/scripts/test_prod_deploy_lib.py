"""Tests for scripts/prod_prod_lib.sh color and Caddy safety helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "prod_prod_lib.sh"


def _bash(
    expr: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", f"source '{LIB}' && {expr}"],
        check=False,
        capture_output=True,
        text=True,
        env=merged,
    )


def test_standby_color() -> None:
    assert _bash("prod_prod_standby_color blue").stdout.strip() == "green"
    assert _bash("prod_prod_standby_color green").stdout.strip() == "blue"


def test_port_and_color_mapping() -> None:
    assert _bash("prod_prod_port_for_color blue").stdout.strip() == "8001"
    assert _bash("prod_prod_port_for_color green").stdout.strip() == "8002"
    assert _bash("prod_prod_color_for_port 8001").stdout.strip() == "blue"
    assert _bash("prod_prod_color_for_port 8002").stdout.strip() == "green"


def test_service_and_container_names() -> None:
    assert _bash("prod_prod_service_for_color blue").stdout.strip() == "api-blue"
    assert _bash("prod_prod_service_for_color green").stdout.strip() == "api-green"
    assert (
        _bash("prod_prod_container_for_color blue").stdout.strip()
        == "shopstore-api-blue-1"
    )
    assert (
        _bash("prod_prod_container_for_color green").stdout.strip()
        == "shopstore-api-green-1"
    )


def test_read_and_verify_caddy_upstream(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "shopstore.pro {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8002\n}\n",
        encoding="utf-8",
    )
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    assert _bash("prod_prod_read_caddy_upstream_port", env=env).stdout.strip() == "8002"
    assert _bash("prod_prod_active_color_from_caddy", env=env).stdout.strip() == "green"
    ok = _bash("prod_prod_verify_caddy_upstream_port 8002", env=env)
    assert ok.returncode == 0
    bad = _bash("prod_prod_verify_caddy_upstream_port 8001", env=env)
    assert bad.returncode != 0


def test_caddy_staging_rewrite_swaps_only_api_block(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    staging = tmp_path / "Caddyfile.staging"
    caddy.write_text(
        "cdn.shopstore.example {\n"
        "\thandle /media/products/* {\n"
        "\t\treverse_proxy 127.0.0.1:8888\n"
        "\t}\n"
        "}\n\n"
        "shopstore.pro {\n"
        "\treverse_proxy 127.0.0.1:8001\n"
        "}\n",
        encoding="utf-8",
    )
    staging_path = str(staging)
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    expr = (
        f'cp "$PROD_PROD_CADDYFILE" "{staging_path}" && '
        f'prod_prod_caddy_apply_api_cutover_sed 8001 8002 "{staging_path}" > '
        f'"{staging_path}.new" && mv "{staging_path}.new" "{staging_path}"'
    )
    assert _bash(expr, env=env).returncode == 0
    text = staging.read_text(encoding="utf-8")
    assert "127.0.0.1:8002" in text
    assert "127.0.0.1:8001" not in text
    assert "127.0.0.1:8888" in text


def test_read_caddy_upstream_ignores_cdn_localhost_proxy(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "cdn.shopstore.example {\n"
        "\treverse_proxy 127.0.0.1:8888\n"
        "}\n\n"
        "shopstore.pro {\n"
        "\treverse_proxy 127.0.0.1:8002\n"
        "}\n",
        encoding="utf-8",
    )
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    assert _bash("prod_prod_read_caddy_upstream_port", env=env).stdout.strip() == "8002"
    assert _bash("prod_prod_active_color_from_caddy", env=env).stdout.strip() == "green"


def test_prod_caddy_example_api_upstream_and_cutover_preserves_cdn(
    tmp_path: Path,
) -> None:
    example = REPO_ROOT / "deploy" / "prod" / "caddy" / "Caddyfile.example"
    assert example.is_file()
    caddy = tmp_path / "Caddyfile"
    staging = tmp_path / "Caddyfile.staging"
    caddy.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    assert _bash("prod_prod_read_caddy_upstream_port", env=env).stdout.strip() == "8002"
    api_block = _bash("prod_prod_caddy_api_block_text", env=env).stdout
    assert "cdn.shopstore.example" not in api_block
    assert "127.0.0.1:8888" not in api_block
    assert "127.0.0.1:8002" in api_block
    staging_path = str(staging)
    expr = (
        f'cp "$PROD_PROD_CADDYFILE" "{staging_path}" && '
        f'prod_prod_caddy_apply_api_cutover_sed 8002 8001 "{staging_path}" > '
        f'"{staging_path}.new" && mv "{staging_path}.new" "{staging_path}"'
    )
    assert _bash(expr, env=env).returncode == 0
    text = staging.read_text(encoding="utf-8")
    assert "127.0.0.1:8888" in text
    assert "127.0.0.1:8001" in text
    assert "127.0.0.1:8002" not in text


def test_verify_caddy_backup_port(tmp_path: Path) -> None:
    backup = tmp_path / "Caddyfile.backup"
    backup.write_text(
        "shopstore.pro {\n\treverse_proxy 127.0.0.1:8002\n}\n",
        encoding="utf-8",
    )
    ok = _bash(f"prod_prod_verify_caddy_backup_port '{backup}' 8002")
    assert ok.returncode == 0
    bad = _bash(f"prod_prod_verify_caddy_backup_port '{backup}' 8001")
    assert bad.returncode != 0


def test_reject_multiple_api_upstreams_in_shopstore_block(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "shopstore.pro {\n"
        "\treverse_proxy 127.0.0.1:8002\n"
        "\treverse_proxy 127.0.0.1:8001\n"
        "}\n",
        encoding="utf-8",
    )
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    result = _bash("prod_prod_read_caddy_upstream_port", env=env)
    assert result.returncode != 0
    assert "8001|8002" in result.stderr


def test_reject_unknown_caddy_port(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "shopstore.pro {\n\treverse_proxy 127.0.0.1:8000\n}\n",
        encoding="utf-8",
    )
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    result = _bash("prod_prod_active_color_from_caddy", env=env)
    assert result.returncode != 0
    assert "8001|8002" in result.stderr or "unknown API port" in result.stderr


def test_verify_public_hits_returns_without_exit_on_smoke_fail() -> None:
    env = {"PROD_PROD_DOMAIN": "http://127.0.0.1:9"}
    result = _bash(
        "prod_prod_verify_public_hits_container shopstore-api-green-1", env=env
    )
    assert result.returncode != 0


def test_skip_drain_when_env_set() -> None:
    result = _bash("prod_prod_drain_api_color blue", env={"PROD_PROD_SKIP_DRAIN": "1"})
    assert result.returncode == 0
    assert "skip drain" in result.stdout


def test_drain_uses_docker_stop_only() -> None:
    lib = LIB.read_text(encoding="utf-8")
    start = lib.index("prod_prod_drain_api_color")
    end = lib.index("prod_prod_ensure_api_running")
    body = lib[start:end]
    assert "docker stop" in body
    assert "docker rm" not in body
    assert "compose down" not in body


def test_deploy_script_action_order() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    ordered = [
        "prod_prod_run_gate",
        "prod_prod_caddy_cutover_ports",
        "prod_prod_verify_public_hits_container",
        "prod_prod_drain_api_color",
        "prod_prod_assert_api_running",
        "prod_prod_write_active_color",
    ]
    positions = [deploy.index(marker) for marker in ordered]
    assert positions == sorted(positions)


def test_active_color_written_after_drain_and_check() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    drain_idx = deploy.index("prod_prod_drain_api_color")
    assert_idx = deploy.index("prod_prod_assert_api_running")
    color_idx = deploy.index("prod_prod_write_active_color")
    assert drain_idx < assert_idx < color_idx


def test_drain_refuses_current_caddy_active(tmp_path: Path) -> None:
    caddy = tmp_path / "Caddyfile"
    caddy.write_text(
        "shopstore.pro {\n\treverse_proxy 127.0.0.1:8002\n}\n", encoding="utf-8"
    )
    env = {"PROD_PROD_CADDYFILE": str(caddy)}
    result = _bash("prod_prod_drain_api_color green", env=env)
    assert result.returncode != 0
    assert "refusing to drain" in result.stderr


def test_drain_failure_messages_require_manual_intervention() -> None:
    lib = LIB.read_text(encoding="utf-8")
    start = lib.index("prod_prod_drain_api_color")
    end = lib.index("prod_prod_ensure_api_running")
    body = lib[start:end]
    assert "manual intervention required" in body
    assert body.count("prod_prod_fail") >= 3


def test_deploy_drains_previous_active_variable() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    assert 'prod_prod_drain_api_color "$active"' in deploy
    assert 'prod_prod_drain_api_color "$standby"' not in deploy


def test_skip_drain_logs_both_apis_may_remain_running() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    assert "both APIs may remain running" in deploy
    assert "prod_prod_skip_drain" in deploy


def test_ensure_api_running_reuses_stopped_container() -> None:
    lib = LIB.read_text(encoding="utf-8")
    start = lib.index("prod_prod_ensure_api_running")
    body = lib[start : start + 900]
    assert "--no-recreate" in body
    assert "docker start" in body
    assert "compose down" not in body


def test_deploy_skips_drain_on_public_smoke_failure() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    verify_idx = deploy.index("prod_prod_verify_public_hits_container")
    drain_idx = deploy.index("prod_prod_drain_api_color")
    failure_block = deploy[verify_idx:drain_idx]
    assert "prod_prod_drain_api_color" not in failure_block
    assert "prod_prod_restore_caddy_backup" in failure_block


def test_post_drain_check_runs_even_when_skip_drain() -> None:
    deploy = (REPO_ROOT / "scripts" / "prod_prod_deploy.sh").read_text(encoding="utf-8")
    skip_idx = deploy.index("prod_prod_skip_drain")
    assert_idx = deploy.index("prod_prod_assert_api_running")
    assert skip_idx < assert_idx


PRODUCTION_PUBLIC_LOG_SAMPLE = """\
INFO:     127.0.0.1:123 - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:123 - "GET /ready HTTP/1.1" 200 OK
INFO:     127.0.0.1:123 - "GET /catalog/labels HTTP/1.1" 200 OK
INFO:     127.0.0.1:123 - "GET /catalog/taxonomy HTTP/1.1" 200 OK
INFO:     127.0.0.1:123 - "GET /products?limit=1 HTTP/1.1" 200 OK
"""


def test_public_smoke_log_delta_sufficient_boundary() -> None:
    assert _bash("prod_prod_public_smoke_log_delta_sufficient 3").returncode == 0
    assert _bash("prod_prod_public_smoke_log_delta_sufficient 2").returncode != 0


def test_logs_contain_public_path_hits_production_sample() -> None:
    env = {"SAMPLE_LOGS": PRODUCTION_PUBLIC_LOG_SAMPLE}
    assert (
        _bash(
            'prod_prod_logs_contain_public_path_hits "$SAMPLE_LOGS"', env=env
        ).returncode
        == 0
    )


def test_logs_contain_public_path_hits_rejects_unrelated_only() -> None:
    env = {"SAMPLE_LOGS": "GET /metrics\nGET /admin/login\n"}
    assert (
        _bash(
            'prod_prod_logs_contain_public_path_hits "$SAMPLE_LOGS"', env=env
        ).returncode
        != 0
    )


def test_logs_contain_public_path_hits_accepts_many_lines_after_match() -> None:
    lines = [PRODUCTION_PUBLIC_LOG_SAMPLE.strip()] + [
        f"noise line {i}" for i in range(120)
    ]
    env = {"SAMPLE_LOGS": "\n".join(lines)}
    assert (
        _bash(
            'prod_prod_logs_contain_public_path_hits "$SAMPLE_LOGS"', env=env
        ).returncode
        == 0
    )


def test_public_log_evidence_requires_both_delta_and_path_hits() -> None:
    env = {"SAMPLE_LOGS": PRODUCTION_PUBLIC_LOG_SAMPLE}
    assert _bash("prod_prod_public_smoke_log_delta_sufficient 5").returncode == 0
    assert (
        _bash(
            'prod_prod_logs_contain_public_path_hits "$SAMPLE_LOGS"', env=env
        ).returncode
        == 0
    )
    assert _bash("prod_prod_public_smoke_log_delta_sufficient 1").returncode != 0


def test_pipefail_grep_q_pipeline_can_fail_despite_matching_line(
    tmp_path: Path,
) -> None:
    """docker logs | grep -q may fail under pipefail when the writer gets SIGPIPE."""
    script = tmp_path / "pipefail.sh"
    script.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
writer() {
  echo 'GET /health'
  local i
  for i in $(seq 1 400); do echo "filler ${i}"; done
}
writer 2>&1 | grep -qE 'GET /(health|ready|catalog|products)'
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    result = subprocess.run([str(script)], capture_output=True, text=True, check=False)
    assert result.returncode != 0


def test_logs_contain_public_path_hits_under_pipefail_with_long_logs() -> None:
    lines = [PRODUCTION_PUBLIC_LOG_SAMPLE.strip()] + [f"filler {i}" for i in range(200)]
    env = {**os.environ, "SAMPLE_LOGS": "\n".join(lines)}
    script = (
        f"set -euo pipefail; source '{LIB}'; "
        'prod_prod_logs_contain_public_path_hits "$SAMPLE_LOGS"'
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0


def test_public_path_hits_avoids_docker_logs_grep_pipeline() -> None:
    lib = LIB.read_text(encoding="utf-8")
    start = lib.index("prod_prod_verify_public_hits_container")
    end = lib.index("prod_prod_api_running")
    body = lib[start:end]
    assert "recent_logs=" in body
    assert 'docker logs --since 2m "$container" 2>&1 | grep -qE' not in body
    assert 'prod_prod_logs_contain_public_path_hits "$recent_logs"' in body
