import sqlite3
from pathlib import Path


db_path = Path("data/source/source.db")


def reset_database():
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)

    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    orders = [
        (101, "approved", 100.0, "2026-08-25 10:00:00", "2026-08-25 10:00:00"),
        (102, "approved", 250.0, "2026-08-25 11:00:00", "2026-08-25 11:00:00"),
        (103, "pending",   80.0, "2026-08-25 12:00:00", "2026-08-25 12:00:00"),
    ]

    cursor.executemany(
        """
        INSERT INTO orders (
            order_id,
            status,
            amount,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        orders
    )

    connection.commit()

    connection.close()


reset_database()