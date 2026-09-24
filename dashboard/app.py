import csv
import io
import os

import boto3
from flask import Flask, render_template_string


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
<html>
<head>
    <title>CloudMart Operations Dashboard</title>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 30px;
            background: #f5f6f8;
        }

        h1 {
            margin-bottom: 5px;
        }

        .summary {
            background: white;
            padding: 20px;
            margin: 20px 0;
            border-radius: 8px;
        }

        .cards {
            display: flex;
            gap: 15px;
            margin: 20px 0;
        }

        .card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            min-width: 180px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            margin-bottom: 30px;
        }

        th, td {
            padding: 10px;
            border: 1px solid #ddd;
            text-align: left;
        }

        th {
            background: #eeeeee;
        }

        .low-stock {
            font-weight: bold;
        }

        .error {
            background: #ffe5e5;
            padding: 15px;
            border-radius: 8px;
        }
    </style>
</head>

<body>

<h1>CloudMart Operations Dashboard</h1>

{% if error %}

<div class="error">
    <strong>Error:</strong> {{ error }}
</div>

{% else %}

<div class="summary">
    <p><strong>Report Date:</strong> {{ report_date }}</p>
    <p><strong>Report Window:</strong> {{ report_window }}</p>
    <p><strong>Environment:</strong> {{ environment }}</p>
    <p><strong>Report File:</strong> {{ report_key }}</p>
</div>

<div class="cards">
    <div class="card">
        <strong>Total Products</strong>
        <h2>{{ products|length }}</h2>
    </div>

    <div class="card">
        <strong>Low Stock Products</strong>
        <h2>{{ low_stock_count }}</h2>
    </div>

    <div class="card">
        <strong>Order Items</strong>
        <h2>{{ orders|length }}</h2>
    </div>
</div>

<h2>Product Inventory</h2>

<table>
    <tr>
        <th>Product ID</th>
        <th>Product Name</th>
        <th>Price</th>
        <th>Current Stock</th>
        <th>Status</th>
        <th>Low Stock</th>
    </tr>

    {% for product in products %}
    <tr>
        <td>{{ product["Product ID"] }}</td>
        <td>{{ product["Product Name"] }}</td>
        <td>{{ product["Price"] }}</td>
        <td>{{ product["Current Stock"] }}</td>
        <td>{{ product["Product Status"] }}</td>
        <td class="{% if product["Low Stock"] == "YES" %}low-stock{% endif %}">
            {{ product["Low Stock"] }}
        </td>
    </tr>
    {% endfor %}
</table>

<h2>Order Item Details</h2>

{% if orders %}

<table>
    <tr>
        {% for column in order_columns %}
        <th>{{ column }}</th>
        {% endfor %}
    </tr>

    {% for order in orders %}
    <tr>
        {% for column in order_columns %}
        <td>{{ order[column] }}</td>
        {% endfor %}
    </tr>
    {% endfor %}
</table>

{% else %}

<p>No order items were present in the latest report.</p>

{% endif %}

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

    latest = max(
        objects,
        key=lambda item: item["LastModified"]
    )

    return latest["Key"]


def load_report():
    key = get_latest_report_key()

    response = s3.get_object(
        Bucket=REPORT_BUCKET,
        Key=key
    )

    content = response["Body"].read().decode("utf-8")

    lines = list(csv.reader(io.StringIO(content)))

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
                    dict(zip(order_columns, row))
                )

    if product_header_index is not None:
        start = product_header_index + 1

        for row in lines[start:]:
            if row and len(row) == len(product_columns):
                products.append(
                    dict(zip(product_columns, row))
                )

    low_stock_count = sum(
        1 for product in products
        if product["Low Stock"].upper() == "YES"
    )

    return {
        "report_key": key,
        "report_date": report_date,
        "report_window": report_window,
        "environment": environment,
        "orders": orders,
        "products": products,
        "order_columns": order_columns,
        "low_stock_count": low_stock_count
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


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )