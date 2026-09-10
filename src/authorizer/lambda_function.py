import json
import logging
import os
import secrets

import boto3


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")
lambda_client = boto3.client("lambda")


CUSTOMER_TOKEN_PARAM = os.environ["CUSTOMER_TOKEN_PARAM"]
PRODUCT_OWNER_TOKEN_PARAM = os.environ["PRODUCT_OWNER_TOKEN_PARAM"]
ADMIN_TOKEN_PARAM = os.environ["ADMIN_TOKEN_PARAM"]

PRODUCT_FUNCTION_NAME = os.environ["PRODUCT_FUNCTION_NAME"]
ORDER_FUNCTION_NAME = os.environ["ORDER_FUNCTION_NAME"]

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
        "body": json.dumps(body, indent=4)
    }


def get_role(supplied_token):

    parameters = ssm.get_parameters(
        Names=[
            CUSTOMER_TOKEN_PARAM,
            PRODUCT_OWNER_TOKEN_PARAM,
            ADMIN_TOKEN_PARAM
        ],
        WithDecryption=True
    )

    token_roles = {}

    for parameter in parameters["Parameters"]:

        name = parameter["Name"]
        value = parameter["Value"]

        if name == CUSTOMER_TOKEN_PARAM:
            token_roles["CUSTOMER"] = value

        elif name == PRODUCT_OWNER_TOKEN_PARAM:
            token_roles["PRODUCT_OWNER"] = value

        elif name == ADMIN_TOKEN_PARAM:
            token_roles["ADMIN"] = value

    for role, expected_token in token_roles.items():

        if secrets.compare_digest(
            supplied_token,
            expected_token
        ):
            return role

    return None


def is_supported_path(path):

    return (
        path == "/products"
        or path.startswith("/products/")
        or path == "/orders"
        or path.startswith("/orders/")
        or path.startswith("/customers/")
    )

def is_product_path(path):

    return (
        path == "/products"
        or path.startswith("/products/")
    )

def is_allowed(role, method, path):

    if is_product_path(path):

        permissions = {
            "CUSTOMER": {
                "GET"
            },

            "PRODUCT_OWNER": {
                "GET",
                "POST",
                "PUT",
                "DELETE"
            },

            "ADMIN": {
                "GET",
                "POST",
                "PUT",
                "DELETE"
            }
        }

    else:

        permissions = {
            "CUSTOMER": {
                "GET",
                "POST",
                "PUT"
            },

            "PRODUCT_OWNER": set(),

            "ADMIN": {
                "GET",
                "PUT"
            }
        }

    return method in permissions.get(role, set())


def invoke_product_lambda(event, request_id):

    invoke_response = lambda_client.invoke(
        FunctionName=PRODUCT_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8")
    )

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
                    "message": "Product service unavailable."
                }
            }
        )

    payload = invoke_response["Payload"].read()

    return json.loads(
        payload.decode("utf-8")
    )


def invoke_order_lambda(event, request_id):

    invoke_response = lambda_client.invoke(
        FunctionName=ORDER_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode("utf-8")
    )

    if invoke_response.get("FunctionError"):

        logger.error(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "order_lambda_error",
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
                    "code": "ORDER_SERVICE_ERROR",
                    "message": "Order service unavailable."
                }
            }
        )

    payload = invoke_response["Payload"].read()

    return json.loads(
        payload.decode("utf-8")
    )


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

        supplied_token = (
            headers.get("X-CloudMart-Token")
            or headers.get("x-cloudmart-token")
        )

        if not supplied_token:

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "missing_token"
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Authentication is required."
                    }
                }
            )

        supplied_token = supplied_token.strip()

        if not supplied_token:

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "missing_token"
                    }
                )
            )

            return response(
                401,
                {
                    "authorized": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Invalid authentication credentials."
                    }
                }
            )
        

        # ========================================================
        # IDENTIFY ROLE
        # ========================================================

        role = get_role(supplied_token)

        if role is None:

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
                        "message": "Invalid authentication credentials."
                    }
                }
            )

        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "role_identified",
                    "role": role,
                    "method": method,
                    "path": path
                }
            )
        )

        # ========================================================
        # ROUTE CHECK
        # ========================================================

        if not is_supported_path(path):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "route_not_found",
                        "path": path
                    }
                )
            )

            return response(
                404,
                {
                    "authorized": True,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": "Requested route was not found."
                    }
                }
            )

        # ========================================================
        # ROLE + METHOD AUTHORIZATION
        # ========================================================

        if not is_allowed(role, method, path):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "authorization_failed",
                        "reason": "method_not_allowed",
                        "role": role,
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
                            "You do not have permission "
                            "to perform this operation."
                        )
                    }
                }
            )

        # ========================================================
        # INVOKE SERVICE LAMBDA
        # ========================================================

        if is_product_path(path):

            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "event": "invoking_product_lambda",
                        "role": role,
                        "method": method,
                        "path": path
                    }
                )
            )

            return invoke_product_lambda(event, request_id)

        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "invoking_order_lambda",
                    "role": role,
                    "method": method,
                    "path": path
                }
            )
        )

        return invoke_order_lambda(event, request_id)

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
                    "message": "Authorization service error."
                }
            }
        )