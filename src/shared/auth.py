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

    Returns authorization status and a message so the calling Lambda
    can provide a clear response to the client.
    """

    headers = event.get("headers") or {}

    cloudmart_token = (
        headers.get("X-CloudMart-Token")
        or headers.get("x-cloudmart-token")
    )

    # Missing Authorization header
    if not cloudmart_token:
        return {
            "authorized": False,
            "code": "MISSING_AUTHORIZATION",
            "message": "Authorization header is required."
        }

    # Expected format:
    # Authorization: Bearer <token>
    if not cloudmart_token.startswith("Bearer "):
        return {
            "authorized": False,
            "code": "INVALID_AUTHORIZATION_FORMAT",
            "message": (
                "Authorization header must use the "
                "Bearer token format."
            )
        }

    provided_token = cloudmart_token.split(
        "Bearer ",
        1
    )[1].strip()

    if not provided_token:
        return {
            "authorized": False,
            "code": "INVALID_TOKEN",
            "message": "Authorization token cannot be empty."
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
                "message": "The provided authorization token is invalid."
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