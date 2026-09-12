import json
import logging
import os

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
events = boto3.client("events")
ses = boto3.client("sesv2")


DB_HOST_PARAM = os.environ["DB_HOST_PARAM"]
DB_NAME_PARAM = os.environ["DB_NAME_PARAM"]
DB_USER_PARAM = os.environ["DB_USER_PARAM"]
DB_PASSWORD_PARAM = os.environ["DB_PASSWORD_PARAM"]
EVENT_BUS_NAME = os.environ["EVENT_BUS_NAME"]
SES_SENDER_EMAIL = os.environ[
    "SES_SENDER_EMAIL"
]


def get_parameter(name):
    response = ssm.get_parameter(
        Name=name,
        WithDecryption=True
    )
    return response["Parameter"]["Value"]


def get_db_connection():
    return pymysql.connect(
        host=get_parameter(DB_HOST_PARAM),
        user=get_parameter(DB_USER_PARAM),
        password=get_parameter(DB_PASSWORD_PARAM),
        database=get_parameter(DB_NAME_PARAM),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=False
    )


def publish_event(detail_type, detail):
    response = events.put_events(
        Entries=[
            {
                "Source": "cloudmart.order-processing",
                "DetailType": detail_type,
                "Detail": json.dumps(detail),
                "EventBusName": EVENT_BUS_NAME
            }
        ]
    )

    if response.get("FailedEntryCount", 0) > 0:
        logger.error(
            json.dumps(
                {
                    "event": "eventbridge_publish_failed",
                    "detail_type": detail_type,
                    "response": response
                },
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
                "ToAddresses": [customer_email]
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

def record_status_history(
    cursor,
    order_id,
    previous_status,
    new_status
):
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
            previous_status,
            new_status
        )
    )


def mark_order_failed(order_id, reason):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT status
                FROM orders
                WHERE order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:
                connection.rollback()
                return

            current_status = order["status"]

            if current_status in (
                "COMPLETED",
                "FAILED",
                "CANCELLED"
            ):
                connection.rollback()
                return

            cursor.execute(
                """
                UPDATE orders
                SET status = 'FAILED'
                WHERE order_id = %s
                """,
                (order_id,)
            )

            record_status_history(
                cursor,
                order_id,
                current_status,
                "FAILED"
            )

            connection.commit()

            logger.error(
                json.dumps(
                    {
                        "event": "order_failed",
                        "order_id": order_id,
                        "previous_status": current_status,
                        "reason": reason
                    }
                )
            )

    finally:
        connection.close()


def mark_idempotency_completed(cursor, order_id):
    cursor.execute(
        """
        UPDATE idempotency_keys
        SET status = 'COMPLETED'
        WHERE order_id = %s
        """,
        (order_id,)
    )


def mark_idempotency_failed(order_id):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE idempotency_keys
                SET status = 'FAILED'
                WHERE order_id = %s
                """,
                (order_id,)
            )

            connection.commit()

    finally:
        connection.close()


def process_order(order_id):
    connection = get_db_connection()

    try:
        with connection.cursor() as cursor:

            # ----------------------------------------------------
            # Lock the order.
            # This protects against duplicate SQS deliveries.
            # ----------------------------------------------------

            cursor.execute(
                """
                SELECT
                    order_id,
                    customer_id,
                    status,
                    total_amount
                FROM orders
                WHERE order_id = %s
                FOR UPDATE
                """,
                (order_id,)
            )

            order = cursor.fetchone()

            if not order:
                logger.error(
                    json.dumps(
                        {
                            "event": "order_not_found",
                            "order_id": order_id
                        }
                    )
                )

                connection.rollback()
                return "IGNORED", None

            current_status = order["status"]

            # ----------------------------------------------------
            # Duplicate delivery protection.
            # ----------------------------------------------------

            if current_status in (
                "COMPLETED",
                "FAILED",
                "CANCELLED"
            ):
                logger.info(
                    json.dumps(
                        {
                            "event": "order_already_processed",
                            "order_id": order_id,
                            "status": current_status
                        }
                    )
                )

                connection.rollback()
                return "IGNORED", order["customer_id"]

            # ----------------------------------------------------
            # Normal processing starts only from PENDING.
            # ----------------------------------------------------

            if current_status != "PENDING":
                logger.info(
                    json.dumps(
                        {
                            "event": "order_not_pending",
                            "order_id": order_id,
                            "status": current_status
                        }
                    )
                )

                connection.rollback()
                return "IGNORED", order["customer_id"]

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

            if not customer:
                raise ValueError(
                    f"Customer {order['customer_id']} not found."
                )

            customer_email = customer["email"]

            # ----------------------------------------------------
            # PENDING -> PROCESSING
            # ----------------------------------------------------

            cursor.execute(
                """
                UPDATE orders
                SET status = 'PROCESSING'
                WHERE order_id = %s
                """,
                (order_id,)
            )

            record_status_history(
                cursor,
                order_id,
                "PENDING",
                "PROCESSING"
            )

            connection.commit()

            publish_order_notification(
                order_id=order_id,
                customer_id=order["customer_id"],
                customer_email=customer_email,
                previous_status="PENDING",
                new_status="PROCESSING"
            )

            # ----------------------------------------------------
            # Read order items.
            # ----------------------------------------------------

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
                """,
                (order_id,)
            )

            items = cursor.fetchall()

            if not items:
                raise ValueError(
                    "Order contains no items."
                )

            # ----------------------------------------------------
            # Validate stock and deduct inventory.
            # ----------------------------------------------------

            for item in items:

                cursor.execute(
                    """
                    SELECT
                        product_id,
                        product_name,
                        stock_quantity,
                        status
                    FROM products
                    WHERE product_id = %s
                    FOR UPDATE
                    """,
                    (item["product_id"],)
                )

                product = cursor.fetchone()

                if not product:
                    raise ValueError(
                        f"Product {item['product_id']} not found."
                    )

                if product["status"] != "ACTIVE":
                    raise ValueError(
                        f"Product {item['product_id']} is inactive."
                    )

                if product["stock_quantity"] < item["quantity"]:
                    raise ValueError(
                        f"Insufficient stock for product "
                        f"{item['product_id']}."
                    )

                cursor.execute(
                    """
                    UPDATE products
                    SET stock_quantity = stock_quantity - %s
                    WHERE product_id = %s
                    """,
                    (
                        item["quantity"],
                        item["product_id"]
                    )
                )

                cursor.execute(
                    """
                    INSERT INTO inventory_transactions
                    (
                        product_id,
                        order_id,
                        change_quantity,
                        transaction_type
                    )
                    VALUES (%s, %s, %s, 'DEDUCTION')
                    """,
                    (
                        item["product_id"],
                        order_id,
                        -item["quantity"]
                    )
                )

            # ----------------------------------------------------
            # All inventory operations succeeded.
            # PROCESSING -> COMPLETED
            # ----------------------------------------------------

            cursor.execute(
                """
                UPDATE orders
                SET status = 'COMPLETED'
                WHERE order_id = %s
                """,
                (order_id,)
            )

            record_status_history(
                cursor,
                order_id,
                "PROCESSING",
                "COMPLETED"
            )

            # ----------------------------------------------------
            # Mark idempotency key as completed.
            # ----------------------------------------------------

            mark_idempotency_completed(
                cursor,
                order_id
            )

            # ----------------------------------------------------
            # Commit the complete business transaction.
            # ----------------------------------------------------

            connection.commit()

            publish_order_notification(
                order_id=order_id,
                customer_id=order["customer_id"],
                customer_email=customer_email,
                previous_status="PROCESSING",
                new_status="COMPLETED"
            )

            logger.info(
                json.dumps(
                    {
                        "event": "order_completed",
                        "order_id": order_id,
                        "customer_id": order["customer_id"],
                        "total_amount": str(
                            order["total_amount"]
                        )
                    }
                )
            )

            return "COMPLETED", order["customer_id"]

    except ValueError as exc:

        # --------------------------------------------------------
        # Expected business failure.
        #
        # Roll back:
        # - PROCESSING status
        # - any stock deductions
        # - inventory transactions
        #
        # Then mark the order FAILED in a separate transaction.
        # --------------------------------------------------------

        connection.rollback()

        failure_customer_id = order["customer_id"]

        mark_order_failed(
            order_id,
            str(exc)
        )

        mark_idempotency_failed(
            order_id
        )

        publish_order_notification(
            order_id=order_id,
            customer_id=failure_customer_id,
            customer_email=customer_email,
            previous_status="PROCESSING",
            new_status="FAILED"
        )

        publish_event(
            "OrderFailed",
            {
                "order_id": order_id,
                "reason": str(exc)
            }
        )

        return "FAILED", failure_customer_id

    except Exception:
        # Unexpected errors should be retried by SQS.
        connection.rollback()
        raise

    finally:
        connection.close()


def handler(event, context):

    batch_item_failures = []

    records = event.get("Records", [])

    for record in records:

        message_id = record.get("messageId")

        try:
            body = json.loads(
                record["body"]
            )

            order_id = body.get(
                "order_id"
            )

            if not order_id:
                raise ValueError(
                    "SQS message does not contain order_id."
                )

            logger.info(
                json.dumps(
                    {
                        "event": "order_processing_started",
                        "order_id": order_id,
                        "message_id": message_id
                    }
                )
            )

            result, customer_id = process_order(
                order_id
            )

            if result == "COMPLETED":

                publish_event(
                    "OrderConfirmed",
                    {
                        "order_id": order_id,
                        "customer_id": customer_id,
                        "status": "COMPLETED"
                    }
                )

            logger.info(
                json.dumps(
                    {
                        "event": "order_processing_finished",
                        "order_id": order_id,
                        "result": result,
                        "message_id": message_id
                    }
                )
            )

        except Exception as exc:

            logger.exception(
                json.dumps(
                    {
                        "event": "order_processing_error",
                        "message_id": message_id,
                        "error": str(exc),
                        "error_type": type(exc).__name__
                    }
                )
            )

            batch_item_failures.append(
                {
                    "itemIdentifier": message_id
                }
            )

    return {
        "batchItemFailures": batch_item_failures
    }