from __future__ import annotations

from botocore.exceptions import ClientError
import boto3

from domain.knowledge_base import (
    KnowledgeBaseObjectStorage,
)

from infrastructure.config.settings import get_settings


class MinIOKnowledgeBaseStorage(
    KnowledgeBaseObjectStorage,
):
    """
    S3-compatible object storage adapter for Knowledge Base files.
    """

    def __init__(self) -> None:
        settings = get_settings()

        self._bucket = settings.minio_bucket

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            region_name="us-east-1",
        )

        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(
                Bucket=self._bucket,
            )
            return
        except ClientError as exc:
            error_code = str(
                exc.response.get(
                    "Error",
                    {},
                ).get(
                    "Code",
                    "",
                )
            )

            if error_code not in {
                "404",
                "NoSuchBucket",
                "NotFound",
            }:
                raise

        self._client.create_bucket(
            Bucket=self._bucket,
        )

    def put(
        self,
        object_key: str,
        data: bytes,
        *,
        content_type: str,
    ) -> None:
        if not object_key.strip():
            raise ValueError(
                "object_key cannot be empty."
            )

        if not data:
            raise ValueError(
                "data cannot be empty."
            )

        self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

    def get(
        self,
        object_key: str,
    ) -> bytes:
        response = self._client.get_object(
            Bucket=self._bucket,
            Key=object_key,
        )

        return response["Body"].read()

    def delete(
        self,
        object_key: str,
    ) -> None:
        self._client.delete_object(
            Bucket=self._bucket,
            Key=object_key,
        )

    def exists(
        self,
        object_key: str,
    ) -> bool:
        try:
            self._client.head_object(
                Bucket=self._bucket,
                Key=object_key,
            )
            return True
        except ClientError as exc:
            error_code = str(
                exc.response.get(
                    "Error",
                    {},
                ).get(
                    "Code",
                    "",
                )
            )

            if error_code in {
                "404",
                "NoSuchKey",
                "NotFound",
            }:
                return False

            raise