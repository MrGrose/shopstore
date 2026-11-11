import ast
from pathlib import Path

from src.services.catalog.display.ux_blueprint import (
    SCHEMA_VERSION,
    StorefrontUxBlueprintError,
    compute_content_checksum,
    load_storefront_ux_blueprint,
    validate_storefront_ux_blueprint,
)


def _legacy_import_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_greenfield_seed_modules_do_not_import_legacy_nav() -> None:
    display_dir = Path("src/services/catalog/display")
    forbidden_modules = (
        "src.services.catalog.read.storefront_nav",
        "src.services.catalog.read.storefront_category_map",
        "src.services.catalog.read.storefront_visibility",
    )
    paths = [
        display_dir / "seed.py",
        Path("src/services/catalog/read/service.py"),
    ]
    for path in paths:
        imported = _legacy_import_modules(path)
        for mod in forbidden_modules:
            assert mod not in imported, f"{path} imports legacy {mod}"
    seed_src = (display_dir / "seed.py").read_text(encoding="utf-8")
    assert "STOREFRONT_EXCLUDED_L2" not in seed_src
    assert "list_active_catalogized_taxonomy" not in seed_src
    assert "_seed_sections" not in seed_src
    assert "_seed_chips_and_rules" not in seed_src
    assert "_seed_root_nodes" in seed_src
    assert "_seed_section_nodes" in seed_src
    assert "_seed_chip_nodes" in seed_src
    assert "resolve_chip_display_key" not in seed_src


def test_ux_blueprint_schema_version_checksum_and_counts() -> None:
    blueprint = load_storefront_ux_blueprint()
    assert blueprint["schema_version"] == SCHEMA_VERSION
    assert blueprint["content_checksum"]
    assert len(blueprint["nodes"]) == 237
    assert len(blueprint["rules"]) == 403
    assert "derived_from_release_id" in blueprint
    assert "review_note" in blueprint
    assert compute_content_checksum(blueprint["nodes"], blueprint["rules"]) == (
        blueprint["content_checksum"]
    )


def test_ux_blueprint_all_mapped_rules_reference_chip_nodes() -> None:
    blueprint = load_storefront_ux_blueprint()
    chip_keys = {
        n["display_key"] for n in blueprint["nodes"] if n["node_type"] == "chip"
    }
    mapped = [r for r in blueprint["rules"] if r["outcome"] == "mapped"]
    assert len(mapped) == 390
    for rule in mapped:
        assert rule["chip_display_key"] in chip_keys


def test_ux_blueprint_display_keys_unique() -> None:
    blueprint = load_storefront_ux_blueprint()
    keys = [n["display_key"] for n in blueprint["nodes"]]
    assert len(keys) == len(set(keys))


def test_ux_blueprint_overgrips_single_node_with_supplier_rules() -> None:
    blueprint = load_storefront_ux_blueprint()
    overgrips_nodes = [
        n
        for n in blueprint["nodes"]
        if n["display_key"] == "tennis.accessories.overgrips"
    ]
    assert len(overgrips_nodes) == 1
    node = overgrips_nodes[0]
    assert node["parent_display_key"] == "tennis.accessories"
    legacy = (node.get("metadata_json") or {}).get("legacy_query_keys") or []
    assert "tennis.overgrips" in legacy

    overgrips_rules = [
        r
        for r in blueprint["rules"]
        if r.get("chip_display_key") == "tennis.accessories.overgrips"
    ]
    assert len(overgrips_rules) == 3
    paths = {
        (r.get("category_l1"), r.get("category_l2"), r.get("category_l3"))
        for r in overgrips_rules
    }
    assert ("Tennis", "Overgrips", None) in paths
    assert ("Accessories", "Overgrips", None) in paths
    assert ("Accessories", "Grips", "Overgrips") in paths


def test_ux_blueprint_sections_are_l1_not_supplier_l2() -> None:
    blueprint = load_storefront_ux_blueprint()
    tennis_sections = [
        n
        for n in blueprint["nodes"]
        if n["sport_type"] == "Tennis" and n["node_type"] == "section"
    ]
    slugs = {n["slug"] for n in tennis_sections}
    assert "accessories" in slugs
    assert "overgrips" not in slugs
    assert "grips" not in slugs


def test_ux_blueprint_rejects_checksum_mismatch() -> None:
    blueprint = load_storefront_ux_blueprint()
    broken = dict(blueprint)
    broken["content_checksum"] = "0" * 64
    try:
        validate_storefront_ux_blueprint(broken)
    except StorefrontUxBlueprintError as exc:
        assert "checksum mismatch" in str(exc)
    else:
        raise AssertionError("expected checksum mismatch error")
