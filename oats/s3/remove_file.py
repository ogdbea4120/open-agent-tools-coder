#!/usr/bin/env python3

import os
import traceback
from oats.s3.get_client import get_s3_client
from oats.log import cl

log = cl('s3.rmk')


def remove_file(
    bk: str | None = None,
    key: str | None = None,
    loc: str | None = None,
    s3_client=None,
    verbose: bool = False,
):
    """
    Removes a key in s3 (useful for replaying manifests from scratch)

    :param bk: The name of the S3 bucket.
    :param key: The path to the object in the S3 bucket.
    :param loc: s3://bucket/key location path
    :param s3_client: optional - boto3 client
    :return: tuple(
            [None | A BytesIO object containing the contents of the downloaded file],
            s3_client
        )
    """

    if s3_client is None:
        # Create an S3 client
        s3_client = get_s3_client()
    try:
        if bk is None and key is None:
            if loc is not None:
                scrub_loc = loc.replace('s3://', '')
                bk = scrub_loc.split('/')[0]
                key = '/'.join(scrub_loc.split('/')[1:])
        # Get the object from S3
        if verbose:
            log.info(f's3_rm: s3://{bk}/{key}')
        s3_client.delete_object(
            Bucket=bk,
            Key=key
        )
        return True, s3_client
    except Exception as e:
        if os.getenv('DEBUG_TASK', '0') == '1':
            log.error(f"failed downloading file from s3: s3://{bk}/{key} client: {s3_client} with error: {traceback.format_exc()}")
            raise e
        else:
            log.info(f"failed downloading file from s3: s3://{bk}/{key}")
    return False, s3_client


if __name__ == '__main__':
    ct, s3 = remove_file(bk='tasks1', key='tasks/test.md')
    print(ct)
