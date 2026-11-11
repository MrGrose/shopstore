import pytest

from src.storage.s3 import S3Storage


# Пропускает тест, если локальный SeaweedFS S3 не слушает :8333.
def _s3_or_skip() -> S3Storage:
    try:
        storage = S3Storage(
            "http://127.0.0.1:8333",
            "shopstore",
            "shopstore-dev-secret-change-me",
            "shopstore-media",
        )
        storage.put("products/_probe.jpg", b"probe", "image/jpeg")
        storage.delete("products/_probe.jpg")
    except Exception as exc:
        pytest.skip(f"SeaweedFS S3 недоступен: {exc}")
    return storage


@pytest.mark.integration
def test_seaweedfs_s3_storage_roundtrip() -> None:
    storage = _s3_or_skip()
    key = "products/poc-roundtrip.jpg"
    payload = b"\xff\xd8\xff poc-jpeg"
    storage.put(key, payload, "image/jpeg")
    assert storage.exists(key) is True
    assert storage.read(key) == payload
    assert storage.public_url(key) == "/media/products/poc-roundtrip.jpg"
    storage.delete(key)
    assert storage.exists(key) is False
