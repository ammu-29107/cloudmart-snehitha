import csv
import io
import os
from collections import Counter

import boto3
import pymysql
from pymysql.cursors import DictCursor
from flask import (
    Flask,
    url_for,
    request,
    redirect,
    session,
    render_template
)


app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "cloudmart-dashboard-secret"
)

s3 = boto3.client("s3")

ssm = boto3.client("ssm")

ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "dev"
)

ADMIN_TOKEN_PARAMETER = os.environ.get(
    "ADMIN_TOKEN_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/auth/admin-token"
)

DB_HOST_PARAMETER = os.environ.get(
    "DB_HOST_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/database/host"
)

DB_NAME_PARAMETER = os.environ.get(
    "DB_NAME_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/database/name"
)

DB_USERNAME_PARAMETER = os.environ.get(
    "DB_USERNAME_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/database/username"
)

DB_PASSWORD_PARAMETER = os.environ.get(
    "DB_PASSWORD_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/database/password"
)

LOW_STOCK_THRESHOLD_PARAMETER = os.environ.get(
    "LOW_STOCK_THRESHOLD_PARAMETER",
    f"/cloudmart/{ENVIRONMENT}/inventory/low-stock-threshold"
)

def get_database_connection():
    parameter_names = [
        DB_HOST_PARAMETER,
        DB_NAME_PARAMETER,
        DB_USERNAME_PARAMETER,
        DB_PASSWORD_PARAMETER
    ]

    response = ssm.get_parameters(
        Names=parameter_names,
        WithDecryption=True
    )

    parameters = {
        item["Name"]: item["Value"]
        for item in response["Parameters"]
    }

    return pymysql.connect(
        host=parameters[DB_HOST_PARAMETER],
        user=parameters[DB_USERNAME_PARAMETER],
        password=parameters[DB_PASSWORD_PARAMETER],
        database=parameters[DB_NAME_PARAMETER],
        cursorclass=DictCursor,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10
    )

def load_live_products():
    connection = get_database_connection()

    try:
        with connection.cursor() as cursor:
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

            rows = cursor.fetchall()

    finally:
        connection.close()

    return rows

def load_live_orders():
    connection = get_database_connection()

    try:
        with connection.cursor() as cursor:
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
                    p.product_name
                FROM orders o
                LEFT JOIN order_items oi
                    ON o.order_id = oi.order_id
                LEFT JOIN products p
                    ON oi.product_id = p.product_id
                ORDER BY o.created_at DESC, o.order_id DESC
                """
            )

            rows = cursor.fetchall()

    finally:
        connection.close()

    return rows

def load_live_order_status_counts():
    connection = get_database_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    status,
                    COUNT(*) AS count
                FROM orders
                GROUP BY status
                """
            )

            rows = cursor.fetchall()

    finally:
        connection.close()

    return {
        row["status"].upper(): row["count"]
        for row in rows
    }

def get_live_low_stock_count(products):
    threshold = int(
        ssm.get_parameter(
            Name=LOW_STOCK_THRESHOLD_PARAMETER,
            WithDecryption=True
        )["Parameter"]["Value"]
    )

    return sum(
        1
        for product in products
        if product["stock_quantity"] <= threshold
    )

def load_live_dashboard_data():
    products = load_live_products()
    orders = load_live_orders()
    order_status_counts = load_live_order_status_counts()

    threshold = int(
        ssm.get_parameter(
            Name=LOW_STOCK_THRESHOLD_PARAMETER,
            WithDecryption=True
        )["Parameter"]["Value"]
    )

    low_stock_count = sum(
        1
        for product in products
        if product["stock_quantity"] <= threshold
    )

    total_orders = sum(order_status_counts.values())

    pending_processing_orders = sum(
        count
        for status, count in order_status_counts.items()
        if status in {"PENDING", "PROCESSING"}
    )

    return {
        "products": [
            {
                "Product ID": product["product_id"],
                "Product Name": product["product_name"],
                "Price": product["price"],
                "Current Stock": product["stock_quantity"],
                "Product Status": product["status"],
                "Low Stock": (
                    "YES"
                    if product["stock_quantity"] <= threshold
                    else "NO"
                )
            }
            for product in products
        ],
        "orders": [
            {
                "Order ID": order["order_id"],
                "Customer ID": order["customer_id"],
                "Created Time": order["created_at"],
                "Updated Time": order["updated_at"],
                "Order Status": order["status"],
                "Total Amount": order["total_amount"],
                "Order Item ID": order["order_item_id"],
                "Product ID": order["product_id"],
                "Quantity": order["quantity"],
                "Unit Price": order["unit_price"],
                "Subtotal": order["subtotal"],
                "Product Name": order["product_name"]
            }
            for order in orders
        ],
        "order_status_counts": order_status_counts,
        "low_stock_count": low_stock_count,
        "total_orders": total_orders,
        "pending_processing_orders": pending_processing_orders,
    }

def get_admin_token():
    response = ssm.get_parameter(
        Name=ADMIN_TOKEN_PARAMETER,
        WithDecryption=True
    )
    return response["Parameter"]["Value"]


REPORT_BUCKET = os.environ.get(
    "REPORT_BUCKET"
)

REPORT_PREFIX = os.environ.get(
    "REPORT_PREFIX",
    "reports/"
)

def get_latest_report_key():

    response = s3.list_objects_v2(
        Bucket=REPORT_BUCKET,
        Prefix=REPORT_PREFIX
    )

    objects = response.get("Contents", [])

    if not objects:
        raise RuntimeError("No reports found in S3.")

    csv_objects = [
        item
        for item in objects
        if item["Key"].lower().endswith(".csv")
    ]

    if not csv_objects:
        raise RuntimeError("No CSV reports found in S3.")

    latest = max(
        csv_objects,
        key=lambda item: item["LastModified"]
    )

    return latest["Key"]


def get_previous_reports():

    response = s3.list_objects_v2(
        Bucket=REPORT_BUCKET,
        Prefix=REPORT_PREFIX
    )

    objects = response.get("Contents", [])

    reports = []

    for item in objects:

        key = item["Key"]

        if not key.lower().endswith(".csv"):
            continue

        reports.append(
            {
                "key": key,
                "name": os.path.basename(key),
                "report_date": item["LastModified"].strftime(
                    "%Y-%m-%d"
                ),
                "last_modified": item["LastModified"].strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            }
        )

    reports.sort(
        key=lambda item: item["last_modified"],
        reverse=True
    )

    return reports


def get_report_content(report_key):

    response = s3.get_object(
        Bucket=REPORT_BUCKET,
        Key=report_key
    )

    return response["Body"].read().decode("utf-8")


def load_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    lines = list(
        csv.reader(
            io.StringIO(content)
        )
    )

    report_date = ""
    report_window = ""
    environment = ""

    for row in lines:

        if len(row) >= 2 and row[0] == "Report Date":
            report_date = row[1]

        elif len(row) >= 2 and row[0] == "Report Window":
            report_window = row[1]

        elif len(row) >= 2 and row[0] == "Environment":
            environment = row[1]


    order_columns = [
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


    product_columns = [
        "Product ID",
        "Product Name",
        "Price",
        "Current Stock",
        "Product Status",
        "Low Stock"
    ]


    orders = []
    products = []

    order_header_index = None
    product_header_index = None


    for index, row in enumerate(lines):

        if row == order_columns:
            order_header_index = index

        if row == product_columns:
            product_header_index = index


    if order_header_index is not None:

        start = order_header_index + 1

        end = product_header_index

        if end is None:
            end = len(lines)

        for row in lines[start:end]:

            if row and len(row) == len(order_columns):

                orders.append(
                    dict(
                        zip(
                            order_columns,
                            row
                        )
                    )
                )


    if product_header_index is not None:

        start = product_header_index + 1

        for row in lines[start:]:

            if row and len(row) == len(product_columns):

                products.append(
                    dict(
                        zip(
                            product_columns,
                            row
                        )
                    )
                )


    low_stock_count = sum(
        1
        for product in products
        if product["Low Stock"].upper() == "YES"
    )


    order_status_counts = Counter(
        order["Order Status"].upper()
        for order in orders
    )


    previous_reports = get_previous_reports()


    return {
        "report_key": key,
        "report_date": report_date,
        "report_window": report_window,
        "environment": environment,
        "orders": orders,
        "products": products,
        "order_columns": order_columns,
        "low_stock_count": low_stock_count,
        "order_status_counts": order_status_counts,
        "previous_reports": previous_reports
    }

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template(
            "login.html",
            error=None
        )

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if username != "admin":
        return render_template(
            "login.html",
            error="Invalid username or password."
        ), 401

    try:
        admin_token = get_admin_token()
    except Exception:
        app.logger.exception(
            "Unable to retrieve dashboard admin token"
        )

        return render_template(
            "login.html",
            error="Login service is unavailable."
        ), 500

    if password != admin_token:
        return render_template(
            "login.html",
            error="Invalid username or password."
        ), 401

    session["authenticated"] = True
    session["username"] = username

    return redirect(url_for("dashboard"))

@app.before_request
def require_login():
    if request.path == "/login" or request.path.startswith("/static/"):
        return

    if not session.get("authenticated"):
        return redirect(url_for("login"))

    return None

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    try:
        live_data = load_live_dashboard_data()

        report_data = {
            "report_date": None,
            "report_window": None,
            "report_key": None,
            "previous_reports": [],
        }

        try:
            report_data = load_report()
        except Exception:
            pass

        report_data.update(live_data)

        return render_template(
            "dashboard.html",
            error=None,
            environment=ENVIRONMENT,
            aws_region=os.environ.get("AWS_DEFAULT_REGION"),
            **report_data
        )

    except Exception as exc:
        app.logger.exception(
            "Unable to load dashboard data"
        )

        return render_template(
            "dashboard.html",
            error=str(exc)
        ), 500


@app.route("/report/view")
def view_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "inline"
        }
    )


@app.route("/report/download")
def download_report():

    key = get_latest_report_key()

    content = get_report_content(key)

    filename = os.path.basename(key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        }
    )


@app.route("/report/view/<path:report_key>")
def view_previous_report(report_key):

    content = get_report_content(report_key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "inline"
        }
    )


@app.route("/report/download/<path:report_key>")
def download_previous_report(report_key):

    content = get_report_content(report_key)

    filename = os.path.basename(report_key)

    return (
        content,
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        }
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )