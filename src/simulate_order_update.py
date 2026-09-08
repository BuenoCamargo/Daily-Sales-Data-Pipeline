import sqlite3
from pathlib import Path
from datetime import datetime

updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


DB_PATH = Path("data/source/source.db")


def update_database():

    connection = sqlite3.connect(DB_PATH)

    cursor = connection.cursor()

    cursor.execute("""
        UPDATE orders
        SET 
            status = ?,
            updated_at = ?
        WHERE order_id = ?
    """, ("cancelled", updated_at, 101)
                   )
    
    connection.commit()

    connection.close()


update_database()