# bot/config.py
from dotenv import load_dotenv
import os

# Загружаем переменные из .env
load_dotenv()

# Получаем токен бота
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Получаем список авторизованных пользователей (через запятую)
AUTHORIZED_USERS = set(
    int(uid.strip()) for uid in os.getenv("AUTHORIZED_USERS", "").split(",") if uid.strip()
)

# Проверяем, что токен указан
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не указан в .env")

# Airtable настройки
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY")
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")
AIRTABLE_TABLE_ID = os.getenv("AIRTABLE_TABLE_ID")
AIRTABLE_ORDERS_TABLE_ID = os.getenv("AIRTABLE_ORDERS_TABLE_ID")

# Проверяем, что всё указано
if not all([AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID, AIRTABLE_ORDERS_TABLE_ID]):
    raise ValueError("Один или несколько Airtable параметров не указаны в .env")
