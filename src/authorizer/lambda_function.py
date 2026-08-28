import json
import logging
import os
import secrets

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")


AUTH_TOKEN_PARAM = os.environ["AUTH_TOKEN_PARAM"]
ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)


def response(status_code, body):

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }


def lambda_handler(event, context):

    request_id = context.aws_request_id

    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "event": "authorizer_request_received",
                "environment": ENVIRONMENT
            }
        )
    )

    try:

        headers = event.get("headers") or {}

        authorization = (
            headers.get("Authorization")
            or headers.get("authorization")
        )

        # --------------------------------------------------------
        # Missing Authorization header
        # --------------------------------------------------------

        if not authorization:

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "missing_authorization_header"
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": (
                            "Authentication is required."
                        ),
                        "requestId": request_id
                    }
                }
            )

        # --------------------------------------------------------
        # Invalid authentication scheme
        # --------------------------------------------------------

        if not authorization.startswith(
            "Bearer "
        ):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": (
                            "invalid_authorization_scheme"
                        )
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": (
                            "Invalid authentication credentials."
                        ),
                        "requestId": request_id
                    }
                }
            )

        # --------------------------------------------------------
        # Extract token
        # --------------------------------------------------------

        supplied_token = (
            authorization[7:].strip()
        )

        if not supplied_token:

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": (
                            "Invalid authentication credentials."
                        ),
                        "requestId": request_id
                    }
                }
            )

        # --------------------------------------------------------
        # Read expected token from SSM SecureString
        # --------------------------------------------------------

        parameter = ssm.get_parameter(
            Name=AUTH_TOKEN_PARAM,
            WithDecryption=True
        )

        expected_token = (
            parameter["Parameter"]["Value"]
        )

        # --------------------------------------------------------
        # Constant-time token comparison
        # --------------------------------------------------------

        if not secrets.compare_digest(
            supplied_token,
            expected_token
        ):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "invalid_token"
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": (
                            "Invalid authentication credentials."
                        ),
                        "requestId": request_id
                    }
                }
            )

        # --------------------------------------------------------
        # Authorized
        # --------------------------------------------------------

        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "authorization_success"
                }
            )
        )

        return response(
            200,
            {
                "authorized": True,
                "requestId": request_id
            }
        )

    except Exception as exc:

        logger.error(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "authorizer_error",
                    "error_type": type(exc).__name__,
                    "message": str(exc)
                }
            )
        )

        return response(
            500,
            {
                "authorized": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": (
                        "Authorization service error."
                    ),
                    "requestId": request_id
                }
            }
        )