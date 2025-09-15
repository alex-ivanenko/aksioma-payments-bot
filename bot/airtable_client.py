# bot/airtable_client.py
import httpx
import asyncio
import logging
from typing import Dict, Any
from .config import AIRTABLE_API_KEY, AIRTABLE_BASE_ID, AIRTABLE_TABLE_ID

logger = logging.getLogger(__name__)

class AirtableClient:
    def __init__(self):
        self.base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
        self.headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

    async def create_record(self, fields: Dict[str, Any]) -> Dict:
        """
        Создаёт новую запись в Airtable с повторами при сетевых ошибках.
        """
        payload = {
            "records": [
                {
                    "fields": fields
                }
            ]
        }

        for attempt in range(3):  # Пробуем 3 раза
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(self.base_url, json=payload, headers=self.headers)
                    response.raise_for_status()
                    return response.json()

            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt == 2:  # Последняя попытка
                    raise Exception(f"Airtable не отвечает после 3 попыток: {str(e)}")
                logger.warning(f"Попытка {attempt + 1} не удалась, повтор через 1 сек: {e}")
                await asyncio.sleep(1)  # Ждём перед повтором

            except httpx.HTTPStatusError as e:
                try:
                    error_data = e.response.json()
                    if isinstance(error_data, dict):
                        error_message = error_data.get("error", {}).get("message", str(e))
                    else:
                        error_message = str(error_data)
                except Exception:
                    error_message = e.response.text or str(e)
                raise Exception(f"Airtable API Error: {error_message}")

            except Exception as e:
                raise Exception(f"Неожиданная ошибка: {str(e)}")
