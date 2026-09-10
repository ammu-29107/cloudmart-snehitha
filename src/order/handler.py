import json
import logging
import os
import uuid
from decimal import Decimal

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")
sqs = boto3.client("sqs")
eventbridge = boto3.client("events")


# ================================================================
# HELPERS
# ================================================================

def log_json(**kwargs):

    logger.info(
        json.dumps(
            kwargs,
            default=str
        )
    )


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
        autocommit=False
    )


def respond(status, body):

    return {
        "statusCode": status,

        "headers": {
            "Content-Type": "application/json"
        },

        "body": json.dumps(
            body,
            default=str,
            indent=4
        )
    }


# ================================================================
# REQUEST VALIDATION
# ================================================================

def parse_body(event):

    try:

        return json.loads(
            event.get("body") or "{}"
        )

    except json.JSONDecodeError:

        return None


def validate_order_data(body):

    required_fields = [
        "customer_id",
        "shipping_address_id",
        "billing_address_id",
        "idempotency_key",
        "items"
    ]

    missing = [
        field
        for field in required_fields
        if field not in body
    ]

    if missing:

        return (
            "Missing required field(s): "
            + ", ".join(missing)
        )


    if not isinstance(body["customer_id"], int):

        return "customer_id must be an integer."


    if not isinstance(
        body["shipping_address_id"],
        int
    ):

        return "shipping_address_id must be an integer."


    if not isinstance(
        body["billing_address_id"],
        int
    ):

        return "billing_address_id must be an integer."


    if not isinstance(
        body["idempotency_key"],
        str
    ):

        return "idempotency_key must be a string."


    idempotency_key = body["idempotency_key"].strip()

    if not idempotency_key:

        return "idempotency_key cannot be empty."


    if len(idempotency_key) > 64:

        return "idempotency_key cannot exceed 64 characters."


    if not isinstance(
        body["items"],
        list
    ):

        return "items must be an array."


    if not body["items"]:

        return "Order must contain at least one item."


    for item in body["items"]:

        if not isinstance(item, dict):

            return "Each order item must be an object."


        if "product_id" not in item:

            return "Each order item requires product_id."


        if "quantity" not in item:

            return "Each order item requires quantity."


        if not isinstance(
            item["product_id"],
            int
        ):

            return "product_id must be an integer."


        if (
            isinstance(item["quantity"], bool)
            or not isinstance(item["quantity"], int)
        ):

            return "quantity must be a whole number."


        if item["quantity"] <= 0:

            return "quantity must be greater than zero."


    return None


# ================================================================
# CUSTOMER VALIDATION
# ================================================================

def validate_customer(
    cursor,
    customer_id
):

    cursor.execute(
        """
        SELECT
            customer_id,
            first_name,
            last_name,
            email,
            status
        FROM customers
        WHERE customer_id = %s
        """,
        (customer_id,)
    )

    customer = cursor.fetchone()

    if not customer:

        return None, "Customer not found."


    if customer["status"] != "ACTIVE":

        return None, "Customer is not active."


    return customer, None


# ================================================================
# ADDRESS VALIDATION
# ================================================================

def validate_address(
    cursor,
    address_id,
    customer_id
):

    cursor.execute(
        """
        SELECT
            address_id
        FROM addresses
        WHERE address_id = %s
        AND customer_id = %s
        """,
        (
            address_id,
            customer_id
        )
    )

    address = cursor.fetchone()

    if not address:

        return False

    return True


# ================================================================
# PRODUCT VALIDATION + TOTAL CALCULATION
# ================================================================

def get_order_items(
    cursor,
    items
):

    prepared_items = []
    total_amount = Decimal("0.00")


    for item in items:

        cursor.execute(
            """
            SELECT
                product_id,
                product_name,
                price,
                stock_quantity,
                status
            FROM products
            WHERE product_id = %s
            """,
            (item["product_id"],)
        )

        product = cursor.fetchone()

        if not product:

            raise ValueError(
                f"Product {item['product_id']} was not found."
            )


        if product["status"] != "ACTIVE":

            raise ValueError(
                f"Product {item['product_id']} is not active."
            )


        quantity = item["quantity"]

        unit_price = Decimal(
            str(product["price"])
        )

        subtotal = (
            unit_price
            * quantity
        )


        prepared_items.append(
            {
                "product_id": product["product_id"],
                "quantity": quantity,
                "unit_price": unit_price,
                "subtotal": subtotal
            }
        )


        total_amount += subtotal


    return prepared_items, total_amount


# ================================================================
# IDEMPOTENCY
# ================================================================

def check_existing_idempotency_key(
    cursor,
    idempotency_key
):

    cursor.execute(
        """
        SELECT
            idempotency_key,
            order_id,
            status
        FROM idempotency_keys
        WHERE idempotency_key = %s
        """,
        (idempotency_key,)
    )

    return cursor.fetchone()


# ================================================================
# CREATE ORDER
# ================================================================

def create_order(
    event
):

    body = parse_body(event)

    if body is None:

        return respond(
            400,
            {
                "success": False,
                "message": "Request body must contain valid JSON."
            }
        )


    validation_error = validate_order_data(body)

    if validation_error:

        return respond(
            400,
            {
                "success": False,
                "message": validation_error
            }
        )


    customer_id = body["customer_id"]

    shipping_address_id = body[
        "shipping_address_id"
    ]

    billing_address_id = body[
        "billing_address_id"
    ]

    idempotency_key = body[
        "idempotency_key"
    ].strip()


    conn = None


    try:

        conn = get_db_connection()


        with conn.cursor() as cursor:

            # ====================================================
            # IDEMPOTENCY CHECK
            # ====================================================

            existing = check_existing_idempotency_key(
                cursor,
                idempotency_key
            )

            if existing:

                conn.rollback()

                return respond(
                    200,
                    {
                        "success": True,
                        "message": "Order already exists.",
                        "data": {
                            "order_id": existing["order_id"],
                            "status": existing["status"]
                        }
                    }
                )


            # ====================================================
            # CUSTOMER
            # ====================================================

            customer, customer_error = validate_customer(
                cursor,
                customer_id
            )

            if customer_error:

                conn.rollback()

                return respond(
                    404,
                    {
                        "success": False,
                        "message": customer_error
                    }
                )


            # ====================================================
            # ADDRESSES
            # ====================================================

            if not validate_address(
                cursor,
                shipping_address_id,
                customer_id
            ):

                conn.rollback()

                return respond(
                    400,
                    {
                        "success": False,
                        "message": (
                            "Shipping address does not "
                            "belong to the customer."
                        )
                    }
                )


            if not validate_address(
                cursor,
                billing_address_id,
                customer_id
            ):

                conn.rollback()

                return respond(
                    400,
                    {
                        "success": False,
                        "message": (
                            "Billing address does not "
                            "belong to the customer."
                        )
                    }
                )


            # ====================================================
            # PRODUCTS + TOTAL
            # ====================================================

            try:

                prepared_items, total_amount = get_order_items(
                    cursor,
                    body["items"]
                )

            except ValueError as exc:

                conn.rollback()

                return respond(
                    400,
                    {
                        "success": False,
                        "message": str(exc)
                    }
                )


            # ====================================================
            # CREATE ORDER
            # ====================================================

            cursor.execute(
                """
                INSERT INTO orders
                (
                    customer_id,
                    shipping_address_id,
                    billing_address_id,
                    status,
                    total_amount
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    customer_id,
                    shipping_address_id,
                    billing_address_id,
                    "PENDING",
                    total_amount
                )
            )


            order_id = cursor.lastrowid


            # ====================================================
            # CREATE ORDER ITEMS
            # ====================================================

            for item in prepared_items:

                cursor.execute(
                    """
                    INSERT INTO order_items
                    (
                        order_id,
                        product_id,
                        quantity,
                        unit_price,
                        subtotal
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["quantity"],
                        item["unit_price"],
                        item["subtotal"]
                    )
                )


            # ====================================================
            # CREATE IDEMPOTENCY RECORD
            # ====================================================

            cursor.execute(
                """
                INSERT INTO idempotency_keys
                (
                    idempotency_key,
                    order_id,
                    status
                )
                VALUES (%s, %s, %s)
                """,
                (
                    idempotency_key,
                    order_id,
                    "IN_PROGRESS"
                )
            )


            # ====================================================
            # INITIAL STATUS HISTORY
            # ====================================================

            cursor.execute(
                """
                INSERT INTO order_status_history
                (
                    order_id,
                    previous_status,
                    new_status
                )
                VALUES (%s, %s, %s)
                """,
                (
                    order_id,
                    None,
                    "PENDING"
                )
            )


            conn.commit()


        # ========================================================
        # SEND ORDER TO SQS
        # ========================================================

        sqs_message = {

            "order_id": order_id,

            "customer_id": customer_id,

            "idempotency_key": idempotency_key
        }


        sqs.send_message(

            QueueUrl=os.environ[
                "ORDER_QUEUE_URL"
            ],

            MessageBody=json.dumps(
                sqs_message
            )
        )


        # ========================================================
        # EVENTBRIDGE ORDER PLACED EVENT
        # ========================================================

        eventbridge.put_events(

            Entries=[

                {

                    "Source":
                        "cloudmart.order",

                    "DetailType":
                        "OrderPlaced",

                    "EventBusName":
                        os.environ[
                            "EVENT_BUS_NAME"
                        ],

                    "Detail":
                        json.dumps(
                            {
                                "event_id": str(
                                    uuid.uuid4()
                                ),

                                "event_type":
                                    "OrderPlaced",

                                "order_id":
                                    order_id,

                                "customer_id":
                                    customer_id,

                                "status":
                                    "PENDING"
                            }
                        )
                }
            ]
        )


        log_json(

            event="order_created",

            order_id=order_id,

            customer_id=customer_id,

            total_amount=total_amount
        )


        return respond(

            202,

            {

                "success": True,

                "message":
                    "Order accepted for processing.",

                "data":
                    {

                        "order_id":
                            order_id,

                        "status":
                            "PENDING",

                        "total_amount":
                            total_amount
                    }
            }
        )


    except Exception as exc:

        if conn:

            conn.rollback()


        log_json(

            event="order_creation_failed",

            error=str(exc),

            error_type=type(exc).__name__
        )


        return respond(

            500,

            {

                "success": False,

                "message":
                    "Unable to create order."
            }
        )


    finally:

        if conn:

            conn.close()


# ================================================================
# ROUTER
# ================================================================

def handler(event, context):

    request_id = context.aws_request_id


    request_context = (
        event.get("requestContext")
        or {}
    )

    http_context = (
        request_context.get("http")
        or {}
    )


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


    log_json(

        request_id=request_id,

        event="order_request_received",

        method=method,

        path=path
    )


    try:

        if (
            method == "POST"
            and path == "/orders"
        ):

            return create_order(event)


        return respond(

            404,

            {

                "success": False,

                "message":
                    "No matching route."
            }
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

                "message":
                    "Unexpected error."
            }
        )