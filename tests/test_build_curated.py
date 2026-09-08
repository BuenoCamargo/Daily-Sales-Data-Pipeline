import sqlite3
import pytest
import csv
import random as rd
from src.build_curated import (
    parse_order_row,
    validate_order,
    process_order_row,
    upsert_orders,
    save_quarantine_records,
    build_analytics_db,
    build_quarantine_db,
    validate_csv_schema,
    build_quarantine_key,
    build_quarantine_record
)


@pytest.fixture
def orders_db():
    connection = sqlite3.connect(":memory:")
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE orders_current (
            order_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    yield cursor

    connection.close()

@pytest.fixture
def quarantine_db():
    connection = sqlite3.connect(":memory:")
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
            source_file TEXT NOT NULL,

            UNIQUE(quarantine_key)
        )
    """)

    yield cursor

    connection.close()

def test_build_curated_with_large_mixed_batch(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"
    raw_path.mkdir()
    raw_file = raw_path / "orders_test.csv"

    rd.seed(42)

    timestamp = "2026-09-07 10:00:00"

    rows = [
    {
        "order_id": row,
        "status": rd.choice(["approved", "pending", "rejected"]),
        "amount": rd.randint(50, 600),
        "created_at": timestamp,
        "updated_at": timestamp
    }
    for row in range(1000, 1080)
    ]

    negative_rows = [
    {
        "order_id": row,
        "status": rd.choice(["approved", "pending", "rejected"]),
        "amount": rd.randint(-600, -50),
        "created_at": timestamp,
        "updated_at": timestamp
    }
    for row in range(1080, 1090)
    ]

    parsing_rows = [
    {
        "order_id": row,
        "status": rd.choice(["approved", "pending", "rejected"]),
        "amount": "abc",
        "created_at": timestamp,
        "updated_at": timestamp
    }
    for row in range(1090, 1095)
    ]

    invalid_order_id_rows = [
    {
        "order_id": f"INVALID_{row}",
        "status": rd.choice(["approved", "pending", "rejected"]),
        "amount": rd.randint(50, 600),
        "created_at": timestamp,
        "updated_at": timestamp
    }
    for row in range(1, 6)
    ]

    rows.extend(negative_rows)
    rows.extend(parsing_rows)
    rows.extend(invalid_order_id_rows)

    assert len(rows) == 100

    with open(raw_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )
        writer.writeheader()
        writer.writerows(rows)

    build_quarantine_db(
        quarantine_path=quarantine_path
    )
    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )

    check_connection = sqlite3.connect(analytics_path)
    check_cursor = check_connection.cursor()

    check_cursor.execute("""
        SELECT COUNT(*)
        FROM orders_current
    """)

    analytics_count = check_cursor.fetchone()[0]

    check_connection.close()

    assert analytics_count == 80

    quarantine_connection = sqlite3.connect(quarantine_path)
    quarantine_cursor = quarantine_connection.cursor()

    quarantine_cursor.execute("""
        SELECT COUNT(*)
        FROM orders_quarantine
        """)

    quarantine_count = quarantine_cursor.fetchone()[0]

    quarantine_cursor.execute("""
        SELECT error_code, COUNT(*)
        FROM orders_quarantine
        GROUP BY error_code
            """)

    error_counts = dict(quarantine_cursor.fetchall())
    quarantine_connection.close()

    assert quarantine_count == 20
    assert error_counts == {
        "INVALID_AMOUNT": 10,
        "INVALID_AMOUNT_FORMAT": 5,
        "INVALID_ORDER_ID_FORMAT": 5
    }

def test_build_curated_keeps_newest_version_across_multiple_raw_files(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"
    raw_path.mkdir()
    newer_file = raw_path / "orders_01.csv"
    older_file = raw_path / "orders_02.csv"

    newer_row = {
    "order_id": "500",
    "status": "cancelled",
    "amount": "100",
    "created_at": "2026-09-07 09:00:00",
    "updated_at": "2026-09-07 15:00:00"
    }

    older_row = {
    "order_id": "500",
    "status": "approved",
    "amount": "100",
    "created_at": "2026-09-07 09:00:00",
    "updated_at": "2026-09-07 10:00:00"
    }


    with open(newer_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )
        writer.writeheader()
        writer.writerow(newer_row)

    with open(older_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )
        writer.writeheader()
        writer.writerow(older_row)
    
    build_quarantine_db(
        quarantine_path=quarantine_path
    )
    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )

    check_connection = sqlite3.connect(analytics_path)
    check_cursor = check_connection.cursor()

    check_cursor.execute("""
        SELECT order_id, status, updated_at
        FROM orders_current
        WHERE order_id = 500
    """)

    result = check_cursor.fetchall()

    check_connection.close()

    assert result == [
        (500, "cancelled", "2026-09-07 15:00:00")
    ]

def test_build_curated_preserves_existing_analytics_when_processing_fails(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"
    temp_analytics_path = analytics_path.with_name(
        f"{analytics_path.stem}_building{analytics_path.suffix}"
    )

    raw_path.mkdir()
    raw_file = raw_path / "orders_test.csv"

    connection = sqlite3.connect(analytics_path)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE orders_current (
            order_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT INTO orders_current (
            order_id,
            status,
            amount,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        999,
        "approved",
        500.0,
        "2026-09-03 10:00:00",
        "2026-09-03 10:00:00"
    ))

    connection.commit()
    connection.close()

    # CRIA RAW QUEBRADO: coluna amount não existe
    rows = [
        {
            "order_id": "201",
            "status": "approved",
            "created_at": "2026-09-04 10:00:00",
            "updated_at": "2026-09-04 10:00:00"
        }
    ]

    with open(raw_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "created_at",
                "updated_at"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError) as exc_info:
        build_analytics_db(
            raw_path=raw_path,
            analytics_path=analytics_path,
            quarantine_path=quarantine_path
        )

    check_connection = sqlite3.connect(analytics_path)
    check_cursor = check_connection.cursor()

    check_cursor.execute("""
        SELECT order_id
        FROM orders_current
    """)

    result = check_cursor.fetchall()

    check_connection.close()

    assert result == [(999,)]
    assert not temp_analytics_path.exists()
    assert "amount" in str(exc_info.value)

def test_validate_csv_schema_accepts_required_columns():
    fieldnames = [
        "order_id",
        "status",
        "amount",
        "created_at",
        "updated_at"
    ]

    result = validate_csv_schema(fieldnames)

    assert result is None

def test_validate_csv_schema_rejects_missing_columns():
    fieldnames = [
        "order_id",
        "status",
        "created_at",
        "updated_at"
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_csv_schema(fieldnames)

    assert "amount" in str(exc_info.value)

def test_build_curated_replaces_existing_analytics_after_success(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"
    temp_analytics_path = analytics_path.with_name(
        f"{analytics_path.stem}_building{analytics_path.suffix}"
    )

    raw_path.mkdir()
    raw_file = raw_path / "orders_test.csv"

    connection = sqlite3.connect(analytics_path)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE orders_current (
            order_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT INTO orders_current (
            order_id,
            status,
            amount,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        999,
        "approved",
        500.0,
        "2026-09-03 10:00:00",
        "2026-09-03 10:00:00"
    ))

    connection.commit()
    connection.close()

    rows = [
        {
            "order_id": "201",
            "status": "approved",
            "amount": 150,
            "created_at": "2026-09-04 10:00:00",
            "updated_at": "2026-09-04 10:00:00"
        },
        {
            "order_id": "203",
            "status": "approved",
            "amount": 90,
            "created_at": "2026-09-04 10:00:00",
            "updated_at": "2026-09-04 10:00:00"
        }
    ]

    build_quarantine_db(
        quarantine_path=quarantine_path
    )

    with open(raw_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)


    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )

    check_connection = sqlite3.connect(analytics_path)
    check_cursor = check_connection.cursor()

    check_cursor.execute("""
        SELECT order_id
        FROM orders_current
        """)

    result_analytics = check_cursor.fetchall()
    order_ids = {row[0] for row in result_analytics}

    assert order_ids == {201, 203}

    assert not temp_analytics_path.exists()
    
def test_build_curated_preserves_existing_analytics_when_raw_is_empty(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"

    raw_path.mkdir()

    connection = sqlite3.connect(analytics_path)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE orders_current (
            order_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        INSERT INTO orders_current (
            order_id,
            status,
            amount,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        999,
        "approved",
        500.0,
        "2026-09-03 10:00:00",
        "2026-09-03 10:00:00"
    ))

    connection.commit()
    connection.close()

    build_analytics_db(
    raw_path=raw_path,
    analytics_path=analytics_path,
    quarantine_path=quarantine_path
    )

    check_connection = sqlite3.connect(analytics_path)
    check_cursor = check_connection.cursor()

    check_cursor.execute("""
        SELECT order_id
        FROM orders_current
    """)

    result = check_cursor.fetchall()

    check_connection.close()

    assert result == [(999,)]

def test_build_curated_with_temp_files(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"

    raw_path.mkdir()

    raw_file = raw_path / "orders_test.csv"

    rows = [
    {
        "order_id": "201",
        "status": "approved",
        "amount": "150.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    },
    {
        "order_id": "202",
        "status": "approved",
        "amount": "-50.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    },
    {
        "order_id": "203",
        "status": "approved",
        "amount": "90.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    }
    ]

    with open(raw_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    build_quarantine_db(
        quarantine_path=quarantine_path
        )

    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )

    analytics_connection = sqlite3.connect(analytics_path)
    quarantine_connection = sqlite3.connect(quarantine_path)

    analytics_cursor = analytics_connection.cursor()
    quarantine_cursor = quarantine_connection.cursor()

    analytics_cursor.execute("""
        SELECT order_id 
        FROM orders_current
    """)
        
    orders_analytics = analytics_cursor.fetchall()
    
    analytics_order_ids = {row[0] for row in orders_analytics}

    assert analytics_order_ids == {201, 203}

    quarantine_cursor.execute("""
        SELECT order_id
        FROM orders_quarantine
    """)

    orders_quarantine = quarantine_cursor.fetchall()

    quarantine_order_ids = {row[0] for row in orders_quarantine}

    assert quarantine_order_ids == {"202"}

    analytics_connection.close()
    quarantine_connection.close()

def test_build_curated_is_idempotent_on_reprocessing(tmp_path):
    raw_path = tmp_path / "raw"
    analytics_path = tmp_path / "analytics.db"
    quarantine_path = tmp_path / "quarantine.db"

    raw_path.mkdir()

    raw_file = raw_path / "orders_test.csv"

    rows = [
    {
        "order_id": "201",
        "status": "approved",
        "amount": "150.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    },
    {
        "order_id": "202",
        "status": "approved",
        "amount": "-50.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    },
    {
        "order_id": "203",
        "status": "approved",
        "amount": "90.0",
        "created_at": "2026-09-03 10:00:00",
        "updated_at": "2026-09-03 10:00:00"
    }
    ]

    with open(raw_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "order_id",
                "status",
                "amount",
                "created_at",
                "updated_at"
            ]
        )
        writer.writeheader()
        writer.writerows(rows)

    build_quarantine_db(quarantine_path=quarantine_path)

    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )

    build_analytics_db(
        raw_path=raw_path,
        analytics_path=analytics_path,
        quarantine_path=quarantine_path
    )
    analytics_connection = sqlite3.connect(analytics_path)
    quarantine_connection = sqlite3.connect(quarantine_path)

    analytics_cursor = analytics_connection.cursor()
    quarantine_cursor = quarantine_connection.cursor()

    analytics_cursor.execute("""
        SELECT COUNT(*)
        FROM orders_current
    """)
        
    result_analytics = analytics_cursor.fetchone()
    
    quarantine_cursor.execute("""
        SELECT COUNT(*)
        FROM orders_quarantine
    """)

    result_quarantine = quarantine_cursor.fetchone()

    assert result_analytics[0] == 2
    assert result_quarantine[0] == 1

    analytics_connection.close()
    quarantine_connection.close()

def test_orders_flow_integration(orders_db, quarantine_db):
    orders_cursor = orders_db
    quarantine_cursor = quarantine_db

    rows = [
        {
            "order_id": "105",
            "status": "approved",
            "amount": "320.0",
            "created_at": "2026-09-03 10:00:00",
            "updated_at": "2026-09-03 10:00:00"
        },
        {
            "order_id": "106",
            "status": "approved",
            "amount": "-900.0",
            "created_at": "2026-09-03 10:00:00",
            "updated_at": "2026-09-03 10:00:00"
        },
        {
            "order_id": "107",
            "status": "pending",
            "amount": "abc",
            "created_at": "2026-09-03 10:00:00",
            "updated_at": "2026-09-03 10:00:00"
        },
        {
            "order_id": "XYZ",
            "status": "approved",
            "amount": "150.0",
            "created_at": "2026-09-03 10:00:00",
            "updated_at": "2026-09-03 10:00:00"
        },
        {
            "order_id": "108",
            "status": "approved",
            "amount": "75.0",
            "created_at": "2026-09-03 10:00:00",
            "updated_at": "2026-09-03 10:00:00"
        }
    ]
    orders_to_upsert = []
    orders_quarantine = []

    timestamp = "20260903_100000"
    source_file = "integration_test.csv"

    for row in rows:
        order_to_upsert, quarantine_record = process_order_row(
            row,
            timestamp,
            source_file
        )

        if quarantine_record:
            orders_quarantine.append(quarantine_record)
            continue

        orders_to_upsert.append(order_to_upsert)

    upsert_orders(orders_cursor, orders_to_upsert)
    save_quarantine_records(quarantine_cursor,orders_quarantine)

    orders_cursor.execute("""
        SELECT COUNT(*)    
        FROM orders_current
        """)
    quarantine_cursor.execute("""
        SELECT COUNT(*)
        FROM orders_quarantine
        """)
    result_valid_orders = orders_cursor.fetchone()
    result_invalid_orders = quarantine_cursor.fetchone()

    assert result_valid_orders[0] == 2
    assert result_invalid_orders[0] == 3

    orders_cursor.execute("""
        SELECT order_id   
        FROM orders_current
        """)

    result_orders_in_curated = orders_cursor.fetchall()
    order_ids = {row[0] for row in result_orders_in_curated}
    assert order_ids == {105, 108}

    quarantine_cursor.execute("""
        SELECT order_id
        FROM orders_quarantine
        """)

    result_orders_in_quarantine = quarantine_cursor.fetchall()
    quarantine_order_ids = {row[0] for row in result_orders_in_quarantine}
    assert quarantine_order_ids == {"106", "107", "XYZ"}

def test_quarantine_keeps_different_errors_for_same_version(quarantine_db):
    cursor = quarantine_db

    order = {
        "order_id": "106",
        "status": "aproved",
        "amount": "-200.00",
        "created_at": "2026-09-01 10:00:00",
        "updated_at": "2026-09-01 15:00:00"
    }

    error_1 = {
        "error_code": "INVALID_AMOUNT",
        "error_message": "amount must be greater than zero"
    }

    error_2 = {
        "error_code": "INVALID_STATUS",
        "error_message": "invalid status; received 'aproved'"
    }

    record_1 = build_quarantine_record(
        order,
        error_1,
        "20260903_090000",
        "orders_test.csv"
    )

    record_2 = build_quarantine_record(
        order,
        error_2,
        "20260903_090000",
        "orders_test.csv"
    )

    save_quarantine_records(cursor, [record_1])
    save_quarantine_records(cursor, [record_2])

    cursor.execute("""
        SELECT COUNT(*)
        FROM orders_quarantine
    """)

    result = cursor.fetchone()

    assert result[0] == 2

def test_upsert_inserts_new_order(orders_db):
    cursor = orders_db

    orders = [
        (
            101,
            "approved",
            100.0,
            "2026-09-01 10:00:00",
            "2026-09-01 10:00:00"
        )
    ]

    upsert_orders(cursor, orders)

    cursor.execute("""
        SELECT *
        FROM orders_current
        WHERE order_id = 101
    """)

    result = cursor.fetchone()

    assert result[0] == 101
    assert result[1] == "approved"
    assert result[2] == 100.0

def test_upsert_updates_newer_order(orders_db):
    cursor = orders_db

    upsert_orders(cursor, [
        (
            101,
            "approved",
            100.0,
            "2026-09-01 10:00:00",
            "2026-09-01 10:00:00"
        )
    ])

    upsert_orders(cursor, [
        (
            101,
            "cancelled",
            100.0,
            "2026-09-01 10:00:00",
            "2026-09-01 15:00:00"
        )
    ])

    cursor.execute("""
        SELECT *
        FROM orders_current
        WHERE order_id = 101
    """)

    result = cursor.fetchone()

    assert result[1] == "cancelled"
    assert result[4] == "2026-09-01 15:00:00"

def test_upsert_does_not_regress_to_old_version(orders_db):
    cursor = orders_db

    upsert_orders(cursor, [
        (
            101,
            "cancelled",
            100.0,
            "2026-09-01 10:00:00",
            "2026-09-01 15:00:00"
        )
    ])

    upsert_orders(cursor, [
        (
            101,
            "approved",
            100.0,
            "2026-09-01 10:00:00",
            "2026-09-01 10:00:00"
        )
    ])

    cursor.execute("""
        SELECT *
        FROM orders_current
        WHERE order_id = 101
    """)

    result = cursor.fetchone()

    assert result[1] == "cancelled"
    assert result[4] == "2026-09-01 15:00:00"

def test_quarantine_is_idempotent(quarantine_db):
    cursor = quarantine_db

    order = {
        "order_id": 106,
        "amount": -200,
        "status": "approved",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }
    error = {
    "error_code": "INVALID_AMOUNT",
    "error_message": "amount must be greater than zero"
    }

    record = build_quarantine_record(order, error, "20260903_090000", "orders_test.csv")

    save_quarantine_records(cursor, [record])
    cursor.execute("""
            SELECT COUNT(*)
            FROM orders_quarantine
        """)
    result = cursor.fetchone()

    assert result[0] == 1

def test_quarantine_key_is_deterministic():
    order = {
        "order_id": None,
        "status": "approved",
        "amount": "100.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    error = {
        "error_code": "INVALID_ORDER_ID_FORMAT",
        "error_message": "qualquer mensagem"
    }

    key_1 = build_quarantine_key(order, error)
    key_2 = build_quarantine_key(order, error)

    assert key_1 == key_2

def test_quarantine_is_idempotent_with_missing_order_id(quarantine_db):
    cursor = quarantine_db

    order = {
    "order_id": None,
    "status": "approved",
    "amount": "-900.0",
    "created_at": "2026-09-01 09:00:00",
    "updated_at": "2026-09-01 09:00:00"
}

    error = {
    "error_code": "INVALID_ORDER_ID_FORMAT",
    "error_message": "order_id is not an integer; received 'None'"
}

    record = build_quarantine_record(
    order,
    error,
    "20260903_090000",
    "orders_test.csv"
)

    save_quarantine_records(cursor, [record])
    save_quarantine_records(cursor, [record])

    cursor.execute("""
            SELECT COUNT(*)
            FROM orders_quarantine
        """)
    result = cursor.fetchone()

    assert result[0] == 1

def test_quarantine_keeps_distinct_rows_with_missing_order_id(quarantine_db):
    cursor = quarantine_db

    order_1 = {
    "order_id": None,
    "status": "approved",
    "amount": "100.0",
    "created_at": "2026-09-01 09:00:00",
    "updated_at": "2026-09-01 09:00:00"
}

    order_2 = {
    "order_id": None,
    "status": "approved",
    "amount": "200.0",
    "created_at": "2026-09-01 09:00:00",
    "updated_at": "2026-09-01 09:00:00"
}

    error = {
    "error_code": "INVALID_ORDER_ID_FORMAT",
    "error_message": "order_id is not an integer; received 'None'"
}
    record_1 = build_quarantine_record(
    order_1,
    error,
    "20260903_090000",
    "orders_test.csv"
)

    record_2 = build_quarantine_record(
    order_2,
    error,
    "20260903_090000",
    "orders_test.csv"
)

    save_quarantine_records(cursor, [record_1])
    save_quarantine_records(cursor, [record_2])
    cursor.execute("""
        SELECT COUNT(*)
        FROM orders_quarantine
    """)
    result = cursor.fetchone()

    assert result[0] == 2

    cursor.execute("""
        SELECT amount
        FROM orders_quarantine
        ORDER BY amount
    """)

    result = cursor.fetchall()

    assert result == [("100.0",),("200.0",)]

def test_process_valid_order_id():
    row = {
        "order_id": "110",
        "status": "approved",
        "amount": "90.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    timestamp = "20260903_080000"
    source_file = "orders_test.csv"

    order_to_upsert, quarantine_record = process_order_row(
        row,
        timestamp,
        source_file
    )
    assert quarantine_record is None
    assert order_to_upsert[0] == 110
    assert order_to_upsert[1] == "approved"
    assert order_to_upsert[2] == 90.0

def test_process_invalid_order_id():
    row = {
        "order_id": "XYZ",
        "status": "approved",
        "amount": "150.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    timestamp = "20260903_080000"
    source_file = "orders_test.csv"

    order_to_upsert, quarantine_record = process_order_row(
        row,
        timestamp,
        source_file
    )
    assert order_to_upsert is None
    assert quarantine_record[1] == row["order_id"]
    assert quarantine_record[6] == "INVALID_ORDER_ID_FORMAT"


def test_process_invalid_amount():
    row = {
        "order_id": "106",
        "status": "approved",
        "amount": "-900.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    timestamp = "20260903_080000"
    source_file = "orders_test.csv"

    order_to_upsert, quarantine_record = process_order_row(
        row,
        timestamp,
        source_file
    )

    assert order_to_upsert is None
    assert quarantine_record[6] == "INVALID_AMOUNT"
    
def test_quarantine_keeps_new_order_version(quarantine_db):
    cursor = quarantine_db

    error = {
        "error_code": "INVALID_AMOUNT",
        "error_message": "amount must be greater than zero"
    }

    old_version = {
        "order_id": "106",
        "status": "approved",
        "amount": "-200.0",
        "created_at": "2026-09-01 10:00:00",
        "updated_at": "2026-09-01 15:00:00"
    }

    new_version = {
        "order_id": "106",
        "status": "approved",
        "amount": "-200.0",
        "created_at": "2026-09-01 10:00:00",
        "updated_at": "2026-09-01 16:00:00"
    }

    record_1 = build_quarantine_record(
        old_version,
        error,
        "20260903_090000",
        "orders_test.csv"
    )

    record_2 = build_quarantine_record(
        new_version,
        error,
        "20260903_100000",
        "orders_test.csv"
    )

    save_quarantine_records(cursor, [record_1])
    save_quarantine_records(cursor, [record_2])

    cursor.execute("""
        SELECT updated_at
        FROM orders_quarantine
        ORDER BY updated_at
    """)

    result = cursor.fetchall()

    assert result == [
        ("2026-09-01 15:00:00",),
        ("2026-09-01 16:00:00",)
    ]

def test_parse_valid_order_id():
    row = {
        "order_id": "110",
        "status": "approved",
        "amount": "90.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert error is None
    assert parsed_order["order_id"] == 110
    assert parsed_order["amount"] == 90.0

def test_parse_missing_status():
    row = {
        "order_id": "107",
        "status": None,
        "amount": "100",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "MISSING_STATUS"
    
def test_parse_invalid_created_at():
    row = {
        "order_id": "107",
        "status": "pending",
        "amount": "100",
        "created_at": "2026/09/01",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_CREATED_AT_FORMAT"

def test_parse_missing_created_at():

    row = {
        "order_id": "107",
        "status": "pending",
        "amount": "100",
        "created_at": None,
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "MISSING_CREATED_AT"

def test_parse_missing_order_id():
    row = {
        "order_id": None,
        "status": "approved",
        "amount": "150.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_ORDER_ID_FORMAT"
    
def test_parse_invalid_order_id():
    row = {
        "order_id": "XYZ",
        "status": "approved",
        "amount": "150.0",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_ORDER_ID_FORMAT"

def test_parse_invalid_updated_at():

    row = {
        "order_id": "107",
        "status": "pending",
        "amount": "100",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "INVALID_DATE"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_UPDATED_AT_FORMAT"

def test_parse_missing_amount():

    row = {
        "order_id": "107",
        "status": "pending",
        "amount": None,
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_AMOUNT_FORMAT"
 
def test_parse_invalid_amount():
    row = {
        "order_id": "107",
        "status": "pending",
        "amount": "abc",
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    parsed_order, error = parse_order_row(row)

    assert parsed_order is None
    assert error["error_code"] == "INVALID_AMOUNT_FORMAT"


def test_validate_valid_order():
    order = {
        "order_id": 110,
        "status": "approved",
        "amount": 90.0,
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    error = validate_order(order)

    assert error is None


def test_validate_invalid_amount():
    order = {
        "order_id": 106,
        "status": "approved",
        "amount": -900.0,
        "created_at": "2026-09-01 09:00:00",
        "updated_at": "2026-09-01 09:00:00"
    }

    error = validate_order(order)

    assert error["error_code"] == "INVALID_AMOUNT"