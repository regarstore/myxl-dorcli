import sqlite3
import logging

DATABASE_URL = "regar_store.db"

def get_db_connection():
    """Creates a database connection."""
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        phone_number TEXT PRIMARY KEY,
        balance INTEGER NOT NULL DEFAULT 0
    )
    """)
    logging.info("Users table created or already exists.")

    # Create packages table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS packages (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        admin_price INTEGER
    )
    """)
    logging.info("Packages table created or already exists.")

    conn.commit()
    conn.close()

def get_all_packages():
    """Retrieves all packages from the local database."""
    conn = get_db_connection()
    packages = conn.execute('SELECT * FROM packages ORDER BY price').fetchall()
    conn.close()
    return packages

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database has been initialized.")
