#!/usr/bin/env python3

"""
# Upload a string, binary data or a file to s3

```
./upload_file.py -c 'hello' -o s3://dev/test1
./upload_file.py -f FILE -o s3://dev/test2
```
"""

import os
import sys
import argparse
import traceback
from typing import Optional, Union, Tuple
from oats.date import utc
from oats.s3.get_client import get_s3_client
from oats.log import cl

log = cl('s3.uf')

def helper_upload_file(
    local_path: str,
    bk: str | None = None,
    loc: str | None = None,
    s3_loc: str | None = None,
    encryption_type: str = 'AES256',
    storage_class: str | None = None,
    local_s3: bool = False,
    verbose: bool = False,
    s3_client=None,
) -> Tuple[bool, str | None]:
    """
    upload local file to s3 with AES256 encryption by default

    :param local_path: [TODO:description]
    :param bk: optional bucket path
    :param s3_loc: s3://bk/prefix/key - use this
    :param encryption_type: [TODO:description]
    :return: [TODO:description]
    """
    if s3_loc is None:
        if loc is not None:
            s3_loc = loc
    if bk is None:
        bk = os.getenv('TEMP_UPLOAD_BUCKET', 'ds-acf')
    new_key = None
    try:
        if s3_client is None:
            # Create an S3 client
            s3_client = get_s3_client()
        # 'STANDARD_IA', 'REDUCED_REDUNDANCY', 'ONEZONE_IA'
        storage_class = None
        if os.getenv('AWS_ENDPOINT_URL', '') == '':
            # default for aws cost savings
            if storage_class is None:
                storage_class = os.getenv('STORAGE_CLASS', 'STANDARD_IA')
            if encryption_type is None:
                encryption_type = os.getenv('STORAGE_ENC', encryption_type)
        else:
            local_s3 = True
        if s3_loc is None:
            # Get current date and create a date prefix
            date_prefix = utc().strftime("%Y%m%d%H%M%S")
            # Extract filename from local_path
            filename = local_path.split('/')[-1]
            # Construct the new key with the date prefix and filename
            new_key = f"dev/uploads/files/{date_prefix}_{filename}"
            s3_loc = f's3://{new_key}'
        else:
            scrub = s3_loc.replace('s3://', '').split('/')
            bk = scrub[0]
            new_key = '/'.join(scrub[1:])

        if verbose:
            log.info(f"uploading file {local_path} to s3://{bk}/{new_key} sc: {storage_class}")
        # Open the local file in binary mode and upload it to S3
        if local_path.endswith('.txt') or local_path.endswith('.py') or local_path.endswith('.md'):
            with open(local_path, 'rb') as file_data:
                if local_s3:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=file_data,
                    )
                else:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=file_data,
                        ServerSideEncryption=encryption_type,
                        StorageClass=storage_class,
                    )
        else:
            with open(local_path, 'rb') as file_data:
                if local_s3:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=file_data,
                    )
                else:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=file_data,
                        ServerSideEncryption=encryption_type,
                        StorageClass=storage_class,
                    )
        if verbose:
            log.info(f"file uploaded successfully to s3://{bk}/{new_key}")
        return True, f's3://{bk}/{new_key}'
    except Exception:
        log.error(f"### Sorry!! Failed uploading file:\n```\n{local_path}\n```\narg_s3_loc:\n```\n{s3_loc}\n```\nuse_s3_loc:\n```\ns3://{bk}/{new_key}\n```\ns3_client: {s3_client} with error:\n```\n{traceback.format_exc()}\n```\n")
        return False, None
    log.error(f"### Sorry!! Failed helper_s3_uploader_found_nothing to upload for file: {local_path} to s3: {s3_loc}")
    return False, None


def upload_file(
    local_path: Optional[str] = None,
    file: Optional[str] = None,
    bk: str | None = None,
    loc: str | None = None,
    s3_loc: str | None = None,
    encryption_type: str = 'AES256',
    storage_class: str | None = None,
    verbose: bool = False,
    s3_client=None,
    local_s3: bool = False,
    ct: Optional[Union[str, bytes]] = None,
) -> Tuple[bool, str | None]:
    """
    Upload local file to s3 with AES256 encryption by default
    :param local_path: Local file path to upload
    :param file: Local file path to upload
    :param bk: optional bucket path
    :param loc: legacy location parameter
    :param s3_loc: s3://bk/pprefix/key - use this
    :param encryption_type: Encryption type (default: AES256)
    :param storage_class: Storage class for the object
    :param verbose: Enable verbose logging
    :param ct: Content (str or bytes) to upload directly without a local file
    :return: Tuple of (success: bool, s3_url: str)
    """
    if local_path is None and file is not None:
        local_path = file
    if file is None and local_path is not None:
        file = local_path
    if s3_loc is None:
        if loc is not None:
            s3_loc = loc
    if bk is None:
        bk = os.getenv('TEMP_UPLOAD_BUCKET', 'ds-acf')

    new_key = None
    if s3_loc is None:
        # Get current date and create a date prefix
        date_prefix = utc().strftime("%Y%m%d%H%M%S")
        # Generate a default filename based on timestamp
        filename = f"content_{date_prefix}.txt"
        # Construct the new key with the date prefix and filename
        new_key = f"dev/uploads/rand/{date_prefix}_{filename}"
    else:
        scrub = s3_loc.replace('s3://', '').split('/')
        bk = scrub[0]
        new_key = '/'.join(scrub[1:])
    try:
        if ct is None and local_path is not None:
            return helper_upload_file(
                local_path=local_path,
                bk=bk,
                loc=loc,
                s3_loc=s3_loc,
                encryption_type=encryption_type,
                storage_class=storage_class,
                s3_client=s3_client,
                local_s3=local_s3,
                verbose=verbose,
            )
        if s3_client is None:
            # Create an S3 client
            s3_client = get_s3_client()

        if os.getenv('AWS_ENDPOINT_URL', '0') == '0':
            # default for aws cost savings
            if storage_class is None:
                storage_class = os.getenv('STORAGE_CLASS', 'STANDARD_IA')
            if encryption_type is None:
                encryption_type = os.getenv('STORAGE_ENC', encryption_type)
        else:
            local_s3 = True

        # Handle content upload directly from string
        if ct is not None:
            # When content is provided directly, we don't need local_path

            if verbose:
                log.info(f"Uploading content directly to s3://{bk}/{new_key} sc: {storage_class}")

            # Upload the content directly
            if local_s3:
                s3_client.put_object(
                    Bucket=bk,
                    Key=new_key,
                    Body=ct if isinstance(ct, bytes) else ct.encode('utf-8')
                )
                if verbose:
                    log.info(f"file uploaded successfully_no_enc to s3://{bk}/{new_key}")
            else:
                if storage_class is None:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=ct if isinstance(ct, bytes) else ct.encode('utf-8'),
                        ServerSideEncryption=encryption_type,
                    )
                else:
                    s3_client.put_object(
                        Bucket=bk,
                        Key=new_key,
                        Body=ct if isinstance(ct, bytes) else ct.encode('utf-8'),
                        ServerSideEncryption=encryption_type,
                        StorageClass=storage_class
                    )
                if verbose:
                    log.info(f"file uploaded successfully to s3://{bk}/{new_key}")
        return True, f's3://{bk}/{new_key}'
    except Exception:
        log.error(f"### Sorry!! Failed uploading file: {local_path} to s3: {s3_loc} with s3_client: {s3_client} with error:\n```\n{traceback.format_exc()}\n```\n")
        return False, None
    log.error(f"### Sorry!! Failed nothing uploaded for file: {local_path} to s3: {s3_loc}")
    return False, None


def helper_get_args():
    p = argparse.ArgumentParser(description='Upload a file or content to S3')
    p.add_argument('-f', '--file_path', dest='file_path', default=None, help='Local file path to upload')
    p.add_argument('-c', '--content', dest='content', default=None, help='Content string to upload directly')
    p.add_argument('-o', '--s3-loc', dest='s3_loc', default=None, help='S3 destination (s3://bucket/key)')
    return p.parse_args()


def main():
    args = helper_get_args()
    if args.file_path is None and args.content is None:
        log.error("### Sorry!! Usage error: -f FILE or -c 'CONTENT' -o s3://BUCKET/PREFIX/KEY")
        sys.exit(1)
    else:
        if args.file_path is not None:
            ok, s3_url = upload_file(local_path=args.file_path, s3_loc=args.s3_loc, verbose=True)
        else:
            ok, s3_url = upload_file(ct=args.content, s3_loc=args.s3_loc, verbose=True)
        if ok:
            print(s3_url)
    sys.exit(0)


if __name__ == '__main__':
    main()
