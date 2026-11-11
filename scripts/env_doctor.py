import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TextIO

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE = ROOT / ".env.example"
DEFAULT_TARGETS = (".env", ".env.dev", ".env.prod")

# Регулярные выражения для проверки синтаксиса env файлов
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Регулярное выражение для проверки комментированных ключей в env файле
_COMMENTED_KEY_RE = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")

# Типы статусов проверки
Status = Literal["OK", "WARNING", "FAILED", "MISSING"]


# Класс для хранения информации о синтаксических проблемах в env файле
@dataclass(frozen=True)
class SyntaxIssue:
    line: int
    message: str


# Класс для хранения информации о parsed env файле
@dataclass
class ParsedEnv:
    path: Path
    exists: bool
    variables: dict[str, str] = field(default_factory=dict)
    duplicate_keys: dict[str, list[int]] = field(default_factory=dict)
    syntax_issues: list[SyntaxIssue] = field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        return set(self.variables)


# Класс для хранения информации о результатах проверки env файла
@dataclass
class FileReport:
    path: Path
    exists: bool
    status: Status
    missing: list[str] = field(default_factory=list)
    unused: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    duplicates: dict[str, list[int]] = field(default_factory=dict)
    syntax_issues: list[SyntaxIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.missing or self.duplicates or self.syntax_issues)

    @property
    def has_warnings(self) -> bool:
        return bool(self.unused or self.empty)


# Класс для хранения информации о результатах проверки всех env файлов
@dataclass
class DoctorReport:
    reference: Path
    reference_keys: list[str]
    files: list[FileReport] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(report.has_errors for report in self.files)

    @property
    def warned(self) -> bool:
        return any(report.has_warnings for report in self.files)


# Класс для работы с ANSI кодами
class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def wrap(self, text: str, *codes: str) -> str:
        if not self.enabled:
            return text
        return "".join(codes) + text + self.RESET


# Функция для удаления комментариев в inline стиле
def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return value[:index].rstrip()
    return value


# Функция для удаления кавычек из значения переменной
def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        body = value[1:-1]
        if value[0] == '"':
            return body.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
        return body
    return value


# Функция для проверки, является ли значение переменной пустым
def _is_empty_value(value: str) -> bool:
    return value == ""


# Функция для парсинга env файла
def parse_env_file(path: Path) -> ParsedEnv:
    result = ParsedEnv(path=path, exists=path.is_file())
    if not result.exists:
        return result

    seen_lines: dict[str, list[int]] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            result.syntax_issues.append(
                SyntaxIssue(line=line_no, message="line without '='")
            )
            continue

        key_part, _, value_part = line.partition("=")
        key_part = key_part.strip()
        if key_part.startswith("export "):
            key_part = key_part[7:].strip()

        if not key_part:
            result.syntax_issues.append(
                SyntaxIssue(line=line_no, message="empty variable name")
            )
            continue
        if " " in key_part or not _VAR_NAME_RE.match(key_part):
            result.syntax_issues.append(
                SyntaxIssue(
                    line=line_no,
                    message=f"invalid variable name '{key_part}'",
                )
            )
            continue

        value = _unquote(_strip_inline_comment(value_part.strip()))
        seen_lines.setdefault(key_part, []).append(line_no)
        result.variables[key_part] = value

    result.duplicate_keys = {
        key: lines for key, lines in seen_lines.items() if len(lines) > 1
    }
    return result


# Функция для загрузки reference env файла
def load_reference(path: Path) -> tuple[set[str], set[str], ParsedEnv]:
    parsed = parse_env_file(path)
    required = set(parsed.keys)
    known = set(required)
    if path.is_file():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            match = _COMMENTED_KEY_RE.match(raw_line)
            if match:
                known.add(match.group(1))
    return required, known, parsed


# Функция для поиска отсутствующих переменных в env файле
def find_missing(required: set[str], parsed: ParsedEnv) -> list[str]:
    if not parsed.exists:
        return sorted(required)
    return sorted(required - parsed.keys)


# Функция для поиска неиспользуемых переменных в env файле
def find_unused(known: set[str], parsed: ParsedEnv) -> list[str]:
    if not parsed.exists:
        return []
    return sorted(parsed.keys - known)


# Функция для поиска переменных с пустыми значениями в env файле
def find_empty(parsed: ParsedEnv) -> list[str]:
    if not parsed.exists:
        return []
    return sorted(
        key for key, value in parsed.variables.items() if _is_empty_value(value)
    )


# Функция для проверки env файла
def validate_env(
    required_keys: set[str],
    known_keys: set[str],
    parsed: ParsedEnv,
    strict: bool,
) -> FileReport:
    if not parsed.exists:
        return FileReport(path=parsed.path, exists=False, status="MISSING")

    missing = find_missing(required_keys, parsed)
    unused = find_unused(known_keys, parsed)
    empty = find_empty(parsed)
    duplicates = dict(parsed.duplicate_keys)
    syntax_issues = list(parsed.syntax_issues)
    has_errors = bool(missing or duplicates or syntax_issues)
    has_warnings = bool(unused or empty)

    if has_errors or (strict and has_warnings):
        status: Status = "FAILED"
    elif has_warnings:
        status = "WARNING"
    else:
        status = "OK"

    return FileReport(
        path=parsed.path,
        exists=True,
        status=status,
        missing=missing,
        unused=unused,
        empty=empty,
        duplicates=duplicates,
        syntax_issues=syntax_issues,
    )


# Функция для построения отчета о результатах проверки всех env файлов
def build_report(
    reference_path: Path,
    target_paths: list[Path],
    strict: bool,
) -> DoctorReport:
    required_keys, known_keys, reference_parsed = load_reference(reference_path)
    if not reference_path.is_file():
        msg = f"Reference file not found: {reference_path}"
        raise FileNotFoundError(msg)
    if reference_parsed.syntax_issues or reference_parsed.duplicate_keys:
        msg = f"Reference file has syntax issues: {reference_path}"
        raise ValueError(msg)

    report = DoctorReport(
        reference=reference_path,
        reference_keys=sorted(required_keys),
    )
    for target_path in target_paths:
        parsed = parse_env_file(target_path)
        report.files.append(
            validate_env(
                required_keys=required_keys,
                known_keys=known_keys,
                parsed=parsed,
                strict=strict,
            )
        )
    return report


# Функция для получения иконки статуса проверки
def _status_icon(status: Status, ansi: Ansi) -> str:
    mapping = {
        "OK": ("✔", Ansi.GREEN),
        "WARNING": ("⚠", Ansi.YELLOW),
        "FAILED": ("❌", Ansi.RED),
        "MISSING": ("⚠", Ansi.YELLOW),
    }
    symbol, color = mapping[status]
    return ansi.wrap(symbol, color)


# Функция для вывода раздела отчета
def _print_section(title: str, items: list[str], stream: TextIO, ansi: Ansi) -> None:
    if not items:
        return
    print(f"\n{ansi.wrap(title, Ansi.BOLD)}", file=stream)
    for item in items:
        print(item, file=stream)


# Функция для вывода отчета о результатах проверки env файла
def _print_file_report(
    report: FileReport,
    stream: TextIO,
    ansi: Ansi,
    verbose: bool,
) -> None:
    rel = report.path.name
    print(f"\n{ansi.wrap('─' * 38, Ansi.DIM)}", file=stream)
    print(ansi.wrap(rel, Ansi.BOLD, Ansi.CYAN), file=stream)

    if not report.exists:
        print(f"{_status_icon('MISSING', ansi)} file not found", file=stream)
        return

    print(f"{_status_icon(report.status, ansi)} {report.status}", file=stream)
    _print_section("Missing:", report.missing, stream=stream, ansi=ansi)
    _print_section("Unused:", report.unused, stream=stream, ansi=ansi)
    _print_section("Empty:", report.empty, stream=stream, ansi=ansi)

    if report.duplicates:
        print(f"\n{ansi.wrap('Duplicates:', Ansi.BOLD)}", file=stream)
        for key, lines in sorted(report.duplicates.items()):
            joined = ", ".join(str(line) for line in lines)
            print(f"{key} (lines {joined})", file=stream)

    if report.syntax_issues:
        print(f"\n{ansi.wrap('Syntax:', Ansi.BOLD)}", file=stream)
        for issue in report.syntax_issues:
            print(f"line {issue.line}: {issue.message}", file=stream)

    if verbose and report.exists:
        issue_count = len(report.missing) + len(report.unused) + len(report.empty)
        label = ansi.wrap("Variables:", Ansi.DIM)
        print(f"\n{label} {issue_count} issues", file=stream)


# Функция для вывода отчета о результатах проверки всех env файлов
def print_report(
    report: DoctorReport,
    stream: TextIO,
    ansi: Ansi,
    verbose: bool,
) -> None:
    print(f"\n{ansi.wrap('─' * 38, Ansi.DIM)}", file=stream)
    print(ansi.wrap("Reference:", Ansi.BOLD), file=stream)
    print(report.reference.name, file=stream)
    print(f"Variables: {len(report.reference_keys)}", file=stream)

    for file_report in report.files:
        _print_file_report(file_report, stream=stream, ansi=ansi, verbose=verbose)

    print(f"\n{ansi.wrap('─' * 38, Ansi.DIM)}", file=stream)
    print(ansi.wrap("Summary", Ansi.BOLD), file=stream)
    for file_report in report.files:
        label = file_report.path.name.ljust(12)
        if not file_report.exists:
            line = f"{label} MISSING"
            print(ansi.wrap(line, Ansi.YELLOW), file=stream)
            continue
        color = {
            "OK": Ansi.GREEN,
            "WARNING": Ansi.YELLOW,
            "FAILED": Ansi.RED,
            "MISSING": Ansi.YELLOW,
        }[file_report.status]
        print(ansi.wrap(f"{label} {file_report.status}", color), file=stream)


# Функция для вывода отчета о результатах проверки всех env файлов в формате JSON
def print_json_report(report: DoctorReport, stream: TextIO) -> None:
    payload = {
        "reference": str(report.reference),
        "reference_variable_count": len(report.reference_keys),
        "failed": report.failed,
        "warned": report.warned,
        "files": [
            {
                **asdict(file_report),
                "path": str(file_report.path),
                "syntax_issues": [asdict(issue) for issue in file_report.syntax_issues],
            }
            for file_report in report.files
        ],
    }
    json.dump(payload, stream, indent=2, ensure_ascii=False)
    stream.write("\n")


# Функция для вывода списка файлов, которые будут проверены
def _print_existence(target_paths: list[Path], stream: TextIO, ansi: Ansi) -> None:
    print(ansi.wrap("Files:", Ansi.BOLD), file=stream)
    for path in target_paths:
        if path.is_file():
            print(f"{ansi.wrap('✔', Ansi.GREEN)} {path.name}", file=stream)
        else:
            print(f"{ansi.wrap('⚠', Ansi.YELLOW)} {path.name} not found", file=stream)


# Функция для разрешения путей к env файлам
def resolve_paths(root: Path, names: list[str]) -> list[Path]:
    return [root / name for name in names]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        default=str(DEFAULT_REFERENCE),
        help="файл с переменными, которые должны быть в env "
        "файлах (default: .env.example)",
    )
    parser.add_argument(
        "--env",
        action="append",
        dest="env_files",
        metavar="FILE",
        help="файл env для проверки (repeatable; default: .env .env.dev .env.prod)",
    )
    parser.add_argument(
        "--root",
        default=str(ROOT),
        help="корневая директория проекта",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--verbose", action="store_true", help="extra details")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="считать пустые/неиспользуемые переменные как ошибки",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="отключить ANSI цвета",
    )
    return parser.parse_args(argv)


# Функция для запуска скрипта
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    reference = Path(args.reference)
    if not reference.is_absolute():
        reference = root / reference

    env_names = args.env_files or list(DEFAULT_TARGETS)
    targets = resolve_paths(root, env_names)

    use_color = not args.no_color and sys.stdout.isatty() and not args.json
    if os.environ.get("NO_COLOR"):
        use_color = False
    ansi = Ansi(enabled=use_color)

    try:
        report = build_report(
            reference_path=reference,
            target_paths=targets,
            strict=args.strict,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print_json_report(report, stream=sys.stdout)
    else:
        _print_existence(targets, stream=sys.stdout, ansi=ansi)
        print_report(report, stream=sys.stdout, ansi=ansi, verbose=args.verbose)

    if report.failed:
        return 1
    if args.strict and report.warned:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
