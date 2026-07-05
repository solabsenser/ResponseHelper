import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import libsql_client

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, token: str):
        self.client = libsql_client.Client(url, auth_token=token)
        self._init_tables()

    def _init_tables(self):
        """Initialize database tables if they don't exist."""
        try:
            with self.client.transaction() as tx:
                # Users table
                tx.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        daily_requests INTEGER DEFAULT 0,
                        last_request_date DATE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # History table
                tx.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER,
                        input TEXT,
                        output TEXT,
                        style TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                    )
                """)

                # Last requests table
                tx.execute("""
                    CREATE TABLE IF NOT EXISTS last_request (
                        telegram_id INTEGER PRIMARY KEY,
                        input TEXT,
                        output TEXT,
                        style TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                    )
                """)

            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def get_or_create_user(self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
        """Get user or create if doesn't exist."""
        try:
            with self.client.transaction() as tx:
                # Check if user exists
                result = tx.execute(
                    "SELECT * FROM users WHERE telegram_id = ?",
                    (telegram_id,)
                )

                if not result.rows:
                    # Create new user
                    tx.execute(
                        """
                        INSERT INTO users (telegram_id, username, first_name, daily_requests)
                        VALUES (?, ?, ?, 0)
                        """,
                        (telegram_id, username, first_name)
                    )
                    return {
                        "telegram_id": telegram_id,
                        "username": username,
                        "first_name": first_name,
                        "daily_requests": 0,
                        "last_request_date": None
                    }

                row = result.rows[0]
                return {
                    "telegram_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "daily_requests": row[3],
                    "last_request_date": row[4]
                }

        except Exception as e:
            logger.error(f"Error getting/creating user: {e}")
            raise

    def check_daily_limit(self, telegram_id: int) -> tuple[bool, int]:
        """Check if user has reached daily limit. Returns (can_proceed, current_requests)."""
        try:
            today = datetime.now().date().isoformat()

            with self.client.transaction() as tx:
                # Get user
                result = tx.execute(
                    "SELECT daily_requests, last_request_date FROM users WHERE telegram_id = ?",
                    (telegram_id,)
                )

                if not result.rows:
                    return True, 0

                daily_requests = result.rows[0][0]
                last_request_date = result.rows[0][1]

                # Reset if new day
                if last_request_date != today:
                    tx.execute(
                        "UPDATE users SET daily_requests = 0, last_request_date = ? WHERE telegram_id = ?",
                        (today, telegram_id)
                    )
                    return True, 0

                return daily_requests < 50, daily_requests

        except Exception as e:
            logger.error(f"Error checking daily limit: {e}")
            return False, 0

    def increment_daily_requests(self, telegram_id: int):
        """Increment daily request count."""
        try:
            today = datetime.now().date().isoformat()

            with self.client.transaction() as tx:
                tx.execute(
                    """
                    UPDATE users 
                    SET daily_requests = daily_requests + 1, 
                        last_request_date = ?
                    WHERE telegram_id = ?
                    """,
                    (today, telegram_id)
                )

        except Exception as e:
            logger.error(f"Error incrementing daily requests: {e}")
            raise

    def save_history(self, telegram_id: int, input_text: str, output: str, style: str):
        """Save to history."""
        try:
            with self.client.transaction() as tx:
                tx.execute(
                    """
                    INSERT INTO history (telegram_id, input, output, style)
                    VALUES (?, ?, ?, ?)
                    """,
                    (telegram_id, input_text, output, style)
                )

        except Exception as e:
            logger.error(f"Error saving history: {e}")
            raise

    def save_last_request(self, telegram_id: int, input_text: str, output: str, style: str):
        """Save or update last request."""
        try:
            with self.client.transaction() as tx:
                tx.execute(
                    """
                    INSERT OR REPLACE INTO last_request (telegram_id, input, output, style, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (telegram_id, input_text, output, style)
                )

        except Exception as e:
            logger.error(f"Error saving last request: {e}")
            raise

    def get_last_request(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get last request for user."""
        try:
            with self.client.transaction() as tx:
                result = tx.execute(
                    "SELECT input, output, style FROM last_request WHERE telegram_id = ?",
                    (telegram_id,)
                )

                if not result.rows:
                    return None

                row = result.rows[0]
                return {
                    "input": row[0],
                    "output": row[1],
                    "style": row[2]
                }

        except Exception as e:
            logger.error(f"Error getting last request: {e}")
            return None

    def get_history(self, telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get user history."""
        try:
            result = self.client.execute(
                """
                SELECT input, output, style, created_at 
                FROM history 
                WHERE telegram_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (telegram_id, limit)
            )

            return [
                {
                    "input": row[0],
                    "output": row[1],
                    "style": row[2],
                    "created_at": row[3]
                }
                for row in result.rows
            ]

        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []

    def clear_history(self, telegram_id: int):
        """Clear user history."""
        try:
            with self.client.transaction() as tx:
                tx.execute(
                    "DELETE FROM history WHERE telegram_id = ?",
                    (telegram_id,)
                )

        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            raise

    def get_today_stats(self, telegram_id: int) -> int:
        """Get today's request count."""
        try:
            today = datetime.now().date().isoformat()

            result = self.client.execute(
                "SELECT daily_requests FROM users WHERE telegram_id = ? AND last_request_date = ?",
                (telegram_id, today)
            )

            if not result.rows:
                return 0

            return result.rows[0][0]

        except Exception as e:
            logger.error(f"Error getting today stats: {e}")
            return 0
