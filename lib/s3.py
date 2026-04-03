from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3

from lib.timestamp_utils import get_current_timestamp

DEFAULT_REGION_NAME = "us-central-2"


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


if __name__ == "__main__":
    bucket = "jspsych-mirror-view-3"
    prefix = "precomputed_assignments"
    iteration_ts = get_current_timestamp()
    object_key = f"{prefix}/{iteration_ts}/test.txt"
    script_body = b'print("mirrorview-pilot S3 upload OK")\n'
    store = S3(bucket)
    store.upload_bytes(object_key, script_body, content_type="text/x-python")
