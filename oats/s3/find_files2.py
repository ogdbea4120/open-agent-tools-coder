#!/usr/bin/env python3

"""
S3 File Finder Module
Finds files in S3 buckets matching specific prefixes.
"""

import argparse
import re
import boto3
import traceback
from botocore.exceptions import ClientError
from typing import List
from oats.eng.resources import EngResources
from oats.log import cl

log = cl('s3.ff.2')


def get_s3_client() -> boto3.client:
    """Create and return an S3 client."""
    return boto3.client("s3")


def parse_s3_url(s3_url: str) -> tuple:
    """
    Parse S3 URL into bucket and prefix.

    Args:
        s3_url (str): S3 URL in format s3://bucket/prefix/

    Returns:
        tuple: (bucket, prefix)

    Raises:
        ValueError: If URL format is invalid
    """
    if not s3_url.startswith("s3://"):
        raise ValueError(f"Invalid S3 URL format: {s3_url}")

    # Remove s3:// prefix
    path = s3_url[5:]

    # Split on first slash to get bucket and prefix
    parts = path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URL format: {s3_url}")

    bucket, prefix = parts
    # Ensure prefix ends with '/'
    if not prefix.endswith("/"):
        prefix += "/"

    return bucket, prefix


def find_files_in_s3(s3_loc: str, prefixes: List[str], max_keys: int = 1000, er: EngResources = None, verbose: bool = False) -> List[dict]:
    """
    Find files in S3 matching given prefixes.

    Args:
        s3_loc (str): S3 location (e.g., s3://bucket/prefix/)
        prefixes (List[str]): List of file prefixes to match
        max_keys (int): Maximum number of keys to return per request

    Returns:
        List[dict]: List of matching files with name, size, and last_modified
    """
    try:
        bucket, prefix = parse_s3_url(s3_loc)
        if verbose:
            log.info(f"searching in s3 bucket '{bucket}' with prefix '{prefix}'")

        s3 = None
        if er is not None:
            s3 = er.get_s3_client_tasks()
        else:
            s3 = get_s3_client()
        paginator = s3.get_paginator("list_objects_v2")

        # Create regex pattern to match any of the prefixes
        escaped_prefixes = [re.escape(p) for p in prefixes]
        pattern = f'^({"|".join(escaped_prefixes)})'
        regex = re.compile(pattern)

        matching_files = []

        # Paginate through results
        page_iterator = paginator.paginate(
            Bucket=bucket, Prefix=prefix, PaginationConfig={"PageSize": max_keys}
        )

        for page in page_iterator:
            if "Contents" not in page:
                if verbose:
                    log.info("no files found in s3 location")
                continue

            for obj in page["Contents"]:
                key = obj["Key"]
                # Extract filename from full path
                filename = key.split("/")[-1]

                # Check if filename matches any prefix
                if regex.match(filename):
                    matching_files.append(
                        {
                            "name": filename,
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"],
                            "s3_loc": f's3://{bucket}/{key}',
                        }
                    )
                    if verbose:
                        log.info(f"found match: {filename}")

        if verbose:
            log.info(f"total matching files found: {len(matching_files)}")
        return matching_files

    except ClientError as e:
        log.error(f"aws client error: {traceback}")
        raise e
    except Exception as e:
        log.error(f"unexpected error: {traceback.format_exc()}")
        raise e

    log.error(f'no_matching_files_found: {len(matching_files)}')
    return matching_files


def main():
    """Main function for command-line interface."""
    parser = argparse.ArgumentParser(
        description="Find S3 files with specified prefixes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -s s3://my-bucket/path/ -p prefix --max-keys 500
  %(prog)s -s s3://tasks1/inv/sec/v9/lac/sec_lac_8k -p sec_lac_10k
        """,
    )

    parser.add_argument("-s", "--s3-loc", required=True, help="S3 location (e.g., s3://bucket/prefix/)")
    parser.add_argument("-p", "--prefixes", nargs="+", required=True, help="File prefixes to match (e.g., sec_lac_8k sec_lac_10k)")
    parser.add_argument("-m", "--max-keys", type=int, default=1000, help="Maximum number of keys to return per request (default: 1000)")
    args = parser.parse_args()

    try:
        files = find_files_in_s3(
            s3_loc=args.s3_loc, prefixes=args.prefixes, max_keys=args.max_keys
        )

        if files:
            log.info("Matching files:")
            for f in files:
                print(f"{f['s3_loc']} ({f['size']} bytes)")
        else:
            log.info("No matching files found")

    except Exception as e:
        log.error(f"Failed to find files: {e}")
        raise


if __name__ == "__main__":
    main()
