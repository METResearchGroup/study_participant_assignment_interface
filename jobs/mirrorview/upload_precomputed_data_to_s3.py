"""Uploads precomputed data to S3.

We'll hard-code the s3 path.
"""

import argparse

S3_BUCKET = "mirrorview-pilot"
S3_PREFIX = "precomputed_assignments"
LOCAL_PREFIX = "data/mirrorview/"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=str, required=True)
    args = parser.parse_args()

    print(args.path)
