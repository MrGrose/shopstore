import pytest

from src.middleware.cache_control import NO_STORE, resolve_cache_policy


def test_resolve_cache_policy_public_products_list() -> None:
    policy = resolve_cache_policy("GET", "/products")
    assert policy.cache_control == "public, max-age=30, stale-while-revalidate=120"


def test_resolve_cache_policy_public_catalog_taxonomy() -> None:
    policy = resolve_cache_policy("GET", "/catalog/taxonomy")
    assert "max-age=300" in policy.cache_control


def test_resolve_cache_policy_public_product_detail() -> None:
    policy = resolve_cache_policy("GET", "/product/42")
    assert "max-age=60" in policy.cache_control


def test_resolve_cache_policy_cart_no_store() -> None:
    policy = resolve_cache_policy("GET", "/cart/me")
    assert policy.cache_control == NO_STORE


def test_resolve_cache_policy_users_no_store() -> None:
    policy = resolve_cache_policy("GET", "/users/me")
    assert policy.cache_control == NO_STORE


def test_resolve_cache_policy_mutations_no_store() -> None:
    policy = resolve_cache_policy("POST", "/products")
    assert policy.cache_control == NO_STORE


def test_resolve_cache_policy_admin_import_no_store() -> None:
    policy = resolve_cache_policy(
        "GET",
        "/products/catalog/import/status",
    )
    assert policy.cache_control == NO_STORE


@pytest.mark.parametrize(
    ("path", "snippet"),
    [
        ("/products/count", "max-age=60"),
        ("/products/facets", "max-age=60"),
        ("/products/meta", "max-age=60"),
        ("/catalog/navigation", "max-age=60"),
        ("/products/subcategories", "max-age=60"),
        ("/products/top-categories", "max-age=60"),
    ],
)
def test_resolve_cache_policy_public_catalog_meta(path: str, snippet: str) -> None:
    policy = resolve_cache_policy("GET", path)
    assert snippet in policy.cache_control


def test_resolve_cache_policy_product_media_immutable() -> None:
    policy = resolve_cache_policy("GET", "/media/products/abc.jpg")
    assert policy.cache_control == "public, max-age=31536000, immutable"


def test_resolve_cache_policy_media_support_no_store() -> None:
    policy = resolve_cache_policy("GET", "/media/support/secret.jpg")
    assert policy.cache_control == NO_STORE
