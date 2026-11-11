import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(label: str, command: list[str], *, cwd: Path = ROOT) -> bool:
    print(f"\n## {label}\n$ {' '.join(command)}")
    return subprocess.run(command, cwd=cwd, check=False).returncode == 0


def check_no_legacy_codes() -> bool:
    files = list((ROOT / "frontend/src").rglob("*.ts")) + list(
        (ROOT / "frontend/src").rglob("*.tsx")
    )
    matches = [
        path
        for path in files
        if "PS-" in path.read_text(encoding="utf-8") and "test" not in path.name
    ]
    if matches:
        for path in matches:
            print(path.relative_to(ROOT))
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    if args.backend_only and args.frontend_only:
        parser.error("--backend-only and --frontend-only нельзя использовать вместе")

    checks: list[tuple[str, list[str], Path]] = []
    backend_tests = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests/integration").glob("test_referral_*.py")
    )
    if not args.frontend_only:
        checks.extend(
            [
                (
                    "Referral fixtures",
                    [
                        "uv",
                        "run",
                        "--extra",
                        "web",
                        "pytest",
                        "-s",
                        "tests/manual/referral_verification_fixture.py",
                        "-q",
                    ],
                    ROOT,
                ),
                (
                    "Backend referral scenarios",
                    ["uv", "run", "--extra", "web", "pytest", *backend_tests, "-q"],
                    ROOT,
                ),
                (
                    "Referral browser E2E",
                    [
                        "uv",
                        "run",
                        "pytest",
                        "tests/e2e/test_referral_e2e.py",
                        "-m",
                        "e2e",
                        "-q",
                    ],
                    ROOT,
                ),
            ]
        )
    if not args.backend_only:
        checks.append(
            (
                "Frontend referral scenarios",
                [
                    "npx",
                    "vitest",
                    "run",
                    "src/lib/storefront/referral.test.ts",
                    "src/lib/storefront/referrer.test.ts",
                ],
                ROOT / "frontend",
            )
        )

    env = {**os.environ, "REFERRAL_VERIFICATION_ACTION": "check"}
    failed: list[str] = []
    for label, command, cwd in checks:
        print(f"\n## {label}\n$ {' '.join(command)}")
        if subprocess.run(command, cwd=cwd, check=False, env=env).returncode != 0:
            failed.append(label)

    print("\n## No legacy PS-* in runtime code")
    if not check_no_legacy_codes():
        failed.append("No legacy PS-* in runtime code")
    print("\n## Итог")
    if failed:
        print("FAIL: " + ", ".join(failed))
        print("Чеклист: openspec/audits/referral-migration-verification.md")
        return 1
    print(f"OK: {len(checks)} автоматических проверок")
    print("Ручные сценарии: openspec/audits/referral-migration-verification.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
