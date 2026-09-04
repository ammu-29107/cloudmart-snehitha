import json
import logging
import os
import uuid
import datetime

import boto3
import pymysql

from shared.auth import authorize


logger = logging.getLogger()
logger.setLevel(logging.INFO)


eventbridge = boto3.client("events")
sns = boto3.client("sns")
ssm = boto3.client("ssm")


def log_json(**kwargs):
    """Structured JSON logging."""
    logger.info(json.dumps(kwargs))


def get_ssm_parameter(name, decrypt=False):
    response = ssm.get_parameter(
        Name=name,
        WithDecryption=decrypt
    )

    return response["Parameter"]["Value"]


def get_db_connection():

    host = get_ssm_parameter(
        os.environ["DB_HOST_PARAM"]
    )

    database = get_ssm_parameter(
        os.environ["DB_NAME_PARAM"]
    )

    username = get_ssm_parameter(
        os.environ["DB_USER_PARAM"]
    )

    password = get_ssm_parameter(
        os.environ["DB_PASSWORD_PARAM"],
        decrypt=True
    )

    return pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def respond(status, body, request_id):

    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(
            {
                **body,
                "request_id": request_id
            },
            default=str
        )
    }


def validate_product_data(body, required_fields=True):
    """Validate product request data."""

    required = [
        "product_name",
        "category",
        "price",
        "stock_quantity"
    ]

    if required_fields:
        missing = [
            field
            for field in required
            if field not in body
        ]

        if missing:
            return (
                f"Missing required field(s): "
                f"{', '.join(missing)}"
            )

    # ------------------------------------------------------------
    # PRODUCT NAME
    # ------------------------------------------------------------

    if "product_name" in body:

        product_name = body["product_name"]

        if not isinstance(product_name, str):
            return "Product name must be a string."

        if not product_name.strip():
            return "Product name cannot be empty."

    # ------------------------------------------------------------
    # CATEGORY
    # ------------------------------------------------------------

    if "category" in body:

        category = body["category"]

        if not isinstance(category, str):
            return "Category must be a string."

        if not category.strip():
            return "Category cannot be empty."

    # ------------------------------------------------------------
    # PRICE
    # ------------------------------------------------------------

    if "price" in body:

        price = body["price"]

        if isinstance(price, bool) or not isinstance(
            price,
            (int, float)
        ):
            return "Price must be a valid number."

        if price < 0:
            return "Price cannot be negative."

    # ------------------------------------------------------------
    # STOCK
    # ------------------------------------------------------------

    if "stock_quantity" in body:

        stock = body["stock_quantity"]

        if isinstance(stock, bool) or not isinstance(
            stock,
            int
        ):
            return "Stock quantity must be a whole number."

        if stock < 0:
            return "Stock quantity cannot be negative."

    return None


def handler(event, context):

    request_id = str(uuid.uuid4())[:8]

    request_context = event.get("requestContext") or {}

    http_context = request_context.get("http") or {}

    method = (
        http_context.get("method")
        or event.get("httpMethod")
    )

    path = (
        event.get("rawPath")
        or event.get("path")
        or ""
    )

    log_json(
        request_id=request_id,
        event="request_received",
        method=method,
        path=path
    )

    # ============================================================
    # AUTHORIZATION
    # ============================================================

    auth_result = authorize(event)

    if not auth_result["authorized"]:
        return respond(
            401,
            {
                "success": False,
                "error": {
                    "code": auth_result["code"],
                    "message": auth_result["message"]
                }
            },
            request_id
        )

    # ============================================================
    # BUSINESS ROUTING
    # ============================================================

    try:

        if method == "POST" and path == "/products":
            return create_product(
                event,
                request_id
            )

        if method == "GET" and path.startswith("/products/"):
            return get_product(
                event,
                request_id
            )

        if method == "GET" and path == "/products":
            return list_products(
                event,
                request_id
            )

        if method == "PUT" and path.startswith("/products/"):
            return update_product(
                event,
                request_id
            )

        if method == "DELETE" and path.startswith("/products/"):
            return deactivate_product(
                event,
                request_id
            )

        return respond(
            404,
            {
                "success": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No matching route."
                }
            },
            request_id
        )

    except Exception as exc:

        log_json(
            request_id=request_id,
            event="unhandled_error",
            error=str(exc),
            error_type=type(exc).__name__
        )

        return respond(
            500,
            {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected error."
                }
            },
            request_id
        )


def get_low_stock_threshold():

    return int(
        get_ssm_parameter(
            os.environ["LOW_STOCK_THRESHOLD_PARAM"]
        )
    )


def publish_low_stock_alert(
    product_id,
    stock_quantity,
    request_id
):

    sns.publish(
        TopicArn=os.environ["LOW_STOCK_TOPIC_ARN"],
        Subject="CloudMart low stock alert",
        Message=(
            f"Product {product_id} has only "
            f"{stock_quantity} unit(s) left."
        ),
    )

    eventbridge.put_events(
        Entries=[
            {
                "Source": "cloudmart.product",
                "DetailType": "LowStockEvents",
                "EventBusName": os.environ["EVENT_BUS_NAME"],
                "Detail": json.dumps(
                    {
                        "event_id": request_id,
                        "event_type": "LowStockEvents",
                        "source": "cloudmart.product",
                        "event_time": (
                            datetime.datetime.utcnow().isoformat()
                            + "Z"
                        ),
                        "environment": os.environ["ENVIRONMENT"],
                        "detail": {
                            "product_id": product_id,
                            "stock_quantity": stock_quantity
                        }
                    }
                ),
            }
        ]
    )

    log_json(
        request_id=request_id,
        event="low_stock_alert_published",
        product_id=product_id,
        stock_quantity=stock_quantity
    )


def create_product(event, request_id):

    try:
        body = json.loads(
            event.get("body") or "{}"
        )
    except json.JSONDecodeError:
        return respond(
            400,
            {
                "success": False,
                "error": {
                    "code": "INVALID_JSON",
                    "message": "Request body must contain valid JSON."
                }
            },
            request_id
        )

    validation_error = validate_product_data(body)

    if validation_error:
        return respond(
            400,
            {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": validation_error
                }
            },
            request_id
        )

    conn = get_db_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT category_id
                FROM categories
                WHERE category_name=%s
                AND status='ACTIVE'
                """,
                (body["category"].strip(),)
            )

            category = cur.fetchone()

            if not category:

                return respond(
                    404,
                    {
                        "success": False,
                        "error": {
                            "code": "CATEGORY_NOT_FOUND",
                            "message": (
                                f"Category '{body['category'].strip()}' "
                                "was not found."
                            )
                        }
                    },
                    request_id
                )

            cur.execute(
                """
                INSERT INTO products
                (
                    category_id,
                    product_name,
                    description,
                    price,
                    stock_quantity,
                    status
                )
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (
                    category["category_id"],
                    body["product_name"].strip(),
                    body.get("description"),
                    body["price"],
                    body["stock_quantity"],
                    "ACTIVE"
                ),
            )

            conn.commit()

            product_id = cur.lastrowid

    finally:
        conn.close()

    log_json(
        request_id=request_id,
        event="product_created",
        product_id=product_id
    )

    if (
        body["stock_quantity"]
        <= get_low_stock_threshold()
    ):

        publish_low_stock_alert(
            product_id,
            body["stock_quantity"],
            request_id
        )

    return respond(
        201,
        {
            "success": True,
            "message": "Product created successfully.",
            "data": {
                "product_id": product_id,
                **body
            }
        },
        request_id
    )


def get_product(event, request_id):

    path_parameters = (
        event.get("pathParameters")
        or {}
    )

    product_id = path_parameters.get(
        "productId"
    )

    if not product_id:

        path = (
            event.get("rawPath")
            or ""
        )

        product_id = path.rstrip("/").split("/")[-1]

    conn = get_db_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    p.product_id,
                    p.product_name,
                    c.category_name AS category,
                    p.description,
                    p.price,
                    p.stock_quantity,
                    p.status,
                    p.created_at,
                    p.updated_at
                FROM products p
                JOIN categories c
                    ON p.category_id = c.category_id
                WHERE p.product_id=%s
                """,
                (product_id,)
            )

            product = cur.fetchone()

    finally:
        conn.close()

    if not product:

        return respond(
            404,
            {
                "success": False,
                "error": {
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found."
                }
            },
            request_id
        )

    return respond(
        200,
        {
            "success": True,
            "message": "Product retrieved successfully.",
            "data": product
        },
        request_id
    )


def list_products(event, request_id):

    query_parameters = (
        event.get("queryStringParameters")
        or {}
    )

    category = query_parameters.get(
        "category"
    )

    status = query_parameters.get(
        "status",
        "ACTIVE"
    )

    query = """
        SELECT
            p.product_id,
            p.product_name,
            c.category_name AS category,
            p.description,
            p.price,
            p.stock_quantity,
            p.status,
            p.created_at,
            p.updated_at
        FROM products p
        JOIN categories c
            ON p.category_id = c.category_id
        WHERE p.status=%s
    """

    params = [status]

    if category:

        query += " AND c.category_name=%s"

        params.append(category.strip())

    conn = get_db_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                query,
                params
            )

            products = cur.fetchall()

    finally:
        conn.close()

    return respond(
        200,
        {
            "success": True,
            "message": (
                "Products retrieved successfully."
                if products
                else "No products found."
            ),
            "data": products
        },
        request_id
    )


def update_product(event, request_id):

    path_parameters = (
        event.get("pathParameters")
        or {}
    )

    product_id = path_parameters.get(
        "productId"
    )

    if not product_id:

        path = (
            event.get("rawPath")
            or ""
        )

        product_id = path.rstrip("/").split("/")[-1]

    try:
        body = json.loads(
            event.get("body") or "{}"
        )
    except json.JSONDecodeError:
        return respond(
            400,
            {
                "success": False,
                "error": {
                    "code": "INVALID_JSON",
                    "message": "Request body must contain valid JSON."
                }
            },
            request_id
        )

    validation_error = validate_product_data(
        body,
        required_fields=False
    )

    if validation_error:
        return respond(
            400,
            {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": validation_error
                }
            },
            request_id
        )

    conn = get_db_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *
                FROM products
                WHERE product_id=%s
                """,
                (product_id,)
            )

            existing = cur.fetchone()

            if not existing:

                return respond(
                    404,
                    {
                        "success": False,
                        "error": {
                            "code": "PRODUCT_NOT_FOUND",
                            "message": "Product not found."
                        }
                    },
                    request_id
                )

            if "category" in body:

                cur.execute(
                    """
                    SELECT category_id
                    FROM categories
                    WHERE category_name=%s
                    AND status='ACTIVE'
                    """,
                    (body["category"].strip(),)
                )

                category = cur.fetchone()

                if not category:

                    return respond(
                        404,
                        {
                            "success": False,
                            "error": {
                                "code": "CATEGORY_NOT_FOUND",
                                "message": (
                                    f"Category '{body['category'].strip()}' "
                                    "was not found."
                                )
                            }
                        },
                        request_id
                    )

                category_id = category["category_id"]

            else:

                category_id = existing["category_id"]

            new_stock = body.get(
                "stock_quantity",
                existing["stock_quantity"]
            )

            new_status = existing["status"]

            # Zero-stock business rule
            if new_stock == 0:
                new_status = "INACTIVE"

            cur.execute(
                """
                UPDATE products
                SET
                    product_name=%s,
                    description=%s,
                    category_id=%s,
                    price=%s,
                    stock_quantity=%s,
                    status=%s,
                    updated_at=NOW()
                WHERE product_id=%s
                """,
                (
                    body.get(
                        "product_name",
                        existing["product_name"]
                    ),
                    body.get(
                        "description",
                        existing["description"]
                    ),
                    category_id,
                    body.get(
                        "price",
                        existing["price"]
                    ),
                    new_stock,
                    new_status,
                    product_id
                ),
            )

            conn.commit()

    finally:
        conn.close()

    log_json(
        request_id=request_id,
        event="product_updated",
        product_id=product_id,
        new_stock=new_stock
    )

    if (
        new_stock
        <= get_low_stock_threshold()
    ):

        publish_low_stock_alert(
            product_id,
            new_stock,
            request_id
        )

    return respond(
        200,
        {
            "success": True,
            "message": "Product updated successfully.",
            "data": {
                "product_id": product_id,
                "stock_quantity": new_stock,
                "status": new_status
            }
        },
        request_id
    )


def deactivate_product(event, request_id):

    path_parameters = (
        event.get("pathParameters")
        or {}
    )

    product_id = path_parameters.get(
        "productId"
    )

    if not product_id:

        path = (
            event.get("rawPath")
            or ""
        )

        product_id = path.rstrip("/").split("/")[-1]

    conn = get_db_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT status
                FROM products
                WHERE product_id=%s
                """,
                (product_id,)
            )

            existing = cur.fetchone()

            if not existing:

                return respond(
                    404,
                    {
                        "success": False,
                        "error": {
                            "code": "PRODUCT_NOT_FOUND",
                            "message": "Product not found."
                        }
                    },
                    request_id
                )

            if existing["status"] == "INACTIVE":

                return respond(
                    409,
                    {
                        "success": False,
                        "error": {
                            "code": "PRODUCT_ALREADY_INACTIVE",
                            "message": "Product is already inactive."
                        }
                    },
                    request_id
                )

            cur.execute(
                """
                UPDATE products
                SET
                    status='INACTIVE',
                    updated_at=NOW()
                WHERE product_id=%s
                """,
                (product_id,)
            )

            conn.commit()

    finally:
        conn.close()

    log_json(
        request_id=request_id,
        event="product_deactivated",
        product_id=product_id
    )

    return respond(
        200,
        {
            "success": True,
            "message": "Product deactivated successfully."
        },
        request_id
    )