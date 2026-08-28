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
    """Structured JSON logging — required by the milestone's review checklist."""
    logger.info(json.dumps(kwargs))


def get_db_connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        db=os.environ["DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor,
    )


def respond(status, body, request_id):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({**body, "request_id": request_id}, default=str),
    }


def handler(event, context):
    request_id = str(uuid.uuid4())[:8]
    method = event.get("requestContext", {}).get("http", {}).get("method")
    path = event.get("rawPath", "")

    log_json(request_id=request_id, event="request_received", method=method, path=path)

    # ---- this block is the "Lambda Authorizer" for a Function URL world ----
    if not authorize(event):
        log_json(request_id=request_id, event="auth_failed")
        return respond(
            401,
            {"success": False, "error": {"code": "UNAUTHORIZED", "message": "Missing or invalid token"}},
            request_id,
        )
    # --------------------------------------------------------------------

    try:
        if method == "POST" and path == "/products":
            return create_product(event, request_id)
        if method == "GET" and path.startswith("/products/"):
            return get_product(event, request_id)
        if method == "GET" and path == "/products":
            return list_products(event, request_id)
        if method == "PUT" and path.startswith("/products/"):
            return update_product(event, request_id)
        if method == "DELETE" and path.startswith("/products/"):
            return deactivate_product(event, request_id)

        return respond(404, {"success": False, "error": {"code": "NOT_FOUND", "message": "No matching route"}}, request_id)

    except Exception as e:
        log_json(request_id=request_id, event="unhandled_error", error=str(e))
        return respond(500, {"success": False, "error": {"code": "INTERNAL_ERROR", "message": "Unexpected error"}}, request_id)


def get_low_stock_threshold():
    param = ssm.get_parameter(Name=os.environ["LOW_STOCK_THRESHOLD_PARAM"])
    return int(param["Parameter"]["Value"])


def publish_low_stock_alert(product_id, stock_quantity, request_id):
    sns.publish(
        TopicArn=os.environ["LOW_STOCK_TOPIC_ARN"],
        Subject="CloudMart low stock alert",
        Message=f"Product {product_id} has only {stock_quantity} unit(s) left.",
    )
    eventbridge.put_events(
        Entries=[{
            "Source": "cloudmart.product",
            "DetailType": "LowStockEvents",
            "EventBusName": os.environ["EVENT_BUS_NAME"],
            "Detail": json.dumps({
                "event_id": request_id,
                "event_type": "LowStockEvents",
                "source": "cloudmart.product",
                "event_time": datetime.datetime.utcnow().isoformat() + "Z",
                "environment": os.environ["ENVIRONMENT"],
                "detail": {"product_id": product_id, "stock_quantity": stock_quantity},
            }),
        }]
    )
    log_json(request_id=request_id, event="low_stock_alert_published", product_id=product_id, stock_quantity=stock_quantity)


def create_product(event, request_id):
    body = json.loads(event.get("body") or "{}")
    required = ["product_name", "category_id", "price", "stock_quantity"]
    missing = [f for f in required if f not in body]
    if missing:
        return respond(400, {"success": False, "error": {"code": "MISSING_FIELDS", "message": f"Missing: {missing}"}}, request_id)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT category_id FROM categories WHERE category_id=%s AND status='ACTIVE'", (body["category_id"],))
            if not cur.fetchone():
                return respond(400, {"success": False, "error": {"code": "INVALID_CATEGORY", "message": f"category_id {body['category_id']} does not exist"}}, request_id)

            cur.execute(
                "INSERT INTO products (category_id, product_name, description, price, stock_quantity, status) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (body["category_id"], body["product_name"], body.get("description"), body["price"],
                 body["stock_quantity"], body.get("status", "ACTIVE")),
            )
            conn.commit()
            product_id = cur.lastrowid
    finally:
        conn.close()

    log_json(request_id=request_id, event="product_created", product_id=product_id)

    if body["stock_quantity"] <= get_low_stock_threshold():
        publish_low_stock_alert(product_id, body["stock_quantity"], request_id)

    return respond(201, {"success": True, "data": {"product_id": product_id, **body}}, request_id)


def get_product(event, request_id):
    product_id = event["pathParameters"]["productId"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE product_id=%s", (product_id,))
            product = cur.fetchone()
    finally:
        conn.close()

    if not product:
        return respond(404, {"success": False, "error": {"code": "PRODUCT_NOT_FOUND", "message": f"product_id {product_id} does not exist"}}, request_id)
    return respond(200, {"success": True, "data": product}, request_id)


def list_products(event, request_id):
    qs = event.get("queryStringParameters") or {}
    category_id = qs.get("category_id")
    status = qs.get("status", "ACTIVE")

    query = "SELECT * FROM products WHERE status=%s"
    params = [status]
    if category_id:
        query += " AND category_id=%s"
        params.append(category_id)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            products = cur.fetchall()
    finally:
        conn.close()

    return respond(200, {"success": True, "data": products}, request_id)


def update_product(event, request_id):
    product_id = event["pathParameters"]["productId"]
    body = json.loads(event.get("body") or "{}")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE product_id=%s", (product_id,))
            existing = cur.fetchone()
            if not existing:
                return respond(404, {"success": False, "error": {"code": "PRODUCT_NOT_FOUND", "message": f"product_id {product_id} does not exist"}}, request_id)

            new_stock = body.get("stock_quantity", existing["stock_quantity"])
            new_status = existing["status"]
            # zero-stock rule from Milestone 2 design: deactivate, never hard-delete
            if new_stock == 0:
                new_status = "INACTIVE"

            cur.execute(
                "UPDATE products SET product_name=%s, description=%s, category_id=%s, price=%s, "
                "stock_quantity=%s, status=%s, updated_at=NOW() WHERE product_id=%s",
                (
                    body.get("product_name", existing["product_name"]),
                    body.get("description", existing["description"]),
                    body.get("category_id", existing["category_id"]),
                    body.get("price", existing["price"]),
                    new_stock,
                    body.get("status", new_status),
                    product_id,
                ),
            )
            conn.commit()
    finally:
        conn.close()

    log_json(request_id=request_id, event="product_updated", product_id=product_id, new_stock=new_stock)

    if new_stock <= get_low_stock_threshold():
        publish_low_stock_alert(product_id, new_stock, request_id)

    return respond(200, {"success": True, "data": {"product_id": product_id, "stock_quantity": new_stock, "status": new_status}}, request_id)


def deactivate_product(event, request_id):
    product_id = event["pathParameters"]["productId"]
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM products WHERE product_id=%s", (product_id,))
            existing = cur.fetchone()
            if not existing:
                return respond(404, {"success": False, "error": {"code": "PRODUCT_NOT_FOUND", "message": f"product_id {product_id} does not exist"}}, request_id)
            if existing["status"] == "INACTIVE":
                return respond(409, {"success": False, "error": {"code": "PRODUCT_ALREADY_INACTIVE", "message": f"product_id {product_id} is already INACTIVE"}}, request_id)

            cur.execute("UPDATE products SET status='INACTIVE', updated_at=NOW() WHERE product_id=%s", (product_id,))
            conn.commit()
    finally:
        conn.close()

    log_json(request_id=request_id, event="product_deactivated", product_id=product_id)
    return {"statusCode": 204, "headers": {}, "body": ""}
