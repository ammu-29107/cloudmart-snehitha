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
ses = boto3.client("sesv2")

SES_SENDER_EMAIL = os.environ[
    "SES_SENDER_EMAIL"
]

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

def publish_order_notification(
    order_id,
    customer_id,
    customer_email,
    previous_status,
    new_status
):
    try:
        ses.send_email(
            FromEmailAddress=SES_SENDER_EMAIL,
            Destination={
                "ToAddresses": [
                    customer_email
                ]
            },
            Content={
                "Simple": {
                    "Subject": {
                        "Data": (
                            f"CloudMart Order "
                            f"{order_id} Status Update"
                        )
                    },
                    "Body": {
                        "Text": {
                            "Data": json.dumps(
                                {
                                    "order_id": order_id,
                                    "customer_id": customer_id,
                                    "previous_status": previous_status,
                                    "new_status": new_status
                                },
                                indent=4
                            )
                        }
                    }
                }
            }
        )

    except Exception as exc:
        logger.error(
            json.dumps(
                {
                    "event": "order_notification_failed",
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "error": str(exc),
                    "error_type": type(exc).__name__
                }
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

            publish_order_notification(
                order_id=order_id,
                customer_id=customer_id,
                customer_email=customer["email"],
                previous_status=None,
                new_status="PENDING"
            )


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
# GET ORDER BY ID
# ================================================================

def get_order_by_id(event):

    path_parameters = event.get("pathParameters") or {}

    order_id = path_parameters.get("orderId")

    if not order_id:

        path = (
            event.get("rawPath")
            or event.get("path")
            or ""
        )

        path_parts = path.strip("/").split("/")

        if (
            len(path_parts) == 2
            and path_parts[0] == "orders"
        ):
            order_id = path_parts[1]

    if not order_id:

        return respond(
            400,
            {
                "success": False,
                "message": "Order ID is required."
            }
        )

    try:

        order_id = int(order_id)

    except ValueError:

        return respond(
            400,
            {
                "success": False,
                "message": "Order ID must be an integer."
            }
        )

    conn = None

    try:

        conn = get_db_connection()

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    order_id,
                    customer_id,
                    shipping_address_id,
                    billing_address_id,
                    status,
                    total_amount,
                    created_at,
                    updated_at
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                conn.rollback()

                return respond(
                    404,
                    {
                        "success": False,
                        "message": "Order not found."
                    }
                )

            cursor.execute(
                """
                SELECT
                    order_item_id,
                    product_id,
                    quantity,
                    unit_price,
                    subtotal
                FROM order_items
                WHERE order_id = %s
                ORDER BY order_item_id
                """,
                (order_id,)
            )

            items = cursor.fetchall()

        return respond(
            200,
            {
                "success": True,
                "data": {
                    "order_id": order["order_id"],
                    "customer_id": order["customer_id"],
                    "shipping_address_id": order["shipping_address_id"],
                    "billing_address_id": order["billing_address_id"],
                    "status": order["status"],
                    "total_amount": order["total_amount"],
                    "created_at": order["created_at"],
                    "updated_at": order["updated_at"],
                    "items": items
                }
            }
        )

    except Exception as exc:

        if conn:
            conn.rollback()

        log_json(
            event="get_order_failed",
            order_id=order_id,
            error=str(exc),
            error_type=type(exc).__name__
        )

        return respond(
            500,
            {
                "success": False,
                "message": "Unable to retrieve order."
            }
        )

    finally:

        if conn:
            conn.close()


# ================================================================
# GET ORDERS BY CUSTOMER
# ================================================================

def get_orders_by_customer(event):

    query_parameters = (
        event.get("queryStringParameters")
        or {}
    )

    customer_id = query_parameters.get(
        "customerId"
    )

    if not customer_id:

        return respond(
            400,
            {
                "success": False,
                "message": "customerId is required."
            }
        )

    try:

        customer_id = int(customer_id)

    except ValueError:

        return respond(
            400,
            {
                "success": False,
                "message": "customerId must be an integer."
            }
        )

    conn = None

    try:

        conn = get_db_connection()

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    order_id,
                    customer_id,
                    shipping_address_id,
                    billing_address_id,
                    status,
                    total_amount,
                    created_at,
                    updated_at
                FROM orders
                WHERE customer_id = %s
                ORDER BY created_at DESC
                """,
                (customer_id,)
            )

            orders = cursor.fetchall()

        return respond(
            200,
            {
                "success": True,
                "data": orders
            }
        )

    except Exception as exc:

        if conn:
            conn.rollback()

        log_json(
            event="get_customer_orders_failed",
            customer_id=customer_id,
            error=str(exc),
            error_type=type(exc).__name__
        )

        return respond(
            500,
            {
                "success": False,
                "message": "Unable to retrieve customer orders."
            }
        )

    finally:

        if conn:
            conn.close()


# ================================================================
# CANCEL ORDER
# ================================================================

def cancel_order(event):

    path_parameters = event.get("pathParameters") or {}

    order_id = path_parameters.get("orderId")

    if not order_id:

        path = (
            event.get("rawPath")
            or event.get("path")
            or ""
        )

        path_parts = path.strip("/").split("/")

        if (
            len(path_parts) == 2
            and path_parts[0] == "orders"
        ):
            order_id = path_parts[1]

    if not order_id:

        return respond(
            400,
            {
                "success": False,
                "message": "Order ID is required."
            }
        )

    try:

        order_id = int(order_id)

    except ValueError:

        return respond(
            400,
            {
                "success": False,
                "message": "Order ID must be an integer."
            }
        )

    body = parse_body(event)

    if body is None:

        return respond(
            400,
            {
                "success": False,
                "message": "Request body must contain valid JSON."
            }
        )

    if body.get("status") != "CANCELLED":

        return respond(
            400,
            {
                "success": False,
                "message": "Only order cancellation is supported."
            }
        )

    conn = None

    try:

        conn = get_db_connection()

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    order_id,
                    customer_id,
                    status,
                    created_at
                FROM orders
                WHERE order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:

                conn.rollback()

                return respond(
                    404,
                    {
                        "success": False,
                        "message": "Order not found."
                    }
                )

            if order["status"] != "PENDING":

                conn.rollback()

                return respond(
                    400,
                    {
                        "success": False,
                        "message": (
                            "Only PENDING orders can be cancelled."
                        )
                    }
                )

            cursor.execute(
                """
                SELECT
                    TIMESTAMPDIFF(
                        SECOND,
                        created_at,
                        CURRENT_TIMESTAMP
                    ) AS age_seconds
                FROM orders
                WHERE order_id = %s
                """,
                (order_id,)
            )

            order_age = cursor.fetchone()["age_seconds"]

            if order_age > 15:

                conn.rollback()

                return respond(
                    400,
                    {
                        "success": False,
                        "message": "Order can no longer be cancelled."
                    }
                )

            cursor.execute(
                """
                SELECT
                    email
                FROM customers
                WHERE customer_id = %s
                """,
                (order["customer_id"],)
            )

            customer = cursor.fetchone()


            cursor.execute(
                """
                UPDATE orders
                SET
                    status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE order_id = %s
                """,
                (
                    "CANCELLED",
                    order_id
                )
            )

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
                    "PENDING",
                    "CANCELLED"
                )
            )

            cursor.execute(
                """
                UPDATE idempotency_keys
                SET status = 'CANCELLED'
                WHERE order_id = %s
                """,
                (order_id,)
            )

            conn.commit()

            publish_order_notification(
                order_id=order_id,
                customer_id=order["customer_id"],
                customer_email=customer["email"],
                previous_status="PENDING",
                new_status="CANCELLED"
            )

        eventbridge.put_events(
            Entries=[
                {
                    "Source": "cloudmart.order",
                    "DetailType": "OrderCancelled",
                    "EventBusName": os.environ["EVENT_BUS_NAME"],
                    "Detail": json.dumps(
                        {
                            "event_id": str(uuid.uuid4()),
                            "event_type": "OrderCancelled",
                            "order_id": order_id,
                            "customer_id": order["customer_id"],
                            "status": "CANCELLED"
                        }
                    )
                }
            ]
        )

        log_json(
            event="order_cancelled",
            order_id=order_id
        )

        return respond(
            200,
            {
                "success": True,
                "message": "Order cancelled successfully.",
                "data": {
                    "order_id": order_id,
                    "status": "CANCELLED"
                }
            }
        )

    except Exception as exc:

        if conn:
            conn.rollback()

        log_json(
            event="order_cancellation_failed",
            order_id=order_id,
            error=str(exc),
            error_type=type(exc).__name__
        )

        return respond(
            500,
            {
                "success": False,
                "message": "Unable to cancel order."
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

        if (
            method == "PATCH"
            and path.startswith("/orders/")
        ):

            return cancel_order(event)

        if (
            method == "GET"
            and path.startswith("/orders/")
        ):

            return get_order_by_id(event)

        if (
            method == "GET"
            and path == "/orders"
        ):

            return get_orders_by_customer(event)


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