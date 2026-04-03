"""Smoke test for S3."""

from lib.s3 import S3
from lib.timestamp_utils import get_current_timestamp

if __name__ == "__main__":
    bucket = "jspsych-mirror-view-3"
    prefix = "precomputed_assignments"
    iteration_ts = get_current_timestamp()
    object_key = f"{prefix}/{iteration_ts}/test.txt"
    script_body = b'print("mirrorview-pilot S3 upload OK")\n'
    store = S3(bucket)
    store.upload_bytes(object_key, script_body, content_type="text/x-python")
    print(f"Uploaded {object_key} to {bucket}")
