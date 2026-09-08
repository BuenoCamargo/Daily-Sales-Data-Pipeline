import sqlite3
from pathlib import Path

DB_PATH = Path("data/quarantine/quarantine.db")

def check_quarantine():
    connection = sqlite3.connect(DB_PATH)

    cursor = connection.cursor()

    cursor.execute("""
            SELECT * FROM orders_quarantine
    """
        )
    
    orders = cursor.fetchall()

    for order in orders:
        print(order)

    connection.close()

check_quarantine()