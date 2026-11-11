import ast
from pathlib import Path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_public_api_does_not_import_catalog_slice() -> None:
    public_paths = [
        Path("src/api/routers/product.py"),
        Path("src/services/catalog/display/runtime.py"),
        Path("src/services/catalog/display/catalog_read.py"),
        Path("src/services/catalog/read/count_cache.py"),
        Path("src/services/catalog/read/facets_cache.py"),
    ]
    forbidden = (
        "src.services.catalog.display.catalog_slice",
        "CatalogRawSlice",
    )
    for path in public_paths:
        source = path.read_text(encoding="utf-8")
        imported = _imported_modules(path)
        for token in forbidden:
            assert token not in imported, f"{path} imports {token}"
            assert "catalog_slice" not in source, f"{path} references catalog_slice"
