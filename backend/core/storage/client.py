"""Abstracao de storage de objetos (MinIO/S3), com prefixo obrigatorio por tenant.

Nenhuma chave e aceita sem tenant_id explicito — mesma politica de "argumento obrigatorio, nunca
filtro opcional" usada em core.tenancy e core.cache (ver ADR-0002).
"""

from __future__ import annotations

import uuid
from typing import BinaryIO

import boto3
from botocore.client import Config as BotoConfig

from core.config import get_settings


def _tenant_key(tenant_id: uuid.UUID, key: str) -> str:
    return f"tenant/{tenant_id}/{key}"


class StorageClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.storage_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def ensure_bucket(self) -> None:
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if self._bucket not in existing:
            self._client.create_bucket(Bucket=self._bucket)

    def put_object(
        self, tenant_id: uuid.UUID, key: str, body: bytes | BinaryIO, content_type: str
    ) -> str:
        full_key = _tenant_key(tenant_id, key)
        self._client.put_object(
            Bucket=self._bucket, Key=full_key, Body=body, ContentType=content_type
        )
        return full_key

    def get_object(self, tenant_id: uuid.UUID, key: str) -> bytes:
        full_key = _tenant_key(tenant_id, key)
        response = self._client.get_object(Bucket=self._bucket, Key=full_key)
        return response["Body"].read()

    def generate_presigned_url(self, tenant_id: uuid.UUID, key: str, expires_in: int = 300) -> str:
        full_key = _tenant_key(tenant_id, key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": full_key},
            ExpiresIn=expires_in,
        )


_storage_client: StorageClient | None = None


def get_storage_client() -> StorageClient:
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient()
    return _storage_client
