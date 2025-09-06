import sqlite3

def create_tables(conn):
    cursor = conn.cursor()

    # Create node_mappings table
    create_node_mappings_sql = """
    CREATE TABLE IF NOT EXISTS node_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name TEXT NOT NULL,
        node_id TEXT NOT NULL,
        column_name TEXT NOT NULL
    );
    """

    # Create device_readings table with 10 float columns + timestamp
    create_device_readings_sql = """
    CREATE TABLE IF NOT EXISTS device_readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sensor1 REAL,
        sensor2 REAL,
        sensor3 REAL,
        sensor4 REAL,
        sensor5 REAL,
        sensor6 REAL,
        sensor7 REAL,
        sensor8 REAL,
        sensor9 REAL,
        sensor10 REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """

    cursor.execute(create_node_mappings_sql)
    cursor.execute(create_device_readings_sql)
    conn.commit()
    print("Tables created successfully.")

def insert_node_mappings(conn):
    cursor = conn.cursor()

    for i in range(1, 11):
        table_name = 'device_readings'
        column_name = f'sensor{i}'
        node_id = f'ns=2;s=Device{i}.Temperature'

        cursor.execute("""
            INSERT INTO node_mappings (table_name, node_id, column_name)
            VALUES (?, ?, ?)
        """, (table_name, node_id, column_name))

    conn.commit()
    print("10 rows inserted into 'node_mappings'.")

def main():
    db_path = 'mydatabase.db'
    conn = sqlite3.connect(db_path)

    try:
        create_tables(conn)
        insert_node_mappings(conn)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
