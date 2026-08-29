import os
import boto3


ssm = boto3.client("ssm")


AUTH_TOKEN_PARAM = os.environ.get(
    "AUTH_TOKEN_PARAM",
    "/cloudmart/dev/auth/token"
)


def authorize(event):
    """
    Validate the Bearer token directly against SSM Parameter Store.

    This is used internally by private Lambdas so they do not need
    internet access to call the Authorizer Lambda Function URL.
    """

    headers = event.get("headers") or {}

    authorization = (
        headers.get("Authorization")
        or headers.get("authorization")
    )

    # Missing Authorization header
    if not authorization:
        return False

    # Expected format:
    # Authorization: Bearer <token>
    if not authorization.startswith("Bearer "):
        return False

    provided_token = authorization.split(
        "Bearer ",
        1
    )[1].strip()

    if not provided_token:
        return False

    try:

        response = ssm.get_parameter(
            Name=AUTH_TOKEN_PARAM,
            WithDecryption=True
        )

        expected_token = response[
            "Parameter"
        ]["Value"]

        return provided_token == expected_token

    except Exception:
        return False