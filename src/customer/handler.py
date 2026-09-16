import json
import logging
import os
import secrets

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)


ssm = boto3.client("ssm")


DB_HOST_PARAM = os.environ["DB_HOST_PARAM"]
DB_NAME_PARAM = os.environ["DB_NAME_PARAM"]
DB_USER_PARAM = os.environ["DB_USER_PARAM"]
DB_PASSWORD_PARAM = os.environ["DB_PASSWORD_PARAM"]


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
        autocommit=False
    )


def lambda_handler(event, context):

    conn = None

    try:

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

        required_fields = [
            "first_name",
            "last_name",
            "email",
            "phone"
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
        email = body["email"].strip()
        phone = body["phone"].strip()

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
            # Generate and store customer credential
            # ------------------------------------------------

            credential_id = None

            for _ in range(3):

                candidate_credential_id = (
                    f"cm-customer-{customer_id}-"
                    f"{secrets.token_urlsafe(24)}"
                )

                try:

                    cur.execute(
                        """
                        INSERT INTO customer_credentials (
                            credential_id,
                            customer_id
                        )
                        VALUES (
                            %s,
                            %s
                        )
                        """,
                        (
                            candidate_credential_id,
                            customer_id
                        )
                    )

                    credential_id = candidate_credential_id
                    break

                except pymysql.err.IntegrityError as e:

                    # A credential collision is extraordinarily unlikely,
                    # but the UNIQUE constraint protects us if it ever happens.
                    if e.args and e.args[0] == 1062:
                        continue

                    raise

            if credential_id is None:
                raise RuntimeError(
                    "Unable to generate a unique customer credential"
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
                "status": "ACTIVE",
                "credentialId": credential_id
            }
        )

    except pymysql.err.IntegrityError as e:

        if conn is not None:
            conn.rollback()

        logger.exception("Customer creation failed")

        return response(
            409,
            False,
            "Customer could not be created because of a database constraint"
        )

    except Exception as e:

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