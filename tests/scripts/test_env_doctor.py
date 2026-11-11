import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = importlib.util.spec_from_file_location(
    "env_doctor",
    ROOT / "scripts" / "env_doctor.py",
)
env_doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["env_doctor"] = env_doctor
SPEC.loader.exec_module(env_doctor)

build_report = env_doctor.build_report
parse_env_file = env_doctor.parse_env_file


def test_parse_env_file_detects_duplicates_and_empty(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "FOO=bar\nFOO=baz\nEMPTY=\nBAD LINE\n",
        encoding="utf-8",
    )
    parsed = parse_env_file(env)
    assert parsed.variables["FOO"] == "baz"
    assert "FOO" in parsed.duplicate_keys
    assert "EMPTY" in parsed.variables
    assert any(issue.message == "line without '='" for issue in parsed.syntax_issues)


def test_build_report_missing_and_unused(tmp_path: Path) -> None:
    reference = tmp_path / ".env.example"
    reference.write_text("REQUIRED=1\n# OPTIONAL=\n", encoding="utf-8")
    target = tmp_path / ".env.dev"
    target.write_text("EXTRA=1\n", encoding="utf-8")

    report = build_report(
        reference_path=reference,
        target_paths=[target],
        strict=False,
    )
    file_report = report.files[0]
    assert file_report.status == "FAILED"
    assert file_report.missing == ["REQUIRED"]
    assert file_report.unused == ["EXTRA"]


def test_commented_reference_keys(tmp_path: Path) -> None:
    reference = tmp_path / ".env.example"
    reference.write_text("ACTIVE=1\n# DOCUMENTED=\n", encoding="utf-8")
    target = tmp_path / ".env.dev"
    target.write_text("ACTIVE=1\nDOCUMENTED=ok\n", encoding="utf-8")

    report = build_report(
        reference_path=reference,
        target_paths=[target],
        strict=False,
    )
    assert report.files[0].status == "OK"
    assert report.files[0].unused == []
