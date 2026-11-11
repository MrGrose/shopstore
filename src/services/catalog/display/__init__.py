import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "RESOLVER_VERSION": ("constants", "RESOLVER_VERSION"),
    "CoverageReport": ("reconciler", "CoverageReport"),
    "DisplayMappingResolver": ("resolver", "DisplayMappingResolver"),
    "StorefrontCompatParamError": ("compat_params", "StorefrontCompatParamError"),
    "StorefrontCompatParams": ("compat_params", "StorefrontCompatParams"),
    "StorefrontMappingReconciler": ("reconciler", "StorefrontMappingReconciler"),
    "StorefrontMappingRepository": ("repository", "StorefrontMappingRepository"),
    "StorefrontNodeFilter": ("compat_params", "StorefrontNodeFilter"),
    "StorefrontPlacementService": ("placement_service", "StorefrontPlacementService"),
    "StorefrontReleaseError": ("release_service", "StorefrontReleaseError"),
    "StorefrontReleaseService": ("release_service", "StorefrontReleaseService"),
    "is_catalogized_product": ("taxonomy", "is_catalogized_product"),
    "is_invalid_taxonomy_product": ("taxonomy", "is_invalid_taxonomy_product"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    if module_name == "repository":
        module = importlib.import_module("src.repositories.storefront_mapping")
        return getattr(module, attr_name)
    module = importlib.import_module(f"src.services.catalog.display.{module_name}")
    return getattr(module, attr_name)


__all__ = list(_LAZY_EXPORTS)
