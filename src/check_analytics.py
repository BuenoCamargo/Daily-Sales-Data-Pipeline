import sqlite3
from pathlib import Path

DB_PATH = Path("data/curated/analytics.db")

def check_database():
    connection = sqlite3.connect(DB_PATH)

    cursor = connection.cursor()

    cursor.execute("""
            SELECT * FROM orders_current
    """
        )
    
    orders = cursor.fetchall()

    for order in orders:
        print(order)

    connection.close()

check_database()