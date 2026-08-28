"""
CloudMart Schema Apply Lambda

This Lambda runs inside the VPC so it can connect to the private RDS
database.

GitHub Actions invokes this Lambda using the AWS Lambda control-plane
API. The GitHub runner does not need direct network access to RDS.

Database connection details are stored in AWS Systems Manager
Parameter Store.

The schema is idempotent:
- CREATE TABLE IF NOT EXISTS
- INSERT IGNORE

Therefore, this Lambda can safely be executed on every deployment.
"""

import json
import logging
import os

import boto3
import pymysql


logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")


# ============================================================
# SSM HELPER
# ============================================================

def get_ssm_parameter(name, decrypt=False):

    response = ssm.get_parameter(
        Name=name,
        WithDecryption=decrypt
    )

    return response["Parameter"]["Value"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

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
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
        autocommit=False
    )


# ============================================================
# DATABASE SCHEMA
# ============================================================

DDL_STATEMENTS = [

    """
    CREATE TABLE IF NOT EXISTS customers (
      customer_id INT AUTO_INCREMENT PRIMARY KEY,
      first_name VARCHAR(100) NOT NULL,
      last_name VARCHAR(100) NOT NULL,
      email VARCHAR(255) NOT NULL UNIQUE,
      phone VARCHAR(20),
      status ENUM('ACTIVE','INACTIVE')
        NOT NULL DEFAULT 'ACTIVE'
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS addresses (
      address_id INT AUTO_INCREMENT PRIMARY KEY,
      customer_id INT NOT NULL,
      address_line1 VARCHAR(255) NOT NULL,
      address_line2 VARCHAR(255),
      city VARCHAR(100) NOT NULL,
      state VARCHAR(100) NOT NULL,
      postal_code VARCHAR(20) NOT NULL,
      country VARCHAR(100) NOT NULL,
      is_default BOOLEAN NOT NULL DEFAULT FALSE,

      FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS categories (
      category_id INT AUTO_INCREMENT PRIMARY KEY,
      category_name VARCHAR(100) NOT NULL UNIQUE,
      description VARCHAR(500),
      status ENUM('ACTIVE','INACTIVE')
        NOT NULL DEFAULT 'ACTIVE'
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS products (
      product_id INT AUTO_INCREMENT PRIMARY KEY,
      category_id INT NOT NULL,
      product_name VARCHAR(200) NOT NULL,
      description TEXT,
      price DECIMAL(10,2) NOT NULL,
      stock_quantity INT NOT NULL DEFAULT 0,
      status ENUM('ACTIVE','INACTIVE')
        NOT NULL DEFAULT 'ACTIVE',

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

      FOREIGN KEY (category_id)
        REFERENCES categories(category_id),

      INDEX idx_products_category (category_id),
      INDEX idx_products_status (status)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS orders (
      order_id INT AUTO_INCREMENT PRIMARY KEY,
      customer_id INT NOT NULL,
      shipping_address_id INT NOT NULL,
      billing_address_id INT NOT NULL,

      status ENUM(
        'PENDING',
        'PROCESSING',
        'COMPLETED',
        'CANCELLED',
        'FAILED'
      ) NOT NULL,

      total_amount DECIMAL(10,2) NOT NULL,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,

      FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

      FOREIGN KEY (shipping_address_id)
        REFERENCES addresses(address_id),

      FOREIGN KEY (billing_address_id)
        REFERENCES addresses(address_id),

      INDEX idx_orders_customer_status
        (customer_id, status)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS order_items (
      order_item_id INT AUTO_INCREMENT PRIMARY KEY,
      order_id INT NOT NULL,
      product_id INT NOT NULL,
      quantity INT NOT NULL,
      unit_price DECIMAL(10,2) NOT NULL,
      subtotal DECIMAL(10,2) NOT NULL,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

      FOREIGN KEY (product_id)
        REFERENCES products(product_id),

      INDEX idx_order_items_order (order_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS order_status_history (
      history_id INT AUTO_INCREMENT PRIMARY KEY,
      order_id INT NOT NULL,

      previous_status ENUM(
        'PENDING',
        'PROCESSING',
        'COMPLETED',
        'CANCELLED',
        'FAILED'
      ),

      new_status ENUM(
        'PENDING',
        'PROCESSING',
        'COMPLETED',
        'CANCELLED',
        'FAILED'
      ) NOT NULL,

      changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

      INDEX idx_history_order (order_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS inventory_transactions (
      transaction_id INT AUTO_INCREMENT PRIMARY KEY,
      product_id INT NOT NULL,
      order_id INT NULL,
      change_quantity INT NOT NULL,

      transaction_type ENUM(
        'DEDUCTION',
        'RESTOCK',
        'CANCELLATION_RESTORE'
      ) NOT NULL,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      FOREIGN KEY (product_id)
        REFERENCES products(product_id),

      FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

      INDEX idx_inventory_product (product_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
      idempotency_key VARCHAR(64) PRIMARY KEY,
      order_id INT NOT NULL,

      status ENUM(
        'IN_PROGRESS',
        'COMPLETED'
      ) NOT NULL,

      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

      FOREIGN KEY (order_id)
        REFERENCES orders(order_id)
    )
    """
]


# ============================================================
# SAMPLE DATA
# ============================================================

SAMPLE_DATA_STATEMENTS = [

    """
    INSERT IGNORE INTO categories
      (
        category_id,
        category_name,
        description,
        status
      )
    VALUES
      (
        1,
        'Electronics',
        'Electronic gadgets and accessories',
        'ACTIVE'
      )
    """,

    """
    INSERT IGNORE INTO products
      (
        product_id,
        category_id,
        product_name,
        description,
        price,
        stock_quantity,
        status
      )
    VALUES
      (
        1,
        1,
        'Wireless Mouse',
        '2.4GHz wireless mouse',
        799.00,
        45,
        'ACTIVE'
      ),
      (
        2,
        1,
        'USB-C Hub',
        '7-in-1 USB-C hub',
        1299.00,
        12,
        'ACTIVE'
      ),
      (
        3,
        1,
        'Mechanical Keyboard',
        'RGB mechanical keyboard',
        3499.00,
        8,
        'ACTIVE'
      )
    """
]


# ============================================================
# LAMBDA HANDLER
# ============================================================

def handler(event, context):

    request_id = context.aws_request_id

    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "event": "schema_apply_started"
            }
        )
    )

    conn = None
    applied = []

    try:

        conn = get_db_connection()

        with conn.cursor() as cur:

            # ------------------------------------------------
            # CREATE TABLES
            # ------------------------------------------------

            for index, statement in enumerate(
                DDL_STATEMENTS,
                start=1
            ):

                cur.execute(statement)

                applied.append(
                    f"DDL_{index}"
                )

            # ------------------------------------------------
            # INSERT SAMPLE DATA
            # ------------------------------------------------

            for statement in SAMPLE_DATA_STATEMENTS:

                cur.execute(statement)

        conn.commit()

        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "schema_apply_completed",
                    "tables_applied": len(
                        DDL_STATEMENTS
                    )
                }
            )
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "success": True,
                    "tables_applied": len(
                        DDL_STATEMENTS
                    ),
                    "sample_data_applied": True,
                    "request_id": request_id
                }
            )
        }

    except Exception as exc:

        if conn:

            try:
                conn.rollback()
            except Exception:
                pass

        logger.error(
            json.dumps(
                {
                    "request_id": request_id,
                    "event": "schema_apply_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "applied_so_far": applied
                }
            )
        )

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "applied_so_far": applied,
                    "request_id": request_id
                }
            )
        }

    finally:

        if conn:

            conn.close()