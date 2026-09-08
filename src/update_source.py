import sqlite3
from pathlib import Path
from datetime import datetime


DB_PATH = Path("data/source/source.db")


def update_database():
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("""
        UPDATE orders
        SET
            status = ?,
            updated_at = ?
        WHERE order_id = ?
    """, ("cancelled", updated_at, 101))

    connection.commit()
    connection.close()


if __name__ == "__main__":
    update_database()