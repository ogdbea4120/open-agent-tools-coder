#!/usr/bin/env python3

"""
# usage

./list_files_in_s3_subdir2.py -s s3://tasks1/
"""

import boto3
import argparse
import traceback
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict, Optional, Tuple
from oats.log import cl

log = cl('s3.lf.2')


def parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    """
    Parse S3 URI into bucket name and prefix.

    Args:
        s3_uri (str): S3 URI in format s3://bucket/path

    Returns:
        Tuple[str, str]: (bucket, prefix)
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Sorry - invalid S3 URI format. Must start with s3:// found: {s3_uri}")

    # Remove s3:// prefix
    path = s3_uri[5:]

    # Split on first slash to get bucket and prefix
    parts = path.split("/", 1)
    if len(parts) == 1:
        bucket = parts[0]
        prefix = ""
    else:
        bucket, prefix = parts

    # log.info(f"s3_loc: s3://{bucket}/{prefix}")
    return bucket, prefix


def list_s3_files(
    s3_loc: str = None,
    bucket: str = None,
    prefix: str = None,
    aws_profile: Optional[str] = None,
    max_keys: int = 10000,
) -> List[Dict]:
    """
    List all files in an S3 bucket subdirectory.

    Args:
        s3_loc (str): Path to s3://BUCKET/PREFIX
        bucket (str): Name of the S3 bucket
        prefix (str): Path prefix to list files from
        aws_profile (str, optional): AWS profile name to use
        max_keys (int): Maximum number of keys to return per request

    Returns:
        List[Dict]: List of file information dictionaries
    """
    # Validate inputs
    if bucket is None and prefix is None and s3_loc is None:
        raise ValueError("s3_loc, Bucket name and prefix must be provided")

    if s3_loc is not None:
        if bucket is None and prefix is None:
            bucket, prefix = parse_s3_uri(s3_loc)
    else:
        s3_loc = f's3://{bucket}/{prefix}'

    log.info(f"listing s3://{bucket}/{prefix}")

    try:
        # Create session with optional profile
        if aws_profile:
            # log.info(f"Using AWS profile: {aws_profile}")
            session = boto3.Session(profile_name=aws_profile)
            s3_client = session.client("s3")
        else:
            # log.info("Using default AWS credentials")
            s3_client = boto3.client("s3")

        # Ensure prefix ends with '/' for directory listing
        if not prefix.endswith("/"):
            prefix += "/"

        files = []
        paginator = s3_client.get_paginator("list_objects_v2")

        # Use paginator to handle large numbers of files
        page_iterator = paginator.paginate(
            Bucket=bucket, Prefix=prefix, PaginationConfig={"PageSize": max_keys}
        )

        for page in page_iterator:
            if "Contents" in page:
                for obj in page["Contents"]:
                    files.append(
                        {
                            "Key": obj["Key"],
                            "Size": obj["Size"],
                            "LastModified": obj["LastModified"],
                            "ETag": obj["ETag"],
                        }
                    )

        log.info(f"Found {len(files)} files in s3://{bucket}/{prefix}")
        return files
    except NoCredentialsError:
        error_msg = "AWS credentials not found. Please configure your AWS credentials."
        log.error(error_msg)
        raise Exception(error_msg)
    except ClientError as e:
        error_code = e.response["Error"]["Code"].lower()
        if 'no such bucket' in error_code:
            error_msg = f"Bucket '{bucket}' does not exist"
            log.error(error_msg)
            raise Exception(error_msg)
        elif 'access denied' in error_code:
            error_msg = f"Access denied to bucket '{bucket}'"
            log.error(error_msg)
            raise Exception(error_msg)
        else:
            error_msg = f"AWS Error: {str(e)}"
            log.error(error_msg)
            raise Exception(error_msg)


def list_s3_files_simple(bucket: str, prefix: str) -> List[str]:
    """
    Simple version that returns just file paths.

    Args:
        bucket (str): Name of the S3 bucket
        prefix (str): Path prefix to list files from

    Returns:
        List[str]: List of file paths
    """
    log.info(f"Getting simple file list for s3://{bucket}/{prefix}")
    files = list_s3_files(bucket=bucket, prefix=prefix)
    return [f["Key"] for f in files]


def main_helper(s3_uri: str, aws_profile: Optional[str] = None) -> List[Dict]:
    """
    Main helper function that processes S3 URI and returns file records.

    Args:
        s3_uri (str): S3 URI in format s3://bucket/path
        aws_profile (str, optional): AWS profile name to use

    Returns:
        List[Dict]: List of file information dictionaries
    """
    try:
        bucket, prefix = parse_s3_uri(s3_uri)
        files = list_s3_files(bucket=bucket, prefix=prefix, aws_profile=aws_profile)
        return files
    except Exception as e:
        log.error(f"Error processing S3 URI {s3_uri}: {e}")
        raise e


def setup_argparse():
    """Setup command line argument parser."""
    parser = argparse.ArgumentParser(
        description="List files in an S3 bucket subdirectory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -s s3://my-bucket/path/to/files/ --profile my-profile
        """,
    )

    parser.add_argument(
        "-s",
        "--s3-uri",
        required=True,
        help="S3 URI to list files from (e.g., s3://bucket/path/subdir/)",
    )

    parser.add_argument(
        "-p", "--profile", help="AWS profile name to use for authentication"
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    return parser


def example_usage():
    """Example of how to use the module"""
    prefix = "tests-202311/data/files"

    try:
        # Get detailed file information using main helper
        files = main_helper(f"s3://{prefix}")
        print(f"Found {len(files)} files in s3://{prefix}")
        print("-" * 80)
        for file_info in files:
            print(f"Key: {file_info['Key']}")
            print(f"Size: {file_info['Size']} bytes")
            print(f"Modified: {file_info['LastModified']}")
            print("-" * 40)
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Parse arguments
    parser = setup_argparse()
    args = parser.parse_args()

    try:
        # Process the S3 URI and get files
        files = main_helper(args.s3_uri, args.profile)

        # Print results
        print(f"Found {len(files)} files:")
        for file_info in files:
            print(f"  {file_info['Key']} ({file_info['Size']} bytes)")

    except Exception:
        log.error(f"\nFailed to list S3 files:\n{traceback.format_exc()}")
        exit(1)
