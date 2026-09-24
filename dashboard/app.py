import csv
import io
import os
from collections import Counter

import boto3
from flask import Flask, render_template_string, url_for


app = Flask(__name__)

s3 = boto3.client("s3")


REPORT_BUCKET = os.environ.get(
    "REPORT_BUCKET",
    "cloudmart-dev-reports-790574019399"
)

REPORT_PREFIX = os.environ.get(
    "REPORT_PREFIX",
    "reports/"
)


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>CloudMart Operations Dashboard</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            font-family: Arial, Helvetica, sans-serif;
            background: #f4f6f8;
            color: #1f2937;
        }

        .topbar {
            background: #111827;
            color: white;
            padding: 22px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 20px;
        }

        .brand h1 {
            margin: 0;
            font-size: 25px;
        }

        .brand p {
            margin: 5px 0 0;
            color: #cbd5e1;
            font-size: 13px;
        }

        .environment {
            background: #1f2937;
            border: 1px solid #374151;
            padding: 8px 14px;
            border-radius: 20px;
            font-size: 13px;
            color: #d1fae5;
        }

        .container {
            max-width: 1450px;
            margin: 0 auto;
            padding: 30px 35px 50px;
        }

        .error {
            background: #fee2e2;
            border: 1px solid #fecaca;
            color: #991b1b;
            padding: 18px;
            border-radius: 12px;
            margin-bottom: 25px;
        }

        .report-header {
            background: white;
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 25px;
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.06);
        }

        .report-header-top {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 20px;
            flex-wrap: wrap;
        }

        .report-header h2 {
            margin: 0 0 8px;
            font-size: 21px;
        }

        .report-header p {
            margin: 6px 0;
            color: #64748b;
            font-size: 14px;
        }

        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .button {
            display: inline-block;
            padding: 10px 16px;
            border-radius: 9px;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            border: none;
        }

        .button-primary {
            background: #2563eb;
            color: white;
        }

        .button-primary:hover {
            background: #1d4ed8;
        }

        .button-secondary {
            background: #e2e8f0;
            color: #334155;
        }

        .button-secondary:hover {
            background: #cbd5e1;
        }

        .cards {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 18px;
            margin-bottom: 30px;
        }

        .card {
            background: white;
            padding: 22px;
            border-radius: 15px;
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.06);
        }

        .card-label {
            color: #64748b;
            font-size: 13px;
            font-weight: 600;
            margin-bottom: 10px;
        }

        .card-value {
            font-size: 30px;
            font-weight: 700;
            margin: 0;
            color: #111827;
        }

        .card-note {
            margin-top: 8px;
            font-size: 12px;
            color: #94a3b8;
        }

        .section {
            background: white;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 28px;
            box-shadow: 0 3px 12px rgba(15, 23, 42, 0.06);
        }

        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }

        .section h2 {
            margin: 0;
            font-size: 19px;
        }

        .section-description {
            color: #64748b;
            font-size: 13px;
            margin-top: 5px;
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 14px;
        }

        .status-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 11px;
            padding: 16px;
        }

        .status-name {
            font-size: 12px;
            color: #64748b;
            font-weight: 600;
        }

        .status-count {
            font-size: 24px;
            font-weight: 700;
            margin-top: 5px;
        }

        .table-wrapper {
            overflow-x: auto;
            border: 1px solid #e5e7eb;
            border-radius: 11px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 800px;
        }

        th {
            background: #f8fafc;
            color: #475569;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            padding: 13px 14px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
            white-space: nowrap;
        }

        td {
            padding: 13px 14px;
            border-bottom: 1px solid #eef2f7;
            font-size: 13px;
            color: #334155;
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: #f8fafc;
        }

        .badge {
            display: inline-block;
            padding: 5px 9px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
        }

        .badge-success {
            background: #dcfce7;
            color: #166534;
        }

        .badge-warning {
            background: #fef3c7;
            color: #92400e;
        }

        .badge-danger {
            background: #fee2e2;
            color: #991b1b;
        }

        .badge-neutral {
            background: #e2e8f0;
            color: #475569;
        }

        .low-stock-row td {
            background: #fff7ed;
        }

        .empty {
            padding: 30px;
            text-align: center;
            color: #94a3b8;
            font-size: 14px;
        }

        .reports-list {
            display: grid;
            gap: 12px;
        }

        .previous-report {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 15px;
            padding: 15px 17px;
            border: 1px solid #e2e8f0;
            border-radius: 11px;
            background: #f8fafc;
        }

        .previous-report-name {
            font-weight: 600;
            font-size: 14px;
            color: #334155;
        }

        .previous-report-date {
            font-size: 12px;
            color: #94a3b8;
            margin-top: 4px;
        }

        .previous-report-actions {
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }

        .footer {
            text-align: center;
            color: #94a3b8;
            font-size: 12px;
            padding-top: 10px;
        }

        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(15, 23, 42, 0.65);
            padding: 35px;
            align-items: center;
            justify-content: center;
        }

        .modal-content {
            background: white;
            width: 100%;
            max-width: 1100px;
            max-height: 85vh;
            overflow: auto;
            border-radius: 16px;
            padding: 25px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
        }

        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .modal-header h2 {
            margin: 0;
        }

        .close {
            font-size: 28px;
            cursor: pointer;
            color: #64748b;
        }

        @media (max-width: 1000px) {
            .cards {
                grid-template-columns: repeat(2, 1fr);
            }

            .status-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (max-width: 650px) {
            .topbar {
                padding: 20px;
            }

            .container {
                padding: 20px 15px 40px;
            }

            .cards,
            .status-grid {
                grid-template-columns: 1fr;
            }

            .modal {
                padding: 15px;
            }

            .previous-report {
                align-items: flex-start;
                flex-direction: column;
            }
        }
    </style>
</head>

<body>

<div class="topbar">

    <div class="brand">
        <h1>CloudMart Operations</h1>
        <p>Daily inventory and order reporting dashboard</p>
    </div>

    <div class="environment">
        Environment: {{ environment or "Unknown" }}
    </div>

</div>

<div class="container">

{% if error %}

    <div class="error">
        <strong>Unable to load dashboard data.</strong>
        <div style="margin-top: 6px;">{{ error }}</div>
    </div>

{% else %}

    <div class="report-header">

        <div class="report-header-top">

            <div>

                <h2>Latest Daily Report</h2>

                <p>
                    <strong>Report Date:</strong>
                    {{ report_date }}
                </p>

                <p>
                    <strong>Report Window:</strong>
                    {{ report_window }}
                </p>

                <p>
                    <strong>Report File:</strong>
                    {{ report_key }}
                </p>

            </div>

            <div class="actions">

                <a
                    class="button button-secondary"
                    href="{{ url_for('view_report') }}"
                    target="_blank"
                >
                    View Report
                </a>

                <a
                    class="button button-primary"
                    href="{{ url_for('download_report') }}"
                >
                    Download Report
                </a>

            </div>

        </div>

    </div>


    <div class="cards">

        <div class="card">

            <div class="card-label">
                TOTAL PRODUCTS
            </div>

            <p class="card-value">
                {{ products|length }}
            </p>

            <div class="card-note">
                Products in latest report
            </div>

        </div>


        <div class="card">

            <div class="card-label">
                LOW STOCK
            </div>

            <p class="card-value">
                {{ low_stock_count }}
            </p>

            <div class="card-note">
                Products below threshold
            </div>

        </div>


        <div class="card">

            <div class="card-label">
                ORDER ITEMS
            </div>

            <p class="card-value">
                {{ orders|length }}
            </p>

            <div class="card-note">
                Order item records
            </div>

        </div>


        <div class="card">

            <div class="card-label">
                REPORT STATUS
            </div>

            {% if products or orders %}

                <p class="card-value" style="font-size: 22px;">
                    Ready
                </p>

                <div class="card-note">
                    Latest report loaded successfully
                </div>

            {% else %}

                <p class="card-value" style="font-size: 22px;">
                    Empty
                </p>

                <div class="card-note">
                    No business records found
                </div>

            {% endif %}

        </div>

    </div>


    <div class="section">

        <div class="section-header">

            <div>

                <h2>Order Status Overview</h2>

                <div class="section-description">
                    Current order statuses included in the latest daily report.
                </div>

            </div>

        </div>


        <div class="status-grid">

            {% for status in ["COMPLETED", "PENDING", "PROCESSING", "FAILED"] %}

                <div class="status-card">

                    <div class="status-name">
                        {{ status }}
                    </div>

                    <div class="status-count">
                        {{ order_status_counts.get(status, 0) }}
                    </div>

                </div>

            {% endfor %}

        </div>

    </div>


    <div class="section">

        <div class="section-header">

            <div>

                <h2>Product Inventory</h2>

                <div class="section-description">
                    Current product stock and availability from the latest report.
                </div>

            </div>

        </div>


        {% if products %}

        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>
                        <th>Product ID</th>
                        <th>Product Name</th>
                        <th>Price</th>
                        <th>Current Stock</th>
                        <th>Status</th>
                        <th>Stock Alert</th>
                    </tr>

                </thead>

                <tbody>

                {% for product in products %}

                    <tr
                        {% if product["Low Stock"].upper() == "YES" %}
                            class="low-stock-row"
                        {% endif %}
                    >

                        <td>
                            {{ product["Product ID"] }}
                        </td>

                        <td>
                            <strong>
                                {{ product["Product Name"] }}
                            </strong>
                        </td>

                        <td>
                            {{ product["Price"] }}
                        </td>

                        <td>
                            <strong>
                                {{ product["Current Stock"] }}
                            </strong>
                        </td>

                        <td>

                            {% if product["Product Status"].upper() == "ACTIVE" %}

                                <span class="badge badge-success">
                                    ACTIVE
                                </span>

                            {% else %}

                                <span class="badge badge-neutral">
                                    {{ product["Product Status"] }}
                                </span>

                            {% endif %}

                        </td>

                        <td>

                            {% if product["Low Stock"].upper() == "YES" %}

                                <span class="badge badge-warning">
                                    LOW STOCK
                                </span>

                            {% else %}

                                <span class="badge badge-success">
                                    NORMAL
                                </span>

                            {% endif %}

                        </td>

                    </tr>

                {% endfor %}

                </tbody>

            </table>

        </div>

        {% else %}

            <div class="empty">
                No products were present in the latest report.
            </div>

        {% endif %}

    </div>


    <div class="section">

        <div class="section-header">

            <div>

                <h2>Order Item Details</h2>

                <div class="section-description">
                    Detailed order and product information from the latest report.
                </div>

            </div>


            {% if orders %}

                <button
                    class="button button-primary"
                    onclick="openOrdersModal()"
                >
                    Open Detailed View
                </button>

            {% endif %}

        </div>


        {% if orders %}

        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>
                        <th>Order ID</th>
                        <th>Customer ID</th>
                        <th>Created</th>
                        <th>Status</th>
                        <th>Total Amount</th>
                        <th>Product</th>
                        <th>Quantity</th>
                        <th>Subtotal</th>
                    </tr>

                </thead>

                <tbody>

                {% for order in orders %}

                    <tr>

                        <td>
                            <strong>
                                #{{ order["Order ID"] }}
                            </strong>
                        </td>

                        <td>
                            {{ order["Customer ID"] }}
                        </td>

                        <td>
                            {{ order["Created Time"] }}
                        </td>

                        <td>

                            {% if order["Order Status"].upper() == "COMPLETED" %}

                                <span class="badge badge-success">
                                    COMPLETED
                                </span>

                            {% elif order["Order Status"].upper() == "FAILED" %}

                                <span class="badge badge-danger">
                                    FAILED
                                </span>

                            {% elif order["Order Status"].upper() in ["PENDING", "PROCESSING"] %}

                                <span class="badge badge-warning">
                                    {{ order["Order Status"] }}
                                </span>

                            {% else %}

                                <span class="badge badge-neutral">
                                    {{ order["Order Status"] }}
                                </span>

                            {% endif %}

                        </td>

                        <td>
                            {{ order["Total Amount"] }}
                        </td>

                        <td>
                            {{ order["Product Name"] }}
                        </td>

                        <td>
                            {{ order["Quantity"] }}
                        </td>

                        <td>
                            {{ order["Subtotal"] }}
                        </td>

                    </tr>

                {% endfor %}

                </tbody>

            </table>

        </div>

        {% else %}

            <div class="empty">
                No order items were present in the latest report.
            </div>

        {% endif %}

    </div>


    <div class="section">

        <div class="section-header">

            <div>

                <h2>Previous Reports</h2>

                <div class="section-description">
                    Reports currently available in the CloudMart S3 report bucket.
                </div>

            </div>

        </div>


        {% if previous_reports %}

        <div class="reports-list">

            {% for report in previous_reports %}

                <div class="previous-report">

                    <div>

                        <div class="previous-report-name">
                            {{ report["name"] }}
                        </div>

                        <div class="previous-report-date">
                            Uploaded: {{ report["last_modified"] }}
                        </div>

                    </div>


                    <div class="previous-report-actions">

                        <a
                            class="button button-secondary"
                            href="{{ url_for('view_previous_report', report_key=report['key']) }}"
                            target="_blank"
                        >
                            View
                        </a>

                        <a
                            class="button button-primary"
                            href="{{ url_for('download_previous_report', report_key=report['key']) }}"
                        >
                            Download
                        </a>

                    </div>

                </div>

            {% endfor %}

        </div>

        {% else %}

            <div class="empty">
                No previous reports found.
            </div>

        {% endif %}

    </div>


    <div class="footer">
        CloudMart Operations Dashboard · Reports stored in Amazon S3
    </div>

{% endif %}

</div>


{% if not error and orders %}

<div id="ordersModal" class="modal">

    <div class="modal-content">

        <div class="modal-header">

            <h2>Detailed Order Information</h2>

            <span
                class="close"
                onclick="closeOrdersModal()"
            >
                &times;
            </span>

        </div>


        <div class="table-wrapper">

            <table>

                <thead>

                    <tr>

                        {% for column in order_columns %}

                            <th>
                                {{ column }}
                            </th>

                        {% endfor %}

                    </tr>

                </thead>


                <tbody>

                {% for order in orders %}

                    <tr>

                        {% for column in order_columns %}

                            <td>
                                {{ order[column] }}
                            </td>

                        {% endfor %}

                    </tr>

                {% endfor %}

                </tbody>

            </table>

        </div>

    </div>

</div>


<script>

function openOrdersModal() {
    document.getElementById("ordersModal").style.display = "flex";
}


function closeOrdersModal() {
    document.getElementById("ordersModal").style.display = "none";
}


window.onclick = function(event) {

    const modal = document.getElementById("ordersModal");

    if (event.target === modal) {
        modal.style.display = "none";
    }

};

</script>

{% endif %}


</body>
</html>
"""


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


@app.route("/")
def dashboard():

    try:

        data = load_report()

        return render_template_string(
            HTML,
            error=None,
            **data
        )

    except Exception as exc:

        return render_template_string(
            HTML,
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