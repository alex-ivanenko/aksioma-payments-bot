# bot/states.py
from aiogram.fsm.state import State, StatesGroup

class PaymentForm(StatesGroup):
    attachment = State()  # Вложение (фото, документ и т.д.)
    amount = State()      # Сумма
    note = State()        # Примечание
    order = State()       # Номер заказа
