# bot/states.py
from aiogram.fsm.state import State, StatesGroup

class PaymentForm(StatesGroup):
    attachment = State()
    amount = State()
    note = State()
    order = State()
    order_selection = State()
