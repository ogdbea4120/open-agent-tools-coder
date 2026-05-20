import boto3
from oats.log import cl

log = cl('s3.gc')

def get_s3_client():
    try:
        return boto3.client('s3')
    except Exception as e:
        log.error(f'failed to get s3 client with error: {e}')
        raise e
