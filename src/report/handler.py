import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")
s3 = boto3.client("s3")
cloudwatch = boto3.client("cloudwatch")


ENVIRONMENT = os.environ["ENVIRONMENT"]

DB_HOST_PARAM = os.environ["DB_HOST_PARAM"]
DB_NAME_PARAM = os.environ["DB_NAME_PARAM"]
DB_USER_PARAM = os.environ["DB_USER_PARAM"]
DB_PASSWORD_PARAM = os.environ["DB_PASSWORD_PARAM"]

REPORT_BUCKET = os.environ["REPORT_BUCKET"]
REPORT_PREFIX = os.environ.get("REPORT_PREFIX", "reports")

REPORT_TIMEZONE = ZoneInfo(
    os.environ.get("REPORT_TIMEZONE", "Asia/Kolkata")
)


def log_json(**kwargs):
    logger.info(
        json.dumps(
            kwargs,
            default=str
        )
    )


def get_ssm_parameter(name, decrypt=False):
    logger.info("ssm_parameter_start name=%s decrypt=%s", name, decrypt)
    response = ssm.get_parameter(Name=name, WithDecryption=decrypt)
    logger.info("ssm_parameter_success name=%s", name)
    return response["Parameter"]["Value"]


def get_db_connection():
    logger.info("db_connection_start")

    host = get_ssm_parameter(DB_HOST_PARAM)
    database = get_ssm_parameter(DB_NAME_PARAM)
    username = get_ssm_parameter(DB_USER_PARAM)
    password = get_ssm_parameter(DB_PASSWORD_PARAM, decrypt=True)

    logger.info("db_parameters_loaded")

    conn = pymysql.connect(
        host=host,
        user=username,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
        autocommit=True
    )

    logger.info("db_connection_success")
    return conn


def get_report_window(mode):
    now_local = datetime.now(REPORT_TIMEZONE)

    if mode == "current":
        start_local = now_local.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end_local = now_local

        report_date = start_local.date()

    else:
        current_day_start = now_local.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        end_local = current_day_start
        start_local = current_day_start - timedelta(days=1)

        report_date = start_local.date()

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    return (
        start_local,
        end_local,
        start_utc,
        end_utc,
        report_date
    )


def fetch_report_data(start_utc, end_utc):
    conn = None

    try:
        conn = get_db_connection()

        with conn.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    o.order_id,
                    o.customer_id,
                    o.created_at,
                    o.updated_at,
                    o.status,
                    o.total_amount,

                    oi.order_item_id,
                    oi.product_id,
                    oi.quantity,
                    oi.unit_price,
                    oi.subtotal,

                    p.product_name,
                    p.stock_quantity,
                    p.status AS product_status

                FROM orders o

                INNER JOIN order_items oi
                    ON oi.order_id = o.order_id

                INNER JOIN products p
                    ON p.product_id = oi.product_id

                WHERE o.created_at >= %s
                  AND o.created_at < %s

                ORDER BY
                    o.created_at ASC,
                    o.order_id ASC,
                    oi.order_item_id ASC
                """,
                (
                    start_utc.replace(tzinfo=None),
                    end_utc.replace(tzinfo=None)
                )
            )

            order_items = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    product_id,
                    product_name,
                    price,
                    stock_quantity,
                    status
                FROM products
                ORDER BY product_id
                """
            )

            products = cursor.fetchall()

        return order_items, products

    finally:
        if conn:
            conn.close()


def build_csv(
    order_items,
    products,
    start_local,
    end_local,
    report_date
):
    output = io.StringIO(
        newline=""
    )

    writer = csv.writer(output)

    writer.writerow(
        [
            "CloudMart Daily Report"
        ]
    )

    writer.writerow(
        [
            "Report Date",
            report_date.strftime("%d-%m-%Y")
        ]
    )

    writer.writerow(
        [
            "Report Window",
            f"{start_local.strftime('%d-%m-%Y %H:%M:%S')} "
            f"to "
            f"{end_local.strftime('%d-%m-%Y %H:%M:%S')} "
            f"IST"
        ]
    )

    writer.writerow(
        [
            "Environment",
            ENVIRONMENT
        ]
    )

    writer.writerow([])

    writer.writerow(
        [
            "ORDER ITEM DETAILS"
        ]
    )

    writer.writerow(
        [
            "Order ID",
            "Customer ID",
            "Created Time",
            "Updated Time",
            "Order Status",
            "Total Amount",
            "Order Item ID",
            "Product ID",
            "Quantity",
            "Unit Price",
            "Subtotal",
            "Product Name",
            "Current Stock",
            "Product Status"
        ]
    )

    for row in order_items:
        writer.writerow(
            [
                row["order_id"],
                row["customer_id"],
                row["created_at"],
                row["updated_at"],
                row["status"],
                row["total_amount"],
                row["order_item_id"],
                row["product_id"],
                row["quantity"],
                row["unit_price"],
                row["subtotal"],
                row["product_name"],
                row["stock_quantity"],
                row["product_status"]
            ]
        )

    writer.writerow([])
    writer.writerow([])

    writer.writerow(
        [
            "PRODUCT INVENTORY SUMMARY"
        ]
    )

    writer.writerow(
        [
            "Product ID",
            "Product Name",
            "Price",
            "Current Stock",
            "Product Status",
            "Low Stock"
        ]
    )

    low_stock_threshold = int(
        os.environ.get(
            "LOW_STOCK_THRESHOLD",
            "10"
        )
    )

    for product in products:
        writer.writerow(
            [
                product["product_id"],
                product["product_name"],
                product["price"],
                product["stock_quantity"],
                product["status"],
                (
                    "YES"
                    if product["stock_quantity"]
                    <= low_stock_threshold
                    else "NO"
                )
            ]
        )

    return output.getvalue()


def put_report(
    report_date,
    csv_content
):
    date_path = report_date.strftime(
        "%Y/%m/%d"
    )

    filename = (
        "cloudmart daily report - "
        f"{report_date.strftime('%d-%m-%Y')}.csv"
    )

    key = (
        f"{REPORT_PREFIX}/"
        f"{date_path}/"
        f"{filename}"
    )

    s3.put_object(
        Bucket=REPORT_BUCKET,
        Key=key,
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv"
    )

    return key


def publish_metric(metric_name, value=1):
    try:
        cloudwatch.put_metric_data(
            Namespace="CloudMart/Operations",
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Dimensions": [
                        {
                            "Name": "Environment",
                            "Value": ENVIRONMENT
                        }
                    ],
                    "Value": value,
                    "Unit": "Count"
                }
            ]
        )

    except Exception as exc:
        logger.warning(
            json.dumps(
                {
                    "event": "metric_publish_failed",
                    "metric_name": metric_name,
                    "error": str(exc)
                }
            )
        )


def lambda_handler(event, context):
    mode = "scheduled"

    if isinstance(event, dict):
        mode = event.get(
            "mode",
            "scheduled"
        )

    if mode not in (
        "scheduled",
        "current"
    ):
        mode = "scheduled"

    try:
        (
            start_local,
            end_local,
            start_utc,
            end_utc,
            report_date
        ) = get_report_window(mode)

        log_json(
            event="report_generation_started",
            mode=mode,
            report_date=str(report_date),
            start_local=start_local,
            end_local=end_local
        )

        order_items, products = fetch_report_data(
            start_utc,
            end_utc
        )

        csv_content = build_csv(
            order_items,
            products,
            start_local,
            end_local,
            report_date
        )

        key = put_report(
            report_date,
            csv_content
        )

        publish_metric(
            "ReportGenerationSuccess"
        )

        log_json(
            event="report_generation_completed",
            mode=mode,
            report_date=str(report_date),
            object_key=key,
            order_item_rows=len(order_items),
            product_rows=len(products)
        )

        return {
            "statusCode": 200,
            "success": True,
            "message": "Report generated successfully.",
            "report_date": report_date.strftime(
                "%d-%m-%Y"
            ),
            "s3_bucket": REPORT_BUCKET,
            "s3_key": key,
            "mode": mode
        }

    except Exception as exc:
        publish_metric(
            "ReportGenerationFailed"
        )

        log_json(
            event="report_generation_failed",
            mode=mode,
            error=str(exc),
            error_type=type(exc).__name__
        )

        raise