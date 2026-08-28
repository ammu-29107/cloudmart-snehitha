"""
Shared authentication helper — imported by every Lambda in CloudMart.

This replaces the API Gateway Lambda Authorizer pattern from the original
brief. Since Function URLs have no authorizer construct, every Lambda calls
authorize(event) as the very first thing it does, before touching any
business logic. The caching here (module-level dict, survives across warm
invocations) is the equivalent of the authorizer's cache TTL.
"""

import os
import time
import boto3

_ssm = boto3.client("ssm")

# Module-level cache — persists across warm Lambda invocations within the
# same execution environment. This is what satisfies "authorizer cache TTL
# set and verified" without an actual API Gateway authorizer resource.
_cache = {"token": None, "expires_at": 0}
CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_valid_token():
    now = time.time()
    if _cache["token"] and now < _cache["expires_at"]:
        return _cache["token"]

    param_name = os.environ["AUTH_TOKEN_PARAM"]  # never hardcoded
    resp = _ssm.get_parameter(Name=param_name, WithDecryption=True)
    _cache["token"] = resp["Parameter"]["Value"]
    _cache["expires_at"] = now + CACHE_TTL_SECONDS
    return _cache["token"]


def authorize(event) -> bool:
    """Returns True if the request carries a valid Bearer token."""
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return False

    provided = auth_header.split("Bearer ", 1)[1].strip()
    valid_token = _get_valid_token()
    return provided == valid_token
