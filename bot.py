import asyncio
import json
import os
from datetime import datetime
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    CallbackQuery,
)
import gspread
from google.oauth2.service_account import Credentials

BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Касса Курьера")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

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


class SearchStates(StatesGroup):
    waiting_query = State()


def get_permanent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💸 Потратил"), KeyboardButton(text="💰 Пополнили")],
            [KeyboardButton(text="🔄 Обмен валюты"), KeyboardButton(text="📊 Баланс кассы")],
            [KeyboardButton(text="🔍 Поиск по расходам")],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def get_currency_menu(prefix: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇧🇾 BYN", callback_data=f"{prefix}_BYN"),
                InlineKeyboardButton(text="💵 USD", callback_data=f"{prefix}_USD"),
                InlineKeyboardButton(text="🇷🇺 RUB", callback_data=f"{prefix}_RUB"),
            ]
        ]
    )


def get_current_balance():
    records = ws_bal.get("A2:B4")
    return {row[0]: float(row[1]) for row in records}


def update_balance_and_log(user_name, op_type, curr_changes, comment, timestamp):
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


async def notify_admin(initiator_id: int, text: str):
    if ADMIN_CHAT_ID and str(initiator_id) != str(ADMIN_CHAT_ID):
        try:
            await bot.send_message(
                chat_id=int(ADMIN_CHAT_ID), text=text, parse_mode="Markdown"
            )
        except Exception:
            pass


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Меню кассы закреплено внизу:",
        reply_markup=get_permanent_keyboard(),
    )


# --- 1. РАСХОД ---
@dp.message(F.text == "💸 Потратил")
async def start_expense(message: Message, state: FSMContext):
    await message.answer("📝 На что потратили? Введите комментарий:")
    await state.set_state(ExpenseStates.waiting_comment)


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

        res_msg = (
            f"✅ Расход зафиксирован: -{amount} {data['currency']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await message.answer(
            res_msg, parse_mode="Markdown", reply_markup=get_permanent_keyboard()
        )

        admin_text = (
            f"🔔 **Новая операция: Расход**\n"
            f"👤 Сотрудник: {message.from_user.full_name}\n"
            f"💸 Сумма: -{amount} {data['currency']}\n"
            f"📝 Причина: {data['comment']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await notify_admin(message.from_user.id, admin_text)
        await state.clear()
    except ValueError:
        await message.answer("Введите сумму числом (например: 15 или 3.50):")


# --- 2. ПОПОЛНЕНИЕ ---
@dp.message(F.text == "💰 Пополнили")
async def start_topup(message: Message, state: FSMContext):
    await message.answer("👤 Кто пополнил кассу? Введите имя/источник:")
    await state.set_state(TopUpStates.waiting_who)


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

        res_msg = (
            f"✅ Пополнение сохранено: +{amount} {data['currency']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await message.answer(
            res_msg, parse_mode="Markdown", reply_markup=get_permanent_keyboard()
        )

        admin_text = (
            f"🔔 **Новая операция: Пополнение**\n"
            f"👤 Зафиксировал: {message.from_user.full_name}\n"
            f"💰 Сумма: +{amount} {data['currency']}\n"
            f"📥 Источник: {data['who']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await notify_admin(message.from_user.id, admin_text)
        await state.clear()
    except ValueError:
        await message.answer("Введите сумму числом:")


# --- 3. ОБМЕН ВАЛЮТЫ ---
@dp.message(F.text == "🔄 Обмен валюты")
async def start_exchange(message: Message, state: FSMContext):
    await message.answer(
        "🔄 Какую валюту вы **сдали**?",
        reply_markup=get_currency_menu("ex_from"),
        parse_mode="Markdown",
    )
    await state.set_state(ExchangeStates.waiting_from_curr)


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

        res_msg = (
            f"✅ Обмен сохранен:\n"
            f"-{data['from_amount']} {data['from_curr']} ➔ +{to_amount} {data['to_curr']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await message.answer(
            res_msg, parse_mode="Markdown", reply_markup=get_permanent_keyboard()
        )

        admin_text = (
            f"🔔 **Новая операция: Обмен валюты**\n"
            f"👤 Сотрудник: {message.from_user.full_name}\n"
            f"🔄 Обмен: -{data['from_amount']} {data['from_curr']} ➔ +{to_amount} {data['to_curr']}\n\n"
            f"{format_balance_msg(new_bal)}"
        )
        await notify_admin(message.from_user.id, admin_text)
        await state.clear()
    except ValueError:
        await message.answer("Введите сумму числом:")


# --- 4. БАЛАНС ---
@dp.message(F.text == "📊 Баланс кассы")
async def check_balance(message: Message):
    balances = get_current_balance()
    await message.answer(
        format_balance_msg(balances),
        parse_mode="Markdown",
        reply_markup=get_permanent_keyboard(),
    )


# --- 5. ПОИСК ПО РАСХОДАМ ---
@dp.message(F.text == "🔍 Поиск по расходам")
async def search_start(message: Message, state: FSMContext):
    await message.answer("🔎 Введите слово или фразу для поиска по комментариям (например: `ступица`, `эвакуатор`, `такси`):", parse_mode="Markdown")
    await state.set_state(SearchStates.waiting_query)


@dp.message(SearchStates.waiting_query)
async def search_process(message: Message, state: FSMContext):
    query = message.text.strip().lower()
    await message.answer("⏳ Ищу совпадения в таблице...")

    try:
        rows = ws_ops.get_all_values()
        if len(rows) <= 1:
            await message.answer("Таблица операций пока пуста.", reply_markup=get_permanent_keyboard())
            await state.clear()
            return

        # Индексы колонок: 0-Дата, 1-Сотрудник, 2-Тип, 3-Валюта, 4-Сумма, 5-Комментарий
        results = []
        for r in rows[1:]:
            if len(r) >= 6:
                date, user, op_type, curr, amount, comment = r[0], r[1], r[2], r[3], r[4], r[5]
                if op_type == "Расход" and query in comment.lower():
                    results.append(f"📅 `{date}` | 👤 {user}\n💸 `{amount} {curr}` — {comment}")

        if not results:
            await message.answer(f"По запросу *«{message.text}»* среди расходов ничего не найдено.", parse_mode="Markdown", reply_markup=get_permanent_keyboard())
        else:
            header = f"🔍 **Результаты поиска по «{message.text}» ({len(results)} шт.):**\n\n"
            text_block = "\n\n".join(results[-20:])
            if len(results) > 20:
                text_block += f"\n\n*(показаны последние 20 из {len(results)} записей)*"
            await message.answer(header + text_block, parse_mode="Markdown", reply_markup=get_permanent_keyboard())
    except Exception as e:
        await message.answer(f"Ошибка при поиске: {e}", reply_markup=get_permanent_keyboard())

    await state.clear()


async def handle_ping(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/healthz", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()


async def main():
    await start_web_server()
    print("Бот успешно запущен на Render!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
