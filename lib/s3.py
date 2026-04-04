from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import boto3
import pandas as pd

DEFAULT_REGION_NAME = "us-east-2"


class S3:
    def __init__(self, bucket: str, *, region_name: str | None = None) -> None:
        client_kwargs: dict[str, Any] = {}
        if region_name is not None:
            client_kwargs["region_name"] = region_name
        self._bucket = bucket
        self._client: Any = boto3.client("s3", **client_kwargs)

    @property
    def bucket(self) -> str:
        return self._bucket

    def upload_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        key = key.lstrip("/")
        extra: dict[str, str] = {}
        if content_type is not None:
            extra["ContentType"] = content_type
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body, **extra)

    def upload_file(
        self,
        local_path: str | Path,
        key: str,
        *,
        content_type: str | None = None,
    ) -> None:
        path = Path(local_path)
        data = path.read_bytes()
        ct = content_type
        if ct is None:
            suffix = path.suffix.lower()
            if suffix == ".json":
                ct = "application/json"
            elif suffix == ".csv":
                ct = "text/csv"
        self.upload_bytes(key, data, content_type=ct)

    def get_bytes(self, key: str) -> bytes:
        key = key.lstrip("/")
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def list_keys_ordered(self, prefix: str) -> list[str]:
        """List object keys for a prefix in ascending lexical order."""
        normalized_prefix = prefix.lstrip("/")
        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self._bucket, Prefix=normalized_prefix)

        keys: list[str] = []
        for page in pages:
            for item in page.get("Contents", []):
                key = item.get("Key")
                if key:
                    keys.append(key)

        return sorted(keys)

    def load_csv_to_dataframe(self, key: str) -> pd.DataFrame:
        """Load a CSV object from S3 into a pandas DataFrame."""
        csv_bytes = self.get_bytes(key)
        return pd.read_csv(BytesIO(csv_bytes))
