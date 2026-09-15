import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_db_connection():
    """
    Opens a new MySQL connection using credentials from .env.
    Callers are responsible for closing the connection (use the
    `with get_db_connection() as conn:` pattern is NOT supported by
    mysql-connector directly, so always close in a finally block or
    use the call_procedure() helper below).
    """
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_NAME", "jyotishveda"),
    )


def call_procedure(proc_name: str, params: list):
    """
    Calls a MySQL stored procedure with parameterized args and returns
    the first result set as a list of dicts. Connection is always
    closed, even on error.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc(proc_name, params)

        rows = []
        for result in cursor.stored_results():
            rows = result.fetchall()

        conn.commit()
        cursor.close()
        return rows
    finally:
        conn.close()
