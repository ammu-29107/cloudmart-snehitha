import json
import os
import urllib.error
import urllib.request


AUTHORIZER_URL = os.environ["AUTHORIZER_URL"]


def authorize(event):
    """
    Send the incoming Authorization header to the dedicated
    Authorizer Lambda Function URL.

    The Product Lambda does NOT read the authentication token
    directly from SSM.

    The Authorizer Lambda owns token validation.
    """

    headers = event.get("headers") or {}

    authorization = (
        headers.get("Authorization")
        or headers.get("authorization")
    )

    # No Authorization header
    if not authorization:
        return False

    # Call the dedicated Authorizer Lambda Function URL
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

            if response.status != 200:
                return False

            body = response.read().decode("utf-8")

            try:
                result = json.loads(body)
            except json.JSONDecodeError:
                return False

            return result.get("authorized") is True

    except urllib.error.HTTPError:
        return False

    except urllib.error.URLError:
        return False

    except TimeoutError:
        return False

    except Exception:
        return False