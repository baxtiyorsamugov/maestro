"""
Состояния FSM.

Вынесены отдельно, потому что на них ссылаются хендлеры из разных доменов:
держать их в модуле одного домена — значит получить импорт клиентских хендлеров
из мастерских и наоборот.
"""
from aiogram.fsm.state import State, StatesGroup


class ScheduleForm(StatesGroup):
    day_of_week = State()
    start_time = State()
    end_time = State()

class SpecialDateForm(StatesGroup):
    target_date = State()
    start_time = State()
    end_time = State()

class ServiceForm(StatesGroup):
    name = State()
    price = State()
    duration = State()

class PortfolioForm(StatesGroup):
    waiting_for_photo = State()

class SearchForm(StatesGroup):
    waiting_for_name = State()

class RegistrationForm(StatesGroup):
    full_name = State()
    phone_number = State()
