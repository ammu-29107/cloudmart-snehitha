import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")


DB_HOST_PARAM = os.environ["DB_HOST_PARAM"]
DB_NAME_PARAM = os.environ["DB_NAME_PARAM"]
DB_USER_PARAM = os.environ["DB_USER_PARAM"]
DB_PASSWORD_PARAM = os.environ["DB_PASSWORD_PARAM"]

ACCESS_TOKEN_LIFETIME_MINUTES = 60


def response(status_code, success, message=None, data=None):
    body = {
        "success": success
    }

    if message is not None:
        body["message"] = message

    if data is not None:
        body["data"] = data

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body, indent=2)
    }


def get_ssm_parameter(name, with_decryption=False):
    result = ssm.get_parameter(
        Name=name,
        WithDecryption=with_decryption
    )

    return result["Parameter"]["Value"]


def get_database_connection():
    host = get_ssm_parameter(DB_HOST_PARAM)
    db_name = get_ssm_parameter(DB_NAME_PARAM)
    user = get_ssm_parameter(DB_USER_PARAM)
    password = get_ssm_parameter(
        DB_PASSWORD_PARAM,
        with_decryption=True
    )

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=db_name,
        connect_timeout=10,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor
    )


def create_access_token(cur, customer_id):
    raw_token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=ACCESS_TOKEN_LIFETIME_MINUTES)
    ).replace(tzinfo=None)

    cur.execute(
        """
        INSERT INTO customer_access_tokens (
            customer_id,
            token_hash,
            expires_at
        )
        VALUES (
            %s,
            %s,
            %s
        )
        """,
        (
            customer_id,
            token_hash,
            expires_at
        )
    )

    return raw_token, expires_at


def handle_login(body):

    conn = None

    try:

        required_fields = [
            "email",
            "password"
        ]

        missing_fields = [
            field
            for field in required_fields
            if not body.get(field)
        ]

        if missing_fields:
            return response(
                400,
                False,
                "Missing required field(s): "
                + ", ".join(missing_fields)
            )

        email = body["email"].strip().lower()
        password = body["password"]

        password_bytes = password.encode("utf-8")

        if len(password_bytes) > 72:
            return response(
                401,
                False,
                "Invalid email or password"
            )

        conn = get_database_connection()

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    c.customer_id,
                    c.status,
                    cc.password_hash
                FROM customers c
                INNER JOIN customer_credentials cc
                    ON c.customer_id = cc.customer_id
                WHERE c.email = %s
                """,
                (email,)
            )

            customer = cur.fetchone()

            if not customer:
                return response(
                    401,
                    False,
                    "Invalid email or password"
                )

            if customer["status"] != "ACTIVE":
                return response(
                    401,
                    False,
                    "Invalid email or password"
                )

            stored_hash = customer["password_hash"]

            if not stored_hash:
                return response(
                    401,
                    False,
                    "Invalid email or password"
                )

            if not bcrypt.checkpw(
                password.encode("utf-8"),
                stored_hash.encode("utf-8")
            ):
                return response(
                    401,
                    False,
                    "Invalid email or password"
                )

            access_token, expires_at = create_access_token(
                cur,
                customer["customer_id"]
            )

            conn.commit()

            return response(
                200,
                True,
                data={
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_at": expires_at.isoformat() + "Z",
                    "customer_id": customer["customer_id"]
                }
            )

    except Exception:
        if conn is not None:
            conn.rollback()

        logger.exception("Customer login failed")

        return response(
            500,
            False,
            "Internal server error"
        )

    finally:

        if conn is not None:
            conn.close()


def handle_password_change(event, body):

    conn = None

    try:

        request_context = (
            event.get("requestContext")
            or {}
        )

        authorizer_context = (
            request_context.get("authorizer")
            or {}
        )

        role = authorizer_context.get("role")
        customer_id = authorizer_context.get("customer_id")

        if role != "CUSTOMER" or customer_id is None:
            return response(
                403,
                False,
                "Customer authentication is required"
            )

        required_fields = [
            "current_password",
            "new_password"
        ]

        missing_fields = [
            field
            for field in required_fields
            if not body.get(field)
        ]

        if missing_fields:
            return response(
                400,
                False,
                "Missing required field(s): "
                + ", ".join(missing_fields)
            )

        current_password = body["current_password"]
        new_password = body["new_password"]

        current_password_bytes = current_password.encode("utf-8")
        new_password_bytes = new_password.encode("utf-8")

        if len(new_password_bytes) < 8:
            return response(
                400,
                False,
                "New password must be at least 8 characters long"
            )

        if len(new_password_bytes) > 72:
            return response(
                400,
                False,
                "New password must not exceed 72 bytes"
            )

        if len(current_password_bytes) > 72:
            return response(
                401,
                False,
                "Current password is incorrect"
            )

        conn = get_database_connection()

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT password_hash
                FROM customer_credentials
                WHERE customer_id = %s
                """,
                (customer_id,)
            )

            credential = cur.fetchone()

            if not credential or not credential["password_hash"]:
                return response(
                    401,
                    False,
                    "Current password is incorrect"
                )

            if not bcrypt.checkpw(
                current_password_bytes,
                credential["password_hash"].encode("utf-8")
            ):
                return response(
                    401,
                    False,
                    "Current password is incorrect"
                )

            new_password_hash = bcrypt.hashpw(
                new_password_bytes,
                bcrypt.gensalt()
            ).decode("utf-8")

            cur.execute(
                """
                UPDATE customer_credentials
                SET
                    password_hash = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE customer_id = %s
                """,
                (
                    new_password_hash,
                    customer_id
                )
            )

            cur.execute(
                """
                UPDATE customer_access_tokens
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE customer_id = %s
                  AND revoked_at IS NULL
                """,
                (customer_id,)
            )

            conn.commit()

        logger.info(
            json.dumps(
                {
                    "event": "customer_password_changed",
                    "customer_id": customer_id
                }
            )
        )

        return response(
            200,
            True,
            "Password changed successfully. Please log in again."
        )

    except Exception:

        if conn is not None:
            conn.rollback()

        logger.exception(
            "Customer password change failed"
        )

        return response(
            500,
            False,
            "Internal server error"
        )

    finally:

        if conn is not None:
            conn.close()


def lambda_handler(event, context):

    conn = None

    try:

        path = (
            event.get("rawPath")
            or event.get("path")
            or ""
        )

        method = (
            (event.get("requestContext") or {})
            .get("http", {})
            .get("method")
            or event.get("httpMethod")
            or ""
        ).upper()

        body = event.get("body")

        if not body:
            return response(
                400,
                False,
                "Request body is required"
            )

        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return response(
                400,
                False,
                "Request body must be valid JSON"
            )

        if method == "POST" and path == "/login":
            return handle_login(body)

        if (
            method == "PATCH"
            and path == "/customers/me/password"
        ):
            return handle_password_change(
                event,
                body
            )

        if not (method == "POST" and path == "/customers"):
            return response(
                404,
                False,
                "Requested route was not found"
            )

        required_fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "password"
        ]

        missing_fields = [
            field
            for field in required_fields
            if not body.get(field)
        ]

        if missing_fields:
            return response(
                400,
                False,
                "Missing required field(s): "
                + ", ".join(missing_fields)
            )

        first_name = body["first_name"].strip()
        last_name = body["last_name"].strip()
        email = body["email"].strip().lower()
        phone = body["phone"].strip()
        password = body["password"]

        password_bytes = password.encode("utf-8")

        if len(password_bytes) < 8:
            return response(
                400,
                False,
                "Password must be at least 8 characters long"
            )

        if len(password_bytes) > 72:
            return response(
                400,
                False,
                "Password must not exceed 72 bytes"
            )

        password_hash = bcrypt.hashpw(
            password_bytes,
            bcrypt.gensalt()
        ).decode("utf-8")

        conn = get_database_connection()

        with conn.cursor() as cur:

            # ------------------------------------------------
            # Check whether the email already exists
            # ------------------------------------------------

            cur.execute(
                """
                SELECT customer_id
                FROM customers
                WHERE email = %s
                """,
                (email,)
            )

            existing_customer = cur.fetchone()

            if existing_customer:
                return response(
                    409,
                    False,
                    "A customer with this email already exists"
                )

            # ------------------------------------------------
            # Create customer
            # ------------------------------------------------

            cur.execute(
                """
                INSERT INTO customers (
                    first_name,
                    last_name,
                    email,
                    phone,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    'ACTIVE'
                )
                """,
                (
                    first_name,
                    last_name,
                    email,
                    phone
                )
            )

            customer_id = cur.lastrowid

            # ------------------------------------------------
            # Create customer credential record
            # ------------------------------------------------

            cur.execute(
                """
                INSERT INTO customer_credentials (
                    customer_id,
                    password_hash
                )
                VALUES (
                    %s,
                    %s
                )
                """,
                (
                    customer_id,
                    password_hash
                )
            )

            conn.commit()

        logger.info(
            json.dumps({
                "event": "customer_created",
                "customer_id": customer_id
            })
        )

        return response(
            201,
            True,
            data={
                "customer_id": customer_id,
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "status": "ACTIVE"
            }
        )

    except pymysql.err.IntegrityError:

        if conn is not None:
            conn.rollback()

        logger.exception("Customer creation failed")

        return response(
            409,
            False,
            "Customer could not be created because of a database constraint"
        )

    except Exception:

        if conn is not None:
            conn.rollback()

        logger.exception("Unexpected customer creation error")

        return response(
            500,
            False,
            "Internal server error"
        )

    finally:

        if conn is not None:
            conn.close()