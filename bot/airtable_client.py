# bot/airtable_client.py
import httpx
import asyncio
import logging
from typing import Dict, Any, List
from .config import (
    AIRTABLE_API_KEY,
    AIRTABLE_BASE_ID,
    AIRTABLE_TABLE_ID,
    AIRTABLE_ORDERS_TABLE_ID
)

logger = logging.getLogger(__name__)


class AirtableClient:
    def __init__(self):
        self.base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
        self.headers = {
            "Authorization": f"Bearer {AIRTABLE_API_KEY}",
            "Content-Type": "application/json"
        }

    async def create_record(self, fields: Dict[str, Any]) -> Dict:
        payload = {
            "records": [{"fields": fields}]
        }
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.post(self.base_url, json=payload, headers=self.headers)
                    response.raise_for_status()
                    return response.json()
            except (httpx.NetworkError, httpx.TimeoutException) as e:
                if attempt == 2:
                    raise Exception(f"Airtable не отвечает после 3 попыток: {str(e)}")
                logger.warning(f"Попытка {attempt + 1} не удалась, повтор через 1 сек: {e}")
                await asyncio.sleep(1)
            except httpx.HTTPStatusError as e:
                try:
                    error_data = e.response.json()
                    error_message = error_data.get("error", {}).get("message", str(e))
                except Exception:
                    error_message = e.response.text or str(e)
                raise Exception(f"Airtable API Error: {error_message}")
            except Exception as e:
                raise Exception(f"Неожиданная ошибка: {str(e)}")

    async def get_order_names(self) -> List[str]:
        if not AIRTABLE_ORDERS_TABLE_ID:
            raise ValueError("AIRTABLE_ORDERS_TABLE_ID не настроен")

        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_ORDERS_TABLE_ID}"
        names = []
        offset = None

        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                # Запрашиваем Name и Статус
                params = {"fields[]": ["Name", "Статус"]}
                if offset:
                    params["offset"] = offset

                response = await client.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()

                for record in data.get("records", []):
                    fields = record.get("fields", {})
                    name = fields.get("Name")
                    status = fields.get("Статус")
                    # Пропускаем, если статус "Расчет" или "Отменен"
                    if isinstance(status, str) and status.strip() in {"Расчет", "Отменен", "Отложен"}:
                        continue
                    if name and isinstance(name, str):
                        names.append(name.strip())

                offset = data.get("offset")
                if not offset:
                    break

        return names
