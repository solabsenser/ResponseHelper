import os
import asyncio
from libsql_client import create_client

DB = create_client(
    url=os.getenv("TURSO_DATABASE_URL"),
    auth_token=os.getenv("TURSO_AUTH_TOKEN")
)

async def init_db():

    await DB.execute("""
    CREATE TABLE IF NOT EXISTS users(
        telegram_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        daily_requests INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    await DB.execute("""
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        input TEXT,
        output TEXT,
        style TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


async def add_user(user):

    await DB.execute(
        """
        INSERT OR IGNORE INTO users(
        telegram_id,
        username,
        first_name
        )
        VALUES(?,?,?)
        """,
        [
            user.id,
            user.username,
            user.first_name
        ]
    )


async def requests_today(user_id):

    result = await DB.execute(
        "SELECT daily_requests FROM users WHERE telegram_id=?",
        [user_id]
    )

    if not result.rows:
        return 0

    return result.rows[0][0]


async def increase_requests(user_id):

    await DB.execute(
        """
        UPDATE users
        SET daily_requests=daily_requests+1
        WHERE telegram_id=?
        """,
        [user_id]
    )


async def save_history(user_id, inp, out, style):

    await DB.execute(
        """
        INSERT INTO history(
        telegram_id,
        input,
        output,
        style
        )
        VALUES(?,?,?,?)
        """,
        [
            user_id,
            inp,
            out,
            style
        ]
    )
