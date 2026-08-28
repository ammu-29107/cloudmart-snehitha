"""
Shared authentication helper for CloudMart Product Lambda.

The Product Lambda does NOT validate the token directly.

Instead:

Client
   |
   | Authorization: Bearer <token>
   v
Product Lambda
   |
   | HTTP request to AUTHORIZER_URL
   | Authorization: Bearer <token>
   v
Authorizer Lambda
   |
   | reads token from SSM SecureString
   v
SSM Parameter Store

The Authorizer Lambda returns:
    200 + {"authorized": true}
for a valid token.

The Product Lambda returns:
    401
for missing/invalid authentication.
"""

import json
import os
import urllib.error
import urllib.request


AUTHORIZER_URL = os.environ["AUTHORIZER_URL"]


def authorize_request(event):
    """
    Send the incoming Authorization header to the
    dedicated Authorizer Lambda Function URL.

    Returns:
        (True, 200)   -> authorization successful
        (False, 401)  -> missing/invalid credentials
        (False, 500)  -> authorizer/service failure
    """

    headers = event.get("headers") or {}

    authorization = (
        headers.get("Authorization")
        or headers.get("authorization")
    )

    # ---------------------------------------------------------
    # No Authorization header
    # ---------------------------------------------------------

    if not authorization:
        return False, 401

    # ---------------------------------------------------------
    # Call the Authorizer Lambda Function URL
    # ---------------------------------------------------------

    request = urllib.request.Request(
        AUTHORIZER_URL,
        method="GET",
        headers={
            "Authorization": authorization
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:

            status_code = response.status

            # -------------------------------------------------
            # Authorizer accepted the token
            # -------------------------------------------------

            if status_code == 200:

                body = response.read().decode("utf-8")

                try:
                    result = json.loads(body)

                except json.JSONDecodeError:
                    return False, 401

                if result.get("authorized") is True:
                    return True, 200

                return False, 401

            # -------------------------------------------------
            # Authorizer rejected the token
            # -------------------------------------------------

            if status_code == 401:
                return False, 401

            # -------------------------------------------------
            # Unexpected authorizer response
            # -------------------------------------------------

            return False, 500

    except urllib.error.HTTPError as error:

        if error.code == 401:
            return False, 401

        return False, 500

    except Exception:
        return False, 500


def authorize(event):
    """
    Compatibility wrapper used by product/handler.py.

    The actual authorization is performed by the
    dedicated Authorizer Lambda Function URL.
    """

    authorized, _status = authorize_request(event)

    return authorized