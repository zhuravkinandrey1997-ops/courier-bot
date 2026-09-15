import asyncio
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery,
)
import gspread
from google.oauth2.service_account import Credentials

# Переменные окружения (задаются в Render)
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Касса Курьера")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")

# Подключение к Google Таблицам
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds_dict = json.loads(GOOGLE_CREDS_RAW)
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)
sheet = gc.open(SPREADSHEET_NAME)
ws_ops = sheet.worksheet("Операции")
ws_bal = sheet.worksheet("Баланс")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# Состояния диалога (FSM)
class ExpenseStates(StatesGroup):
    waiting_comment = State()
    waiting_currency = State()
    waiting_amount = State()


class TopUpStates(StatesGroup):
    waiting_who = State()
    waiting_currency = State()
    waiting_amount = State()


class ExchangeStates(StatesGroup):
    waiting_from_curr = State()
    waiting_from_amount = State()
    waiting_to_curr = State()
    waiting_to_amount = State()


# Главное меню
def get_main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💸 Потратил", callback_data="btn_expense"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Пополнили", callback_data="btn_topup"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обмен валюты", callback_data="btn_exchange"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Баланс кассы", callback_data="btn_balance"
                )
            ],
        ]
    )


# Выбор валюты
def get_currency_menu(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🇧🇾 BYN", callback_data=f"{prefix}_BYN"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💵 USD", callback_data=f"{prefix}_USD"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇷🇺 RUB", callback_data=f"{prefix}_RUB"
                )
            ],
        ]
    )


def get_current_balance():
    records = ws_bal.get("A2:B4")
    return {row[0]: float(row[1]) for row in records}


def update_balance_and_log(
    user_name, op_type, curr_changes, comment, timestamp
):
    for curr, amount in curr_changes.items():
        ws_ops.append_row([timestamp, user_name, op_type, curr, amount, comment])

    current = get_current_balance()
    for curr, amount in curr_changes.items():
        current[curr] = round(current.get(curr, 0.0) + amount, 2)

    update_data = [
        [current.get("BYN", 0)],
        [current.get("USD", 0)],
        [current.get("RUB", 0)],
    ]
    ws_bal.update(range_name="B2:B4", values=update_data)
    return current


def format_balance_msg(balances):
    return (
        "💼 **Остаток в кассе:**\n"
        f"• 🇧🇾 BYN: `{balances.get('BYN', 0):.2f}`\n"
        f"• 💵 USD: `{balances.get('USD', 0):.2f}`\n"
        f"• 🇷🇺 RUB: `{balances.get('RUB', 0):.2f}`"
    )


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Выберите действие с кассой:", reply_markup=get_main_menu()
    )


# --- 1. РАСХОД ---
@dp.callback_query(F.data == "btn_expense")
async def start_expense(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("📝 На что потратили? Введите комментарий:")
    await state.set_state(ExpenseStates.waiting_comment)
    await cb.answer()


@dp.message(ExpenseStates.waiting_comment)
async def expense_comment(message: Message, state: FSMContext):
    await state.update_data(comment=message.text)
    await message.answer("Выберите валюту:", reply_markup=get_currency_menu("exp_cur"))
    await state.set_state(ExpenseStates.waiting_currency)


@dp.callback_query(ExpenseStates.waiting_currency, F.data.startswith("exp_cur_"))
async def expense_currency(cb: CallbackQuery, state: FSMContext):
    curr = cb.data.split("_")[-1]
    await state.update_data(currency=curr)
    await cb.message.answer(f"Выбрана валюта: **{curr}**. Введите сумму расхода:")
    await state.set_state(ExpenseStates.waiting_amount)
    await cb.answer()


@dp.message(ExpenseStates.waiting_amount)
async def expense_finish(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        data = await state.get_data()
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        new_bal = update_balance_and_log(
            message.from_user.full_name,
            "Расход",
            {data["currency"]: -abs(amount)},
            data["comment"],
            now,
        )

        await message.answer(
            f"✅ Расход зафиксирован: -{amount} {data['currency']}\n\n{format_balance_msg(new_bal)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите сумму числом (например: 15 или 3.50):")


# --- 2. ПОПОЛНЕНИЕ ---
@dp.callback_query(F.data == "btn_topup")
async def start_topup(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer("👤 Кто пополнил кассу? Введите имя/источник:")
    await state.set_state(TopUpStates.waiting_who)
    await cb.answer()


@dp.message(TopUpStates.waiting_who)
async def topup_who(message: Message, state: FSMContext):
    await state.update_data(who=message.text)
    await message.answer("Выберите валюту:", reply_markup=get_currency_menu("top_cur"))
    await state.set_state(TopUpStates.waiting_currency)


@dp.callback_query(TopUpStates.waiting_currency, F.data.startswith("top_cur_"))
async def topup_currency(cb: CallbackQuery, state: FSMContext):
    curr = cb.data.split("_")[-1]
    await state.update_data(currency=curr)
    await cb.message.answer(f"Выбрана валюта: **{curr}**. Введите полученную сумму:")
    await state.set_state(TopUpStates.waiting_amount)
    await cb.answer()


@dp.message(TopUpStates.waiting_amount)
async def topup_finish(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        data = await state.get_data()
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        new_bal = update_balance_and_log(
            message.from_user.full_name,
            "Пополнение",
            {data["currency"]: abs(amount)},
            f"От: {data['who']}",
            now,
        )

        await message.answer(
            f"✅ Пополнение сохранено: +{amount} {data['currency']}\n\n{format_balance_msg(new_bal)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        await state.clear()
    except ValueError:
        await message.answer("Введите сумму числом:")


# --- 3. ОБМЕН ВАЛЮТЫ ---
@dp.callback_query(F.data == "btn_exchange")
async def start_exchange(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer(
        "🔄 Какую валюту вы **сдали**?",
        reply_markup=get_currency_menu("ex_from"),
        parse_mode="Markdown",
    )
    await state.set_state(ExchangeStates.waiting_from_curr)
    await cb.answer()


@dp.callback_query(
    ExchangeStates.waiting_from_curr, F.data.startswith("ex_from_")
)
async def ex_from_curr(cb: CallbackQuery, state: FSMContext):
    curr = cb.data.split("_")[-1]
    await state.update_data(from_curr=curr)
    await cb.message.answer(f"Сколько **{curr}** вы сдали?")
    await state.set_state(ExchangeStates.waiting_from_amount)
    await cb.answer()


@dp.message(ExchangeStates.waiting_from_amount)
async def ex_from_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        await state.update_data(from_amount=amount)
        await message.answer(
            "Какую валюту вы **получили** взамен?",
            reply_markup=get_currency_menu("ex_to"),
            parse_mode="Markdown",
        )
        await state.set_state(ExchangeStates.waiting_to_curr)
    except ValueError:
        await message.answer("Введите сумму числом:")


@dp.callback_query(ExchangeStates.waiting_to_curr, F.data.startswith("ex_to_"))
async def ex_to_curr(cb: CallbackQuery, state: FSMContext):
    curr = cb.data.split("_")[-1]
    await state.update_data(to_curr=curr)
    await cb.message.answer(f"Сколько **{curr}** вы получили?")
    await state.set_state(ExchangeStates.waiting_to_amount)
    await cb.answer()


@dp.message(ExchangeStates.waiting_to_amount)
async def ex_to_amount(message: Message, state: FSMContext):
    try:
        to_amount = float(message.text.replace(",", "."))
        data = await state.get_data()
        now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

        changes = {
            data["from_curr"]: -abs(data["from_amount"]),
            data["to_curr"]: abs(to_amount),
        }

        new_bal = update_balance_and_log(
            message.from_user.full_name,
            "Обмен",
            changes,
            f"Обмен {data['from_amount']} {data['from_curr']} -> {to_amount} {data['to_curr']}",
            now,
        )

        await message.answer(
            f"✅ Обмен сохранен:\n"
            f"-{data['from_amount']} {data['from_curr']} ➔ +{to_amount} {data['to_curr']}\n\n"
            f"{format_balance_msg(new_bal)}",
            parse_mode="Markdown",
            reply_markup=get_main_menu(),
        )
        await state.clear()
    except ValueError:
        await message.answer("Введите сумму числом:")


# --- 4. БАЛАНС ---
@dp.callback_query(F.data == "btn_balance")
async def check_balance(cb: CallbackQuery):
    balances = get_current_balance()
    await cb.message.answer(
        format_balance_msg(balances),
        parse_mode="Markdown",
        reply_markup=get_main_menu(),
    )
    await cb.answer()


async def main():
    print("Бот успешно запущен на Render!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
