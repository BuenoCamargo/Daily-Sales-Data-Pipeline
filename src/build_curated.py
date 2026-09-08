import sqlite3
import csv
import json
import hashlib
from pathlib import Path
from datetime import datetime

ANALYTICS_PATH = Path("data/curated/analytics.db")
RAW_PATH = Path("data/raw/orders")
QUARANTINE_PATH = Path("data/quarantine/quarantine.db")

REQUIRED_ORDER_COLUMNS = {
    "order_id",
    "status",
    "amount",
    "created_at",
    "updated_at"
}
def build_quarantine_key(order, error):
    identity_data = {
        "order_id": order["order_id"],
        "status": order["status"],
        "amount": order["amount"],
        "created_at": order["created_at"],
        "updated_at": order["updated_at"],
        "error_code": error["error_code"]
    }

    serialized = json.dumps(
        identity_data,
        sort_keys=True,
        separators=(",", ":")
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

def build_quarantine_db(quarantine_path=QUARANTINE_PATH):

    quarantine_path.parent.mkdir(parents=True,exist_ok=True)   
    
    connection = sqlite3.connect(quarantine_path)
    cursor = connection.cursor()
    

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders_quarantine (
            quarantine_key TEXT PRIMARY KEY,
            order_id TEXT,
            status TEXT,
            amount TEXT,
            created_at TEXT,
            updated_at TEXT,
            error_code TEXT NOT NULL,
            error_message TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            source_file TEXT NOT NULL
        )
""")
    connection.commit()
    connection.close()

def validate_csv_schema(fieldnames):
    received_columns = set(fieldnames or [])
    missing_columns = sorted(REQUIRED_ORDER_COLUMNS - received_columns)

    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

def parse_order_row(row):
    try:
        order_id = int(row["order_id"])

    except (ValueError, TypeError):
        return None, {
            "error_code": "INVALID_ORDER_ID_FORMAT",
            "error_message": f"order_id is not an integer; received '{row['order_id']}'"
        }
    
    status = row["status"]

    if status is None or status.strip() == "":
        return None, {
        "error_code": "MISSING_STATUS",
        "error_message": "status column is missing value"
    }

    status = status.strip()

    try:
        amount = float(row["amount"])

    except (ValueError, TypeError):
        return None, {
            "error_code": "INVALID_AMOUNT_FORMAT",
            "error_message": f"amount is not numeric; received '{row['amount']}'"
        }

    created_at = row["created_at"]

    if created_at is None or created_at == "":
        return None, {
            "error_code": "MISSING_CREATED_AT",
            "error_message": "created_at is missing"
        }
    
    try:
        created_at = datetime.strptime(
            created_at,
            "%Y-%m-%d %H:%M:%S"
        )
        created_at = created_at.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except (ValueError, TypeError):
        return None, {
            "error_code": "INVALID_CREATED_AT_FORMAT",
            "error_message": (
                f"created_at has invalid format; "
                f"received '{row['created_at']}'"
            )
        }
    
    try:
        parsed_updated_at = datetime.strptime(
            row["updated_at"],
            "%Y-%m-%d %H:%M:%S"
        )
        updated_at = parsed_updated_at.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    except (ValueError, TypeError):
        return None, {
            "error_code": "INVALID_UPDATED_AT_FORMAT",
            "error_message": (
                f"updated_at has invalid format; "
                f"received '{row['updated_at']}'"
            )
        }
    
    parsed_order = {
        "order_id": order_id,
        "status": status,
        "amount": amount,
        "created_at": created_at,
        "updated_at": updated_at
    }

    return parsed_order, None

def validate_order(parsed_order):

    if parsed_order["amount"] <= 0:
        return {
            "error_code": "INVALID_AMOUNT",
            "error_message": f"amount: {parsed_order['amount']}, must be greater than zero"
        }
    return None

def upsert_orders(cursor, orders_to_upsert):
    cursor.executemany(
    """
    INSERT INTO orders_current (
        order_id,
        status,
        amount,
        created_at,
        updated_at
    )
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(order_id)
    DO UPDATE SET
        status = excluded.status,
        amount = excluded.amount,
        created_at = excluded.created_at,
        updated_at = excluded.updated_at
    WHERE excluded.updated_at > orders_current.updated_at
    """,
    orders_to_upsert
        )
    
def save_quarantine_records(quarantine_cursor, orders_quarantine):
    quarantine_cursor.executemany(
    """
    INSERT INTO orders_quarantine (
        quarantine_key,
        order_id,
        status,
        amount,
        created_at,
        updated_at,
        error_code,
        error_message,
        detected_at,
        source_file
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(quarantine_key)
    DO NOTHING
        """, orders_quarantine)

def build_quarantine_record(order, error, timestamp, file):
    quarantine_key = build_quarantine_key(
        order,
        error
    )
    return (
        quarantine_key,
        order["order_id"],
        order["status"],
        order["amount"],
        order["created_at"],
        order["updated_at"],
        error["error_code"],
        error["error_message"],
        timestamp,
        str(file)
    )

def process_order_row(row, timestamp, file):

    parsed_order, error = parse_order_row(row)

    if error:
        quarantine_record = build_quarantine_record(
            row,
            error,
            timestamp,
            file
        )

        return None, quarantine_record

    validation_error = validate_order(parsed_order)

    if validation_error:
        quarantine_record = build_quarantine_record(
            parsed_order,
            validation_error,
            timestamp,
            file
        )

        return None, quarantine_record

    order_to_upsert = (
        parsed_order["order_id"],
        parsed_order["status"],
        parsed_order["amount"],
        parsed_order["created_at"],
        parsed_order["updated_at"]
    )

    return order_to_upsert, None
    
def build_analytics_db(
    raw_path=RAW_PATH,
    analytics_path=ANALYTICS_PATH,
    quarantine_path=QUARANTINE_PATH
):
    analytics_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(raw_path.glob("*.csv"))

    if not files:
        print("Nenhum arquivo encontrado.")
        return

    temp_analytics_path = analytics_path.with_name(
        f"{analytics_path.stem}_building{analytics_path.suffix}"
    )

    if temp_analytics_path.exists():
        temp_analytics_path.unlink()

    connection = sqlite3.connect(temp_analytics_path)
    cursor = connection.cursor()

    quarantine_connection = None

    try:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders_current (
                order_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        orders_to_upsert = []
        orders_quarantine = []

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        for file in files:
            print(file)
            with open(file, mode='r', newline='', encoding='utf-8') as file_csv:
                reader = csv.DictReader(file_csv)

                validate_csv_schema(reader.fieldnames)

                for row in reader:

                    order_to_upsert, quarantine_record = process_order_row(
                        row,
                        timestamp,
                        file
                    )

                    if quarantine_record:
                        orders_quarantine.append(quarantine_record)
                        continue

                    orders_to_upsert.append(order_to_upsert)

        upsert_orders(cursor, orders_to_upsert)

        connection.commit()

        quarantine_connection = sqlite3.connect(quarantine_path)
        quarantine_cursor = quarantine_connection.cursor()

        save_quarantine_records(quarantine_cursor,orders_quarantine)

        quarantine_connection.commit()
    except Exception:
        connection.rollback()

        if quarantine_connection is not None:
            quarantine_connection.rollback()
            quarantine_connection.close()

        connection.close()

        if temp_analytics_path.exists():
            temp_analytics_path.unlink()

        raise

    else:
        if quarantine_connection is not None:
            quarantine_connection.close()

        connection.close()

        temp_analytics_path.replace(analytics_path)

if __name__ == "__main__":
    build_quarantine_db()
    build_analytics_db()

