"""
Runs inside the VPC.

The GitHub Actions runner invokes this Lambda through the AWS control
plane. The Lambda itself runs inside the VPC and connects to the private
RDS database.

Database connection details are retrieved from AWS Systems Manager
Parameter Store at runtime.

The password is stored as a SecureString and retrieved with decryption.

Every DDL statement uses IF NOT EXISTS and sample-data inserts use
INSERT IGNORE, so this Lambda is safe to invoke repeatedly.
"""

import os
import json

import boto3
import pymysql


ssm = boto3.client("ssm")


DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS customers (
      customer_id INT AUTO_INCREMENT PRIMARY KEY,
      first_name VARCHAR(100) NOT NULL,
      last_name VARCHAR(100) NOT NULL,
      email VARCHAR(255) NOT NULL UNIQUE,
      phone VARCHAR(20),
      status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'
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
      FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS categories (
      category_id INT AUTO_INCREMENT PRIMARY KEY,
      category_name VARCHAR(100) NOT NULL UNIQUE,
      description VARCHAR(500),
      status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE'
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
      status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      FOREIGN KEY (category_id) REFERENCES categories(category_id),
      INDEX idx_products_category (category_id),
      INDEX idx_products_status (status),
      CONSTRAINT chk_products_stock_nonnegative
        CHECK (stock_quantity >= 0)
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
      FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
      FOREIGN KEY (shipping_address_id) REFERENCES addresses(address_id),
      FOREIGN KEY (billing_address_id) REFERENCES addresses(address_id),
      INDEX idx_orders_customer_status (customer_id, status)
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
      FOREIGN KEY (order_id) REFERENCES orders(order_id),
      FOREIGN KEY (product_id) REFERENCES products(product_id),
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
      FOREIGN KEY (order_id) REFERENCES orders(order_id),
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
      FOREIGN KEY (product_id) REFERENCES products(product_id),
      FOREIGN KEY (order_id) REFERENCES orders(order_id),
      INDEX idx_inventory_product (product_id)
    )
    """,

    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
      idempotency_key VARCHAR(64) PRIMARY KEY,
      order_id INT NOT NULL,
      status ENUM('IN_PROGRESS','COMPLETED') NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (order_id) REFERENCES orders(order_id)
    )
    """,
]


# Milestone 3 sample data for the review/demo.
SAMPLE_DATA_STATEMENTS = [
    """
    INSERT IGNORE INTO categories (
      category_id,
      category_name,
      description,
      status
    )
    VALUES (
      1,
      'Electronics',
      'Electronic gadgets and accessories',
      'ACTIVE'
    )
    """,

    """
    INSERT IGNORE INTO products (
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


def get_ssm_parameter(name, with_decryption=False):
    """
    Retrieve a single value from SSM Parameter Store.
    """

    response = ssm.get_parameter(
        Name=name,
        WithDecryption=with_decryption
    )

    return response["Parameter"]["Value"]


def lambda_handler(event, context):

    applied = []
    conn = None

    try:

        # ========================================================
        # READ DATABASE PARAMETERS FROM SSM
        # ========================================================

        host = get_ssm_parameter(
            os.environ["DB_HOST_PARAM"]
        )

        db_name = get_ssm_parameter(
            os.environ["DB_NAME_PARAM"]
        )

        user = get_ssm_parameter(
            os.environ["DB_USER_PARAM"]
        )

        password = get_ssm_parameter(
            os.environ["DB_PASSWORD_PARAM"],
            with_decryption=True
        )

        # ========================================================
        # CONNECT TO RDS
        # ========================================================

        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            db=db_name,
            connect_timeout=10,
            autocommit=True
        )

        # ========================================================
        # APPLY DATABASE SCHEMA
        # ========================================================

        with conn.cursor() as cur:

            for stmt in DDL_STATEMENTS:

                cur.execute(stmt)

                applied.append(
                    stmt.strip().split("\n")[0]
                )

            # ====================================================
            # INSERT SAMPLE DATA
            # ====================================================

            for stmt in SAMPLE_DATA_STATEMENTS:

                cur.execute(stmt)

        # ========================================================
        # SUCCESS
        # ========================================================

        return {
            "statusCode": 200,
            "body": json.dumps({
                "success": True,
                "tables_applied": len(DDL_STATEMENTS),
                "sample_data_applied": True
            })
        }

    except Exception as e:

        # ========================================================
        # FAILURE
        # ========================================================

        return {
            "statusCode": 500,
            "body": json.dumps({
                "success": False,
                "error": str(e),
                "applied_so_far": applied
            })
        }

    finally:

        if conn is not None:
            conn.close()