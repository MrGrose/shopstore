from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from src.core.config import settings
from src.storage.dual import DualStorage
from src.storage.factory import get_storage
from src.storage.local import LocalStorage
from src.storage.s3 import S3Storage


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._buf = BytesIO(data)

    def read(self) -> bytes:
        return self._buf.read()

    def close(self) -> None:
        self._buf.close()


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}
        self.buckets: set[str] = set()
        self.fail_put = False
        self.fail_delete = False

    def head_bucket(self, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def create_bucket(self, Bucket: str) -> None:
        self.buckets.add(Bucket)

    def put_object(self, **kwargs: object) -> None:
        if self.fail_put:
            raise ClientError({"Error": {"Code": "503"}}, "PutObject")
        bucket = str(kwargs["Bucket"])
        key = str(kwargs["Key"])
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        content_type = kwargs.get("ContentType")
        ct = str(content_type) if isinstance(content_type, str) else None
        self.objects[(bucket, key)] = (body, ct)

    def delete_object(self, Bucket: str, Key: str) -> None:
        if self.fail_delete:
            raise ClientError({"Error": {"Code": "503"}}, "DeleteObject")
        self.objects.pop((Bucket, Key), None)

    def head_object(self, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        data, _ct = self.objects[(Bucket, Key)]
        return {"ContentLength": len(data)}

    def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        data, _ct = self.objects[(Bucket, Key)]
        return {"Body": FakeBody(data), "ContentLength": len(data)}

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs.get("Prefix") or "")
        contents = [
            {"Key": key, "LastModified": datetime.now(UTC)}
            for (bkt, key) in sorted(self.objects)
            if bkt == bucket and key.startswith(prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}


# S3Storage поверх in-memory клиента.
def _s3() -> S3Storage:
    return S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=FakeS3Client(),
    )


# Контракт put/read/exists/delete/missing/public_url.
def _assert_contract(storage: S3Storage | LocalStorage | DualStorage) -> None:
    key = "products/a.jpg"
    storage.put(key, b"jpeg-bytes", "image/jpeg")
    assert storage.exists(key) is True
    assert storage.read(key) == b"jpeg-bytes"
    assert storage.public_url(key) == "/media/products/a.jpg"
    storage.delete(key)
    assert storage.exists(key) is False
    with pytest.raises(FileNotFoundError):
        storage.read(key)
    storage.delete(key)


def test_s3_storage_contract() -> None:
    _assert_contract(_s3())


def test_s3_storage_missing_exists_false() -> None:
    storage = _s3()
    assert storage.exists("products/nope.jpg") is False


def test_dual_storage_reads_s3_then_local(tmp_path: Path) -> None:
    local = LocalStorage(root=tmp_path)
    s3 = _s3()
    dual = DualStorage(s3, local)
    key = "products/only-local.jpg"
    local.put(key, b"from-disk", "image/jpeg")
    assert dual.read(key) == b"from-disk"
    dual.put(key, b"both", "image/jpeg")
    assert s3.read(key) == b"both"
    assert local.read(key) == b"both"
    assert dual.public_url(key) == "/media/products/only-local.jpg"


def test_get_storage_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_ENDPOINT", "http://seaweedfs:8333")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "shopstore")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "secret")
    monkeypatch.setattr(settings, "S3_BUCKET", "shopstore-media")
    fake = FakeS3Client()
    monkeypatch.setattr("src.storage.s3.boto3.client", lambda *args, **kwargs: fake)
    storage = get_storage()
    storage.put("products/x.jpg", b"x", "image/jpeg")
    assert storage.read("products/x.jpg") == b"x"


def test_get_storage_rejects_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "minio")
    with pytest.raises(RuntimeError, match="не поддерживается"):
        get_storage()


def test_s3_ensure_bucket_does_not_create_on_403() -> None:
    class ForbiddenHead:
        def head_bucket(self, Bucket: str) -> None:
            raise ClientError({"Error": {"Code": "403"}}, "HeadBucket")

        def create_bucket(self, Bucket: str) -> None:
            raise AssertionError("create_bucket must not run on 403")

    with pytest.raises(ClientError):
        S3Storage(
            "http://seaweedfs:8333",
            "shopstore",
            "secret",
            "shopstore-media",
            client=ForbiddenHead(),
        )


def test_dual_put_propagates_s3_failure(tmp_path: Path) -> None:
    local = LocalStorage(root=tmp_path)
    fake = FakeS3Client()
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    fake.fail_put = True
    dual = DualStorage(s3, local)
    key = "products/partial.jpg"
    with pytest.raises(ClientError):
        dual.put(key, b"data", "image/jpeg")
    assert local.read(key) == b"data"
    assert s3.exists(key) is False


def test_dual_delete_local_first_no_local_resurrect(tmp_path: Path) -> None:
    local = LocalStorage(root=tmp_path)
    fake = FakeS3Client()
    s3 = S3Storage(
        "http://seaweedfs:8333",
        "shopstore",
        "secret",
        "shopstore-media",
        client=fake,
    )
    dual = DualStorage(s3, local)
    key = "products/gone.jpg"
    dual.put(key, b"data", "image/jpeg")
    fake.fail_delete = True
    with pytest.raises(ClientError):
        dual.delete(key)
    assert local.exists(key) is False
    assert s3.exists(key) is True
    dual_again = DualStorage(s3, local)
    assert dual_again.read(key) == b"data"
    rollback = LocalStorage(root=tmp_path)
    assert rollback.exists(key) is False


def test_s3_iter_keys_lists_prefix() -> None:
    storage = _s3()
    storage.put("products/a.jpg", b"a", "image/jpeg")
    storage.put("products/b.jpg", b"b", "image/jpeg")
    keys = storage.iter_keys("products/")
    assert "products/a.jpg" in keys
    assert "products/b.jpg" in keys


def test_s3_iter_key_mtimes_includes_last_modified() -> None:
    storage = _s3()
    storage.put("support/1/a.jpg", b"a", "image/jpeg")
    rows = dict(storage.iter_key_mtimes("support/"))
    assert "support/1/a.jpg" in rows
    assert isinstance(rows["support/1/a.jpg"], datetime)
