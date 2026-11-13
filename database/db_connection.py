import os
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


_db_pool = None
_pool_init_attempted = False


def get_db_pool():
    global _db_pool, _pool_init_attempted
    if _db_pool is None and not _pool_init_attempted:
        _pool_init_attempted = True
        try:
            from mysql.connector import pooling
            _db_pool = pooling.MySQLConnectionPool(
                pool_name="jyotish_conn_pool",
                pool_size=int(os.getenv("MYSQL_POOL_SIZE", 3)),
                pool_reset_session=True,
                host=os.getenv("MYSQL_HOST", "localhost"),
                port=int(os.getenv("MYSQL_PORT", 3306)),
                user=os.getenv("MYSQL_USER", "root"),
                password=os.getenv("MYSQL_PASSWORD", ""),
                database=os.getenv("MYSQL_NAME", "jyotishveda"),
            )
        except Exception as e:
            print(f"[DB Pool Warning] Could not initialize connection pool: {e}")
            _db_pool = None
    return _db_pool


def get_db_connection():
    """
    Returns a MySQL connection from the connection pool if available,
    or falls back to a new direct connection.
    Always close connections in a finally block to return them to the pool.
    """
    import time
    pool = get_db_pool()
    if pool:
        try:
            return pool.get_connection()
        except Exception:
            pass

    last_err = None
    for attempt in range(5):
        try:
            return mysql.connector.connect(
                host=os.getenv("MYSQL_HOST", "localhost"),
                port=int(os.getenv("MYSQL_PORT", 3306)),
                user=os.getenv("MYSQL_USER", "root"),
                password=os.getenv("MYSQL_PASSWORD", ""),
                database=os.getenv("MYSQL_NAME", "jyotishveda"),
                connection_timeout=10,
            )
        except Exception as e:
            last_err = e
            if "1040" in str(e) and attempt < 4:
                time.sleep(2 * (attempt + 1))
            else:
                break
    raise last_err


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
