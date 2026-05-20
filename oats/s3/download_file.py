import os
import traceback
from io import BytesIO
from oats.s3.get_client import get_s3_client
from oats.log import create_log

log = create_log('dl.f')


def download_file(
    bk: str | None = None,
    key: str | None = None,
    loc: str | None = None,
    s3_client=None,
    verbose: bool = False,
    silent: bool = False,
):
    """
    Downloads a file from an S3 bucket directly into memory.

    :param bk: The name of the S3 bucket.
    :param key: The path to the object in the S3 bucket.
    :param loc: s3://bucket/key location path
    :param s3_client: optional - boto3 client
    :return: tuple(
            [None | A BytesIO object containing the contents of the downloaded file],
            s3_client
        )
    """
    file_content = None
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
            log.info(f's3_dl: s3://{bk}/{key}')
        response = s3_client.get_object(Bucket=bk, Key=key)
        # Read the content of the file into memory
        file_content_bytes = BytesIO(response['Body'].read()).read()
        if file_content_bytes is not None:
            file_content = file_content_bytes.decode('utf-8')
        return file_content, s3_client
    except Exception:
        if os.getenv('DEBUG_TASK', '0') == '1':
            log.error(f"failed downloading file from s3: s3://{bk}/{key} client: {s3_client} with error: {traceback.format_exc()}")
        else:
            log.info(f"failed downloading file s3://{bk}/{key}")
    return None, s3_client


if __name__ == '__main__':
    ct, s3 = download_file(bk='tasks1', key='tests/file1/file1')
    print(ct)
