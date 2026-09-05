import os
import boto3


ssm = boto3.client("ssm")


AUTH_TOKEN_PARAM = os.environ.get(
    "AUTH_TOKEN_PARAM",
    "/cloudmart/dev/auth/token"
)


def authorize(event):
    """
    Validate the CloudMart application token directly against
    SSM Parameter Store.

    AWS IAM/SigV4 authentication is handled separately by the
    Lambda Function URL. The CloudMart application token is passed
    through the X-CloudMart-Token header.
    """

    headers = event.get("headers") or {}

    cloudmart_token = (
        headers.get("X-CloudMart-Token")
        or headers.get("x-cloudmart-token")
    )

    # Missing application token
    if not cloudmart_token:
        return {
            "authorized": False,
            "code": "MISSING_AUTHORIZATION",
            "message": "X-CloudMart-Token header is required."
        }

    provided_token = cloudmart_token.strip()

    if not provided_token:
        return {
            "authorized": False,
            "code": "INVALID_TOKEN",
            "message": "Authentication token cannot be empty."
        }

    try:
        response = ssm.get_parameter(
            Name=AUTH_TOKEN_PARAM,
            WithDecryption=True
        )

        expected_token = response[
            "Parameter"
        ]["Value"]

        if provided_token != expected_token:
            return {
                "authorized": False,
                "code": "INVALID_TOKEN",
                "message": "The provided authentication token is invalid."
            }

        return {
            "authorized": True,
            "code": "AUTHORIZED",
            "message": "Authorization successful."
        }

    except Exception:
        return {
            "authorized": False,
            "code": "AUTHORIZATION_ERROR",
            "message": "Unable to validate authorization."
        }