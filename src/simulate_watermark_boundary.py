import json
from pathlib import Path
import sqlite3
from datetime import datetime
import csv

state_path = Path("data/state/orders_state.json")
db_path = Path("data/source/source.db")

def insert_order():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    with open (state_path, mode='r', newline='', encoding='utf-8') as arquivo_json:
                state = json.load(arquivo_json)
                last_updated_at = state["last_updated_at"]

    orders = [
            (104, "approved", 175.0, last_updated_at, last_updated_at),
            ]
    cursor.executemany("""
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
    connection.commit()  # Grava as alterações no disco
    connection.close()   # Libera o arquivo do banco

if __name__ == "__main__":
    insert_order()