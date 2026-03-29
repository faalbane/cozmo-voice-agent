"""SQLite order database — real DB, no mocking.

Pre-seeded with sample e-commerce orders for the demo.
All queries and updates hit a real SQLite database.
"""

import datetime
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "shopease.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables and seed with sample data if empty."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            item TEXT NOT NULL,
            total TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'processing',
            tracking TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            action TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # Seed if empty
    cursor.execute("SELECT COUNT(*) FROM orders")
    if cursor.fetchone()[0] == 0:
        now = datetime.datetime.now().isoformat()
        seed_orders = [
            ("12345", "Jane Smith", "Wireless Headphones", "$89.99", "shipped", "1Z999AA10123456784", now, now),
            ("67890", "Mike Johnson", "USB-C Hub", "$34.99", "processing", None, now, now),
            ("11111", "Sarah Lee", "Phone Case", "$19.99", "delivered", "1Z999AA10123456799", now, now),
            ("22222", "Tom Brown", "Bluetooth Speaker", "$49.99", "shipped", "1Z999AA10123456800", now, now),
            ("33333", "Emily Davis", "Laptop Stand", "$29.99", "processing", None, now, now),
        ]
        cursor.executemany(
            "INSERT INTO orders (order_id, customer_name, item, total, status, tracking, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            seed_orders,
        )
        logger.info("Seeded SQLite database with 5 sample orders")

    conn.commit()
    conn.close()


def lookup_order(order_id: str) -> dict | None:
    """Look up an order by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def update_order_status(order_id: str, new_status: str) -> dict | None:
    """Update order status and log the change."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    previous_status = row["status"]
    now = datetime.datetime.now().isoformat()

    cursor.execute(
        "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
        (new_status, now, order_id),
    )
    cursor.execute(
        "INSERT INTO order_log (order_id, action, previous_status, new_status, timestamp) VALUES (?, ?, ?, ?, ?)",
        (order_id, f"status_change", previous_status, new_status, now),
    )

    conn.commit()
    conn.close()

    return lookup_order(order_id)


def get_order_log(order_id: str = None, limit: int = 10) -> list[dict]:
    """Get recent order log entries."""
    conn = get_connection()
    cursor = conn.cursor()
    if order_id:
        cursor.execute("SELECT * FROM order_log WHERE order_id = ? ORDER BY id DESC LIMIT ?", (order_id, limit))
    else:
        cursor.execute("SELECT * FROM order_log ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# Initialize on import
init_db()
