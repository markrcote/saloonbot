import boto3
import requests
from botocore.exceptions import ClientError


def is_ec2_instance():
    try:
        token_response = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            timeout=1,
        )
        if token_response.status_code != 200:
            return False
        token = token_response.text
        metadata_response = requests.get(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=1,
        )
        return metadata_response.status_code == 200
    except requests.RequestException:
        return False


def get_secret(dev_discord_server):
    if dev_discord_server:
        secret_name = "saloonbot/discord-dev"
    else:
        secret_name = "saloonbot/discord"
    region_name = "ca-central-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    return get_secret_value_response['SecretString']
