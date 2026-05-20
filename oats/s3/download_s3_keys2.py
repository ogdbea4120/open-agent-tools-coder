import os
import boto3
from typing import Dict, Any
from io import BytesIO
from oats.log import cl

log = cl('dl.s3.keys.2')


def download_s3_keys(s3_locs: list[str], dl_dir: str, verbose: bool = False, s3_client=None):
    """Download files from S3 given their S3 locations and save them to a specified directory.

    Args:
        s3_locs (list[str]): A list of strings in the format 's3://bucket/key'.
        dl_dir (str): Local directory to download the files.
        verbose (bool): if True, enable tracing logging
        s3_client: Boto3 S3 client. If None, a new client will be created.

    Returns:
        tuple: (list of local file paths, boto3 S3 client)
    """
    if s3_client is None:
        s3_client = boto3.client('s3')

    downloaded_files: Dict[str, Any] = {}

    for s3_loc in s3_locs:
        s3_split = []
        if 's3://' in s3_loc:
            s3_split = s3_loc.split('s3://')[1].split('/')
        elif 'https://' in s3_loc and '?' in s3_loc:
            s3_split = s3_loc.split('?')[0].split('https://')[1].split('/')
        else:
            if 's3://' not in s3_loc:
                log.warning(f'unexpected download path: {s3_loc} - skipping_s3_download')
                s3_split = []
            else:
                s3_split = s3_loc.split('s3://')[1].split('/')
        if len(s3_split) == 0:
            log.info('no files to download')
            return downloaded_files, s3_client
        if s3_split[0] == '':
            s3_split = s3_split[1:]
        bucket = s3_split[0]
        key = '/'.join(s3_split[1:])
        rel_path_to_file = key
        if rel_path_to_file.startswith('/'):
            rel_path_to_file = key[1:]
        local_file_path = os.path.join(dl_dir, os.path.basename(rel_path_to_file))
        local_ext = local_file_path.split('.')[-1]
        # log.info(f'\n\ndl\nbucket: ~{bucket}~\ns3_loc: {s3_loc}\nkey: ~{key}~\nlocal_file: {local_file_path}\next: {local_ext}')
        try:
            if not os.path.exists(dl_dir):
                os.makedirs(dl_dir, exist_ok=True)  # Create directory if it doesn't exist
            if not os.path.exists(dl_dir):
                log.error(f'failed to create download directory: {dl_dir} - please confirm user permissions')
                os.system('id -a')
            else:
                response = s3_client.get_object(Bucket=bucket, Key=key)
                # Read the content of the file into memory
                file_content_bytes = BytesIO(response['Body'].read()).read()
                file_content = file_content_bytes.decode('utf-8')
                if local_ext in ['txt', 'text', 'md', 'py', 'rs', 'toml', 'config', 'conf', 'ini', 'json', 'yaml']:
                    file_content = file_content_bytes.decode('utf-8')
                    if verbose:
                        log.info(f'dl\n\ns3://{bucket}/{key}\n\ntxt file: {local_file_path} rel_path: {rel_path_to_file}')
                    with open(local_file_path, 'w') as fp:
                        fp.write(file_content)
                else:
                    if verbose:
                        log.info(f'dl\n\ns3://{bucket}/{key}\n\nbin file: {local_file_path}')
                    with open(local_file_path, 'wb') as fp:
                        fp.write(file_content)
                # s3_client.download_file(bucket, key, local_file_path)
                downloaded_files[local_file_path] = s3_loc
                if verbose:
                    log.info(f"downloaded {s3_loc} to {local_file_path}")
        except Exception as e:
            log.error(f"failed to download {s3_loc} to local_file_path: {local_file_path} with error: {e}")
    # end for all files

    if verbose:
        log.info(f'downloaded {len(downloaded_files)} from oats s3 files: {len(s3_locs)}')

    return downloaded_files, s3_client
