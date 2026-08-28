"""
Shared authentication helper for CloudMart Lambdas.

Function URLs do not provide the API Gateway Lambda Authorizer
construct used in the original architecture. Therefore authentication
is performed inside the Lambda before any business logic executes.

The authentication token is stored in SSM Parameter Store as a
SecureString and retrieved using the Lambda execution role.

A module-level cache is used so the token is not fetched from SSM
on every warm Lambda invocation.
"""

import os
import time
import boto3


_ssm = boto3.client("ssm")


_cache = {
    "token": None,
    "expires_at": 0
}


CACHE_TTL_SECONDS = 300


def _get_valid_token():

    now = time.time()

    if (
        _cache["token"]
        and now < _cache["expires_at"]
    ):
        return _cache["token"]

    param_name = os.environ["AUTH_TOKEN_PARAM"]

    response = _ssm.get_parameter(
        Name=param_name,
        WithDecryption=True
    )

    _cache["token"] = response["Parameter"]["Value"]

    _cache["expires_at"] = (
        now + CACHE_TTL_SECONDS
    )

    return _cache["token"]


def authorize(event) -> bool:
    """
    Validate the Bearer token supplied in the request.

    Returns True only when the supplied token matches the
    SecureString stored in SSM Parameter Store.
    """

    headers = event.get("headers") or {}

    auth_header = (
        headers.get("authorization")
        or headers.get("Authorization")
    )

    if (
        not auth_header
        or not auth_header.startswith("Bearer ")
    ):
        return False

    provided = (
        auth_header
        .split("Bearer ", 1)[1]
        .strip()
    )

    valid_token = _get_valid_token()

    return provided == valid_token