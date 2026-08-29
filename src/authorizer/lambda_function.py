import json
import logging
import os
import secrets

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")
lambda_client = boto3.client("lambda")


AUTH_TOKEN_PARAM = os.environ["AUTH_TOKEN_PARAM"]
PRODUCT_FUNCTION_NAME = os.environ["PRODUCT_FUNCTION_NAME"]

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

    request_context = event.get("requestContext") or {}
    http_context = request_context.get("http") or {}

    method = (
        http_context.get("method")
        or event.get("httpMethod")
        or ""
    ).upper()

    path = (
        event.get("rawPath")
        or event.get("path")
        or ""
    )

    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "event": "authorizer_request_received",
                "environment": ENVIRONMENT,
                "method": method,
                "path": path
            }
        )
    )

    try:

        # ========================================================
        # AUTHENTICATION
        # ========================================================

        headers = event.get("headers") or {}

        authorization = (
            headers.get("Authorization")
            or headers.get("authorization")
        )

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
                        "message": "Authentication is required.",
                        "requestId": request_id
                    }
                }
            )

        if not authorization.startswith("Bearer "):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "invalid_authorization_scheme"
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid authentication credentials.",
                        "requestId": request_id
                    }
                }
            )

        supplied_token = authorization[7:].strip()

        if not supplied_token:

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid authentication credentials.",
                        "requestId": request_id
                    }
                }
            )

        # ========================================================
        # TOKEN VALIDATION
        # ========================================================

        parameter = ssm.get_parameter(
            Name=AUTH_TOKEN_PARAM,
            WithDecryption=True
        )

        expected_token = parameter["Parameter"]["Value"]

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
                        "message": "Invalid authentication credentials.",
                        "requestId": request_id
                    }
                }
            )

        # ========================================================
        # METHOD AUTHORIZATION
        #
        # External clients are currently allowed to READ products
        # only.
        # ========================================================

        if method != "GET":

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "method_not_allowed",
                        "method": method,
                        "path": path
                    }
                )
            )

            return response(
                403,
                {
                    "authorized": False,
                    "error": {
                        "code": "FORBIDDEN",
                        "message": (
                            "Only GET requests are permitted "
                            "through the public product endpoint."
                        ),
                        "requestId": request_id
                    }
                }
            )

        # ========================================================
        # INVOKE PRODUCT LAMBDA
        # ========================================================

        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "invoking_product_lambda",
                    "method": method,
                    "path": path
                }
            )
        )

        invoke_response = lambda_client.invoke(
            FunctionName=PRODUCT_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(event).encode("utf-8")
        )

        # ========================================================
        # PRODUCT LAMBDA ERROR
        # ========================================================

        if invoke_response.get("FunctionError"):

            logger.error(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "product_lambda_error",
                        "function_error": invoke_response[
                            "FunctionError"
                        ]
                    }
                )
            )

            return response(
                502,
                {
                    "authorized": True,
                    "error": {
                        "code": "PRODUCT_SERVICE_ERROR",
                        "message": "Product service unavailable.",
                        "requestId": request_id
                    }
                }
            )

        # ========================================================
        # RETURN PRODUCT RESPONSE
        # ========================================================

        payload = invoke_response["Payload"].read()

        product_response = json.loads(
            payload.decode("utf-8")
        )

        return product_response

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
                    "message": "Authorization service error.",
                    "requestId": request_id
                }
            }
        )