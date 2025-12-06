# bot/handlers.py
import logging
from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ContentType,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, CommandStart
from rapidfuzz import process as fuzz_process, fuzz
from .states import PaymentForm
from .config import AUTHORIZED_USERS, TELEGRAM_BOT_TOKEN
from .airtable_client import AirtableClient
from .cache_manager import OrdersCache

router = Router()
logger = logging.getLogger(__name__)
airtable_client = AirtableClient()
orders_cache = OrdersCache()

# === КЛАВИАТУРЫ ===
main_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Добавить оплату")]],
    resize_keyboard=True,
    one_time_keyboard=True
)
skip_cancel_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Пропустить")],
        [KeyboardButton(text="Отмена")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

def is_authorized(user) -> bool:
    return user.id in AUTHORIZED_USERS

# === ХЕНДЛЕРЫ ===
@router.message(CommandStart())
async def cmd_start(message: Message):
    if not is_authorized(message.from_user):
        await message.answer("🚫 У вас нет доступа к этому боту")
        return
    await message.answer(
        "Добро пожаловать!\nНажмите кнопку ниже, чтобы добавить оплату",
        reply_markup=main_kb
    )

@router.message(F.text == "Добавить оплату")
async def start_payment_by_button(message: Message, state: FSMContext):
    if not is_authorized(message.from_user):
        await message.answer("🚫 У вас нет доступа к этому действию")
        return
    await message.answer("Добавьте вложение:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.attachment)

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
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id
    elif message.audio:
        file_id = message.audio.file_id
    await state.update_data(attachment=file_id)
    await message.answer("Введите сумму:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.amount)

@router.message(F.text == "Отмена")
async def handle_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Нет активного диалога", reply_markup=main_kb)
        return
    await state.clear()
    await message.answer("Диалог отменён", reply_markup=main_kb)

@router.message(PaymentForm.attachment, F.text == "Пропустить")
async def skip_attachment(message: Message, state: FSMContext):
    await state.update_data(attachment=None)
    await message.answer("Введите сумму:", reply_markup=skip_cancel_kb)
    await state.set_state(PaymentForm.amount)

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

# === ОБНОВЛЁННЫЙ ХЕНДЛЕР ЗАКАЗА ===
@router.message(PaymentForm.order, F.text)
async def process_order(message: Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(order="")
        await _save_data_and_finish(message.bot, message.from_user, state)
        return
    if message.text == "Отмена":
        await handle_cancel(message, state)
        return

    user_input_raw = message.text.strip()
    user_input_norm = user_input_raw.lower()

    if user_input_norm in {"цех", "дом", "не знаю"}:
        await state.update_data(order=user_input_raw)
        await _save_data_and_finish(message.bot, message.from_user, state)
        return

    try:
        orders_original = await orders_cache.get_orders()
        if not orders_original:
            await state.update_data(order=user_input_raw)
            await _save_data_and_finish(message.bot, message.from_user, state)
            return

        orders_lower = [name.lower() for name in orders_original]
        results = []
        
        for token in user_input_norm.split():
            matches = fuzz_process.extract(
                token,
                orders_lower,
                scorer=fuzz.partial_ratio,
                score_cutoff=80,
                limit=None
            )           

            matched_indices = {match[2] for match in matches}
            results.append(matched_indices)
        
        if not results:
            indices = set()
        else:
            indices = results[0].intersection(*results[1:]) if len(results) > 1 else results[0]

        found_orders = [orders_original[i] for i in indices]
        options = found_orders + [user_input_raw]

        buttons = []
        for opt in options:
            cb_data = f"order:{opt[:50]}"
            buttons.append([InlineKeyboardButton(text=opt, callback_data=cb_data)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        try:
            await message.answer("Выберите заказ:", reply_markup=keyboard)
            await state.update_data(order_options=options)
            await state.set_state(PaymentForm.order_selection)
        except Exception as send_error:
            logger.warning(f"Не удалось отправить выбор заказа: {send_error}")
            await state.update_data(order=user_input_raw)
            await _save_data_and_finish(message.bot, message.from_user, state)
            return

    except Exception as e:
        logger.error(f"Ошибка при поиске заказа: {e}", exc_info=True)
        await message.answer("❌ Не удалось найти заказы")
        await state.update_data(order=user_input_raw)
        await _save_data_and_finish(message.bot, message.from_user, state)

# === ХЕНДЛЕР INLINE-ВЫБОРА ===
@router.callback_query(PaymentForm.order_selection, F.data.startswith("order:"))
async def handle_order_selection(callback: CallbackQuery, state: FSMContext):
    selected = callback.data[len("order:"):]
    await state.update_data(order=selected)
    await callback.answer()
    await _save_data_and_finish(callback.bot, callback.from_user, state)

# === ФУНКЦИЯ СОХРАНЕНИЯ ===
async def _save_data_and_finish(bot: Bot, user, state: FSMContext):
    data = await state.get_data()
    try:
        sender_name = user.first_name
        if user.last_name:
            sender_name += " " + user.last_name

        fields = {"Отправитель": sender_name}
        if data.get('amount'):
            fields["Сумма"] = data.get('amount')
        if data.get('note'):
            fields["Примечание"] = data.get('note')
        if data.get('order'):
            fields["Заказ"] = data.get('order')

        attachment_value = []
        file_id = data.get('attachment')
        if file_id:
            try:
                file = await bot.get_file(file_id)
                file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file.file_path}"
                attachment_value = [{"url": file_url}]
                fields["Вложение"] = attachment_value
            except Exception as e:
                logger.error(f"Ошибка при получении ссылки на файл: {e}")

        await airtable_client.create_record(fields)

        result_lines = ["✅ Запись добавлена:\n"]
        if data.get('order'):
            result_lines.append(f"<b>Заказ:</b> {data.get('order')}")
        if file_id:
            result_lines.append(f"<b>Вложение:</b> 📎")
        if data.get('amount'):
            result_lines.append(f"<b>Сумма:</b> {data.get('amount')}")
        if data.get('note'):
            result_lines.append(f"<b>Примечание:</b> {data.get('note')}")
        result_lines.append(f"<b>Отправитель:</b> {sender_name}")

        final_message = "\n".join(result_lines)
        await bot.send_message(
            chat_id=user.id,
            text=final_message,
            reply_markup=main_kb
        )

    except Exception as e:
        logger.error(f"Ошибка при сохранении данных: {e}", exc_info=True)
        await bot.send_message(
            chat_id=user.id,
            text=f"Произошла ошибка при сохранении в Airtable:\n<code>{str(e)}</code>"
        )
    finally:
        await state.clear()
