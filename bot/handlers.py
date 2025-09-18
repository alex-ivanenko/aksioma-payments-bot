# bot/handlers.py
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart
from .states import PaymentForm
from .config import AUTHORIZED_USERS, TELEGRAM_BOT_TOKEN
from .airtable_client import AirtableClient

router = Router()
logger = logging.getLogger(__name__)
airtable_client = AirtableClient()

# === КЛАВИАТУРЫ ===

# Главная клавиатура — после /start и в конце диалога
main_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Добавить оплату")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Клавиатура с кнопкой "Пропустить" — для опциональных шагов
skip_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пропустить")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# Клавиатура с кнопками "Пропустить" и "Отмена"
skip_cancel_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Пропустить")],
        [KeyboardButton(text="Отмена")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def is_authorized(user) -> bool:
    return user.id in AUTHORIZED_USERS

# === ХЕНДЛЕРЫ ===

# Команда /start
@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_authorized(message.from_user):
        await message.answer("🚫 У вас нет доступа к этому боту")
        return
    await message.answer(
        "Добро пожаловать!\nНажмите кнопку ниже, чтобы добавить оплату",
        reply_markup=main_kb
    )

# Обработчик кнопки "Добавить оплату" (Сценарий 2)
@router.message(F.text == "Добавить оплату")
async def start_payment_by_button(message: Message, state: FSMContext):
    if not is_authorized(message.from_user):
        await message.answer("🚫 У вас нет доступа к этому действию")
        return
    await message.answer("Добавьте вложение:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.attachment)

# Обработчик любого вложения (Сценарий 1)
@router.message(F.content_type.in_({
    ContentType.PHOTO,
    ContentType.DOCUMENT,
    ContentType.VIDEO,
    ContentType.AUDIO
}))
async def start_payment_by_attachment(message: Message, state: FSMContext, bot: Bot):
    if not is_authorized(message.from_user):
        await message.answer("🚫 У вас нет доступа к этому действию")
        return

    # Сохраняем file_id вложения
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id  # Берём фото в максимальном разрешении
    elif message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.audio:
        file_id = message.audio.file_id

    await state.update_data(attachment=file_id)
    await message.answer("Введите сумму:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.amount)

# Обработчик кнопки "Отмена"
@router.message(F.text == "Отмена")
async def handle_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного диалога", reply_markup=main_kb)
        return
    await state.clear()
    await message.answer("Диалог отменён", reply_markup=main_kb)

# Обработчик кнопки "Пропустить" на шаге вложения (Сценарий 2)
@router.message(PaymentForm.attachment, F.text == "Пропустить")
async def skip_attachment(message: Message, state: FSMContext):
    await state.update_data(attachment=None)
    await message.answer("Введите сумму:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.amount)

# Обработчик суммы
@router.message(PaymentForm.amount, F.text)
async def process_amount(message: Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(amount=None)
        await message.answer("Введите примечание:", reply_markup=skip_cancel_kb)
        await state.set_state(PaymentForm.note)
        return
    if message.text == "Отмена":
        await handle_cancel(message, state)
        return

    # Валидация суммы (можно вводить число с точкой или запятой)
    amount_text = message.text.strip().replace(",", ".")
    try:
        amount = float(amount_text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число", reply_markup=skip_cancel_kb)
        return

    await state.update_data(amount=amount)
    await message.answer("Введите примечание:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.note)

# Обработчик примечания
@router.message(PaymentForm.note, F.text)
async def process_note(message: Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(note="")
        await message.answer("Введите номер заказа:", reply_markup=skip_cancel_kb)
        await state.set_state(PaymentForm.order)
        return
    if message.text == "Отмена":
        await handle_cancel(message, state)
        return

    note_text = message.text.strip() if message.text else ""
    await state.update_data(note=note_text)
    await message.answer("Введите номер заказа:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.order)

# Обработчик заказа
@router.message(PaymentForm.order, F.text)
async def process_order(message: Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(order="")
        await _save_data_and_finish(message, state)
        return
    if message.text == "Отмена":
        await handle_cancel(message, state)
        return

    order_text = message.text.strip() if message.text else ""
    await state.update_data(order=order_text)
    await _save_data_and_finish(message, state)

# === ФУНКЦИЯ СОХРАНЕНИЯ ===

async def _save_data_and_finish(message: Message, state: FSMContext):
    """
    Сохраняет данные в Airtable и отправляет итоговое сообщение.
    """
    data = await state.get_data()
    try:
        user = message.from_user
        sender_name = user.first_name
        if user.last_name:
            sender_name += " " + user.last_name

        # --- Подготавливаем данные для Airtable ---
        fields = {
            "Отправитель": sender_name
        }
        
        # Добавляем поля в Airtable только если они не пустые
        if data.get('amount'):
            fields["Сумма"] = data.get('amount')
        if data.get('note'):
            fields["Примечание"] = data.get('note')
        if data.get('order'):
            fields["Заказ"] = data.get('order')

        # Обрабатываем вложение
        attachment_value = []
        file_id = data.get('attachment')
        if file_id:
            try:
                bot = message.bot
                file = await bot.get_file(file_id)
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file.file_path}"
                attachment_value = [{"url": file_url}]
                fields["Вложение"] = attachment_value
            except Exception as e:
                logger.error(f"Ошибка при получении ссылки на файл: {e}")

        # Отправляем в Airtable
        await airtable_client.create_record(fields)

        # --- Формируем итоговое сообщение для пользователя, исключая пустые строки ---
        result_lines = [f"✅ Запись добавлена:\n"]
        
        # Добавляем номер заказа, если он есть
        if data.get('order'):
            result_lines.append(f"<b>Заказ:</b> {data.get('order')}")
        
        # Добавляем информацию о вложении, если оно есть
        if file_id:
            result_lines.append(f"<b>Вложение:</b> 📎")
        
        # Добавляем сумму, если она есть
        if data.get('amount'):
            result_lines.append(f"<b>Сумма:</b> {data.get('amount')}")
        
        # Добавляем примечание, если оно есть
        if data.get('note'):
            result_lines.append(f"<b>Примечание:</b> {data.get('note')}")
        
        # Добавляем отправителя (всегда)
        result_lines.append(f"<b>Отправитель:</b> {sender_name}")

        # Объединяем все строки в одно сообщение
        final_message = "\n".join(result_lines)

        await message.answer(
            final_message,
            reply_markup=main_kb
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении данных: {e}", exc_info=True)
        await message.answer(
            f"Произошла ошибка при сохранении в Airtable:\n<code>{str(e)}</code>"
        )
    finally:
        await state.clear()
        

        

