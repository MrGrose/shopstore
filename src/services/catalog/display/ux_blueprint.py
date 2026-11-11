import hashlib
import json
import re
from pathlib import Path

from src.services.catalog.display.constants import (
    MATCH_MODE_EXACT,
    MATCH_MODE_L2_ANY_L3,
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
    OUTCOME_EXCLUDED,
    OUTCOME_MAPPED,
)

SCHEMA_VERSION = 1
BLUEPRINT_FILENAME = "storefront_ux_blueprint.json"
_BLUEPRINT_PATH = Path(__file__).with_name(BLUEPRINT_FILENAME)

_NODE_TYPES = frozenset({NODE_TYPE_ROOT, NODE_TYPE_SECTION, NODE_TYPE_CHIP})
_MATCH_MODES = frozenset({MATCH_MODE_EXACT, MATCH_MODE_L2_ANY_L3})
_OUTCOMES = frozenset({OUTCOME_MAPPED, OUTCOME_EXCLUDED})
_CYRILLIC_LABEL_RE = re.compile(r"[\u0400-\u04FF]")
_FORBIDDEN_PUBLIC_LABELS = frozenset(
    {
        "All",
        "Tennis",
        "Padel",
        "Running",
        "Balls",
        "Shoes",
        "Accessories",
        "Overgrips",
        "Rackets",
        "Bags",
    }
)


class StorefrontUxBlueprintError(Exception):
    pass


# Канонический SHA256 payload nodes+rules для checksum gate.
def compute_content_checksum(nodes: list[dict], rules: list[dict]) -> str:
    payload = {"nodes": nodes, "rules": rules}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Проверяет schema, checksum, уникальность keys и rule→chip ссылки.
def validate_storefront_ux_blueprint(payload: dict) -> None:
    schema_version = payload.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise StorefrontUxBlueprintError(
            f"schema_version={schema_version!r}, ожидается {SCHEMA_VERSION}"
        )

    nodes = payload.get("nodes")
    rules = payload.get("rules")
    if not isinstance(nodes, list) or not nodes:
        raise StorefrontUxBlueprintError("nodes must be a non-empty list")
    if not isinstance(rules, list) or not rules:
        raise StorefrontUxBlueprintError("rules must be a non-empty list")

    expected_checksum = payload.get("content_checksum")
    if not expected_checksum:
        raise StorefrontUxBlueprintError("content_checksum is required")
    actual_checksum = compute_content_checksum(nodes, rules)
    if expected_checksum != actual_checksum:
        raise StorefrontUxBlueprintError(
            "content_checksum mismatch: "
            f"expected {expected_checksum}, got {actual_checksum}"
        )

    node_by_key: dict[str, dict] = {}
    for idx, node in enumerate(nodes):
        _validate_node(node, idx)
        display_key = str(node["display_key"])
        if display_key in node_by_key:
            raise StorefrontUxBlueprintError(f"duplicate display_key {display_key!r}")
        node_by_key[display_key] = node

    chip_keys = {
        key for key, node in node_by_key.items() if node["node_type"] == NODE_TYPE_CHIP
    }
    _validate_legacy_keys(node_by_key)

    mapped_rules = 0
    for idx, rule in enumerate(rules):
        _validate_rule(rule, idx, chip_keys)
        if rule.get("outcome") == OUTCOME_MAPPED:
            mapped_rules += 1
            chip_key = rule.get("chip_display_key")
            if not chip_key or str(chip_key) not in chip_keys:
                raise StorefrontUxBlueprintError(
                    f"mapped rule[{idx}] chip_display_key={chip_key!r} not found"
                )

    if mapped_rules == 0:
        raise StorefrontUxBlueprintError("no mapped rules in blueprint")


def _validate_node(node: dict, idx: int) -> None:
    required = (
        "sport_type",
        "node_type",
        "display_key",
        "slug",
        "label_ru",
        "sort_order",
    )
    for field in required:
        if field not in node:
            raise StorefrontUxBlueprintError(f"node[{idx}] missing {field}")
    if node["node_type"] not in _NODE_TYPES:
        raise StorefrontUxBlueprintError(
            f"node[{idx}] invalid node_type={node['node_type']!r}"
        )
    _validate_public_label_ru(node, idx)
    parent_key = node.get("parent_display_key")
    if node["node_type"] == NODE_TYPE_ROOT:
        if parent_key is not None:
            raise StorefrontUxBlueprintError(
                f"node[{idx}] root must not have parent_display_key"
            )
    else:
        if not parent_key:
            raise StorefrontUxBlueprintError(
                f"node[{idx}] {node['node_type']} requires parent_display_key"
            )


# Публичный label категории: непустой label_ru с кириллицей, без English fallback.
def _validate_public_label_ru(node: dict, idx: int) -> None:
    raw = node.get("label_ru")
    label = str(raw or "").strip()
    if not label:
        raise StorefrontUxBlueprintError(f"node[{idx}] label_ru is required")
    if label in _FORBIDDEN_PUBLIC_LABELS:
        raise StorefrontUxBlueprintError(
            f"node[{idx}] label_ru={label!r} is forbidden English public label"
        )
    if not _CYRILLIC_LABEL_RE.search(label):
        raise StorefrontUxBlueprintError(
            f"node[{idx}] label_ru={label!r} must contain Cyrillic characters"
        )


def _validate_rule(rule: dict, idx: int, chip_keys: set[str]) -> None:
    required = ("sport_type", "match_mode", "outcome")
    for field in required:
        if field not in rule:
            raise StorefrontUxBlueprintError(f"rule[{idx}] missing {field}")
    if rule["match_mode"] not in _MATCH_MODES:
        raise StorefrontUxBlueprintError(
            f"rule[{idx}] invalid match_mode={rule['match_mode']!r}"
        )
    if rule["outcome"] not in _OUTCOMES:
        raise StorefrontUxBlueprintError(
            f"rule[{idx}] invalid outcome={rule['outcome']!r}"
        )
    chip_key = rule.get("chip_display_key")
    if rule["outcome"] == OUTCOME_EXCLUDED:
        if chip_key is not None:
            raise StorefrontUxBlueprintError(
                f"rule[{idx}] excluded rule must not have chip_display_key"
            )
        return
    if not chip_key:
        raise StorefrontUxBlueprintError(
            f"rule[{idx}] mapped rule requires chip_display_key"
        )
    if str(chip_key) not in chip_keys:
        raise StorefrontUxBlueprintError(
            f"rule[{idx}] chip_display_key={chip_key!r} not in nodes"
        )


# Legacy keys уникальны внутри (sport, section) и внутри sport (bare lookup).
def _validate_legacy_keys(node_by_key: dict[str, dict]) -> None:
    seen_section: dict[tuple[str, str, str], str] = {}
    seen_sport: dict[tuple[str, str], str] = {}
    for display_key, node in node_by_key.items():
        if node["node_type"] != NODE_TYPE_CHIP:
            continue
        parent_key = node.get("parent_display_key")
        if not parent_key:
            continue
        parent = node_by_key.get(str(parent_key))
        if parent is None or parent["node_type"] != NODE_TYPE_SECTION:
            continue
        sport = str(node["sport_type"])
        section_slug = str(parent["slug"])
        meta = node.get("metadata_json") or {}
        legacy_keys = meta.get("legacy_query_keys") or []
        for legacy in legacy_keys:
            legacy_str = str(legacy)
            section_scope = (sport, section_slug, legacy_str)
            prev_section = seen_section.get(section_scope)
            if prev_section is not None:
                raise StorefrontUxBlueprintError(
                    f"duplicate legacy key {legacy_str!r} in "
                    f"{sport}/{section_slug}: {prev_section} and {display_key}"
                )
            seen_section[section_scope] = display_key

            sport_scope = (sport, legacy_str)
            prev_sport = seen_sport.get(sport_scope)
            if prev_sport is not None:
                raise StorefrontUxBlueprintError(
                    f"duplicate legacy key {legacy_str!r} in {sport}: "
                    f"{prev_sport} and {display_key}"
                )
            seen_sport[sport_scope] = display_key


# Загружает version-controlled UX blueprint с validation gate.
def load_storefront_ux_blueprint() -> dict:
    raw = _BLUEPRINT_PATH.read_text(encoding="utf-8")
    payload = json.loads(raw)
    validate_storefront_ux_blueprint(payload)
    return payload
