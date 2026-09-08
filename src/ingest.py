import sqlite3
from pathlib import Path
import csv
from datetime import datetime
import json

state_path = Path("data/state/orders_state.json")
db_path = Path("data/source/source.db")


def ingest_database():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = Path(f"data/raw/orders/orders_{timestamp}.csv")
    connection = sqlite3.connect(db_path)
    cursor = connection.cursor()

    if state_path.exists():

        with open (state_path, mode='r', newline='', encoding='utf-8') as arquivo_json:
            state = json.load(arquivo_json)
            last_updated_at = state["last_updated_at"]

        cursor.execute("""
            SELECT
                order_id,
                status,
                amount,
                created_at,
                updated_at
            FROM orders
            WHERE updated_at >= ? 
            """, (last_updated_at,)) ## Wow! Isso é genial. Sequestra apenas o que foi mudado na ultima vez que usou a ingestão
            
        orders = cursor.fetchall()
        if not orders:
            print("No new or updated orders.")
            connection.close()
            return
        
        with open(output_path, mode='w', newline='',encoding='utf-8') as arquivo_csv:
                escritor = csv.writer(arquivo_csv)
                escritor.writerow(
                    ["order_id", "status", "amount", "created_at","updated_at"]
                ) #cabeçalho
                escritor.writerows(orders)

        new_watermark = max(order[4] for order in orders)

        with open(state_path, mode="w", encoding="utf-8") as arquivo_json:
            json.dump(
            {"last_updated_at": new_watermark},
            arquivo_json,
            indent=4
                )
        
        connection.close()
    else:

        cursor.execute("""
        SELECT
            order_id,
            status,
            amount,
            created_at,
            updated_at
        FROM orders
        """)
        
        orders = cursor.fetchall()

        with open(output_path, mode='w', newline='',encoding='utf-8') as arquivo_csv:
            escritor = csv.writer(arquivo_csv)
            escritor.writerow(
                ["order_id", "status", "amount", "created_at","updated_at"]
            ) #cabeçalho
            escritor.writerows(orders)
        if not orders:
            print("No orders found.")
            connection.close()
            return
        
        new_watermark = max(order[4] for order in orders)
        
        with open(state_path, mode="w", encoding="utf-8") as arquivo_json:
            json.dump(
            {"last_updated_at": new_watermark},
            arquivo_json,
            indent=4
                        )

        connection.close()

ingest_database()