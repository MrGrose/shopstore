from datetime import datetime
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

_MISSING = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}


# True if S3 treated the key/bucket as missing.
def _is_missing(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code in _MISSING


class S3Storage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        if client is not None:
            self._client = client
        else:
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
        self._ensure_bucket()

    # Создаёт bucket только если head вернул missing, не 403.
    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if not _is_missing(exc):
                raise
            self._client.create_bucket(Bucket=self._bucket)

    # Пишет object по logical key.
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self._client.put_object(**kwargs)

    # Удаляет object; отсутствующий ключ — no-op.
    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    # True, если object есть.
    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise
        return True

    # Читает object; нет ключа → FileNotFoundError.
    def read(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise
        body = resp["Body"]
        try:
            return body.read()
        finally:
            body.close()

    # Application URL, не S3 endpoint.
    def public_url(self, key: str) -> str:
        from src.utils.images import public_url_for_storage_key

        return public_url_for_storage_key(key)

    # Страницы list_objects_v2 с данным prefix.
    def _list_objects(self, prefix: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents") or []:
                items.append(obj)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
            if not token:
                break
        return items

    # Ключи objects с данным prefix.
    def iter_keys(self, prefix: str = "") -> list[str]:
        return [str(obj["Key"]) for obj in self._list_objects(prefix)]

    # Ключи и LastModified; нет метки → None.
    def iter_key_mtimes(self, prefix: str = "") -> list[tuple[str, datetime | None]]:
        rows: list[tuple[str, datetime | None]] = []
        for obj in self._list_objects(prefix):
            raw = obj.get("LastModified")
            mtime = raw if isinstance(raw, datetime) else None
            rows.append((str(obj["Key"]), mtime))
        return rows
