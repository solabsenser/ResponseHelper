import logging
import json
import aiohttp
from datetime import datetime, date
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class TursoClient:
    """Turso HTTP API client"""
    
    def __init__(self, url: str, token: str):
        self.url = url.rstrip('/')
        self.token = token
        
        if self.url.startswith("libsql://"):
            self.url = self.url.replace("libsql://", "https://")
        self.url = self.url.replace(":443", "")
        logger.info(f"✅ Turso client initialized with URL: {self.url}")
    
    def _format_params(self, params):
        if not params:
            return []
        formatted = []
        for p in params:
            if p is None:
                formatted.append({"type": "null"})
            elif isinstance(p, bool):
                formatted.append({"type": "integer", "value": 1 if p else 0})
            elif isinstance(p, int):
                formatted.append({"type": "integer", "value": p})
            elif isinstance(p, float):
                formatted.append({"type": "real", "value": p})
            elif isinstance(p, (list, dict)):
                formatted.append({"type": "text", "value": json.dumps(p, ensure_ascii=False)})
            else:
                formatted.append({"type": "text", "value": str(p)})
        return formatted
    
    async def execute(self, sql: str, params: list = None):
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"
            }
            payload = {"stmt": {"sql": sql}}
            if params:
                payload["stmt"]["args"] = self._format_params(params)
            
            full_url = f"{self.url}/v1/execute"
            
            try:
                async with session.post(full_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        raise Exception(f"Turso error {resp.status}: {error}")
                    data = await resp.json()
                    if data.get("error"):
                        raise Exception(f"Turso error: {data['error']}")
                    return data
            except aiohttp.ClientError as e:
                raise Exception(f"Connection error: {e}")


def extract_value(data):
    if isinstance(data, dict) and 'value' in data:
        return data['value']
    return data


class Database:
    def __init__(self, url: str, token: str):
        self.client = TursoClient(url, token)
        self._initialized = False
    
    async def _ensure_initialized(self):
        if not self._initialized:
            await self._init_tables()
            self._initialized = True
    
    async def _init_tables(self):
        try:
            await self.client.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    daily_requests INTEGER DEFAULT 0,
                    last_request_date TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await self.client.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    input TEXT,
                    output TEXT,
                    style TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await self.client.execute("""
                CREATE TABLE IF NOT EXISTS last_request (
                    telegram_id INTEGER PRIMARY KEY,
                    input TEXT,
                    output TEXT,
                    style TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            logger.info("✅ Database tables initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    async def get_or_create_user(self, telegram_id: int, username: Optional[str] = None, first_name: Optional[str] = None):
        await self._ensure_initialized()
        
        try:
            result = await self.client.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            
            rows = result.get('result', {}).get('rows', [])
            
            if not rows:
                await self.client.execute(
                    """
                    INSERT INTO users (telegram_id, username, first_name, daily_requests, last_request_date)
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    (telegram_id, username, first_name, None)
                )
                return {
                    "telegram_id": telegram_id,
                    "username": username,
                    "first_name": first_name,
                    "daily_requests": 0,
                    "last_request_date": None
                }
            
            row = rows[0]
            if isinstance(row, (list, tuple)):
                return {
                    "telegram_id": extract_value(row[0]),
                    "username": extract_value(row[1]),
                    "first_name": extract_value(row[2]),
                    "daily_requests": extract_value(row[3]) or 0,
                    "last_request_date": extract_value(row[4])
                }
            elif isinstance(row, dict):
                return {
                    "telegram_id": extract_value(row.get('telegram_id')),
                    "username": extract_value(row.get('username')),
                    "first_name": extract_value(row.get('first_name')),
                    "daily_requests": extract_value(row.get('daily_requests')) or 0,
                    "last_request_date": extract_value(row.get('last_request_date'))
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting/creating user: {e}")
            raise
    
    async def check_daily_limit(self, telegram_id: int) -> tuple[bool, int]:
        """Check if user has reached daily limit."""
        await self._ensure_initialized()
        
        try:
            today = date.today().isoformat()
            
            result = await self.client.execute(
                "SELECT daily_requests, last_request_date FROM users WHERE telegram_id = ?",
                (telegram_id,)
            )
            
            rows = result.get('result', {}).get('rows', [])
            
            if not rows:
                # Пользователь не найден - создаем нового
                await self.get_or_create_user(telegram_id)
                return True, 0
            
            row = rows[0]
            if isinstance(row, (list, tuple)):
                daily_requests = extract_value(row[0]) or 0
                last_request_date = extract_value(row[1])
            else:
                daily_requests = extract_value(row.get('daily_requests')) or 0
                last_request_date = extract_value(row.get('last_request_date'))
            
            logger.info(f"User {telegram_id}: daily_requests={daily_requests}, last_request_date={last_request_date}, today={today}")
            
            # Если last_request_date None или отличается от сегодня - сбрасываем
            if last_request_date is None or last_request_date != today:
                await self.client.execute(
                    "UPDATE users SET daily_requests = 0, last_request_date = ? WHERE telegram_id = ?",
                    (today, telegram_id)
                )
                return True, 0
            
            can_proceed = daily_requests < 50
            return can_proceed, daily_requests
            
        except Exception as e:
            logger.error(f"Error checking daily limit: {e}")
            return True, 0  # В случае ошибки разрешаем запрос
    
    async def increment_daily_requests(self, telegram_id: int):
        await self._ensure_initialized()
        
        try:
            today = date.today().isoformat()
            
            await self.client.execute(
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
    
    async def save_history(self, telegram_id: int, input_text: str, output: str, style: str):
        await self._ensure_initialized()
        
        try:
            await self.client.execute(
                """
                INSERT INTO history (telegram_id, input, output, style)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, input_text, output, style)
            )
            
        except Exception as e:
            logger.error(f"Error saving history: {e}")
            raise
    
    async def save_last_request(self, telegram_id: int, input_text: str, output: str, style: str):
        await self._ensure_initialized()
        
        try:
            await self.client.execute(
                """
                INSERT OR REPLACE INTO last_request (telegram_id, input, output, style, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (telegram_id, input_text, output, style)
            )
            
        except Exception as e:
            logger.error(f"Error saving last request: {e}")
            raise
    
    async def get_last_request(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        await self._ensure_initialized()
        
        try:
            result = await self.client.execute(
                "SELECT input, output, style FROM last_request WHERE telegram_id = ?",
                (telegram_id,)
            )
            
            rows = result.get('result', {}).get('rows', [])
            
            if not rows:
                return None
            
            row = rows[0]
            if isinstance(row, (list, tuple)):
                return {
                    "input": extract_value(row[0]),
                    "output": extract_value(row[1]),
                    "style": extract_value(row[2])
                }
            else:
                return {
                    "input": extract_value(row.get('input')),
                    "output": extract_value(row.get('output')),
                    "style": extract_value(row.get('style'))
                }
            
        except Exception as e:
            logger.error(f"Error getting last request: {e}")
            return None
    
    async def get_history(self, telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        await self._ensure_initialized()
        
        try:
            result = await self.client.execute(
                """
                SELECT input, output, style, created_at 
                FROM history 
                WHERE telegram_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (telegram_id, limit)
            )
            
            rows = result.get('result', {}).get('rows', [])
            
            history = []
            for row in rows:
                if isinstance(row, (list, tuple)):
                    history.append({
                        "input": extract_value(row[0]),
                        "output": extract_value(row[1]),
                        "style": extract_value(row[2]),
                        "created_at": extract_value(row[3])
                    })
                elif isinstance(row, dict):
                    history.append({
                        "input": extract_value(row.get('input')),
                        "output": extract_value(row.get('output')),
                        "style": extract_value(row.get('style')),
                        "created_at": extract_value(row.get('created_at'))
                    })
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting history: {e}")
            return []
    
    async def clear_history(self, telegram_id: int):
        await self._ensure_initialized()
        
        try:
            await self.client.execute(
                "DELETE FROM history WHERE telegram_id = ?",
                (telegram_id,)
            )
            
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            raise
    
    async def get_today_stats(self, telegram_id: int) -> int:
        await self._ensure_initialized()
        
        try:
            today = date.today().isoformat()
            
            result = await self.client.execute(
                "SELECT daily_requests FROM users WHERE telegram_id = ? AND last_request_date = ?",
                (telegram_id, today)
            )
            
            rows = result.get('result', {}).get('rows', [])
            
            if not rows:
                return 0
            
            row = rows[0]
            if isinstance(row, (list, tuple)):
                return extract_value(row[0]) or 0
            else:
                return extract_value(row.get('daily_requests')) or 0
            
        except Exception as e:
            logger.error(f"Error getting today stats: {e}")
            return 0