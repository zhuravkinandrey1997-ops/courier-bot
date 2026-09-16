import telebot
from telebot import types
import requests
import json
import re
import os
import time
import calendar
from datetime import datetime, timedelta
import pytz
from flask import Flask, request
import cv2
import numpy as np

# --- КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = "8868238188:AAHDc03-iHiBZ8lMQQeSnLAGv8Yx12CQTmQ"
RENDER_APP_URL = "https://telegram-bot-vvcm.onrender.com"
GOOGLE_SHEET_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxyAuIe6TDf6thnua95YKmJt8Pg7DWfASal1Gr-rc4v9-ePee9AGFL84zxOfBvsJCF4vQ/exec"

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

CHAT_A_ID = -1004402573147    # Чат А (входящие фото)
CHAT_B_ID = -1003907319710    # Чат Б (Диспетчер 1 - Алина)
CHAT_B2_ID = -1004301816476   # Чат Б-2 (Диспетчер 2 - Настя)
CHAT_C_ID = -1004393379168    # Кремль (распределение агентам)
CHAT_D_ID = -1004303017205    # Чат Г (отчеты и результаты)

# Администраторы маршрутизации
ALLOWED_ROUTE_MANAGERS = ["andreyzhuravkin", "ms_ksunchik", "dred_rock"]
ALLOWED_ADMIN_IDS = [661842368]

MANAGERS = ["ms_ksunchik", "alinrasp", "andreyzhuravkin"]
DISTRIBUTORS = ["ms_ksunchik", "andreyzhuravkin"]
DISTRIBUTOR_IDS = [661842368]

KSENIA_CHAT_ID = None

BUTTON_TTL_CHAT_B_SECONDS = 8 * 60 * 60
BUTTON_TTL_AGENT_SECONDS = 3 * 24 * 60 * 60

AGENTS = {
    "Андрей": [661842368, "@AndreyZhuravkin", "+79990000000"],
    "Ксюша": [None, "@ms_ksunchik", "+79990000001"],
    "Вика": [628275396, "@vika_agent", "+79119359988"],
    "Дима": [5312674822, "@DimaSpidi", "+79111369987"],
    "Люба": [966288385, "@Liuba_ava", "+79312524418"],
    "Жанна": [None, "@zhanna_agent", "+79964995339"],
    "Лёша": [1462253337, "@Kristallik_ink", "+79650665666"]
}

BOARD_MSG_FILE = "board_msg_id.txt"
def save_board_msg_id(msg_id):
    try:
        with open(BOARD_MSG_FILE, "w") as f:
            f.write(str(msg_id))
    except Exception:
        pass

def get_board_msg_id():
    if os.path.exists(BOARD_MSG_FILE):
        try:
            with open(BOARD_MSG_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None

ROUTE_MSG_FILE = "route_board_msg_id.txt"
def save_route_board_msg_id(msg_id):
    try:
        with open(ROUTE_MSG_FILE, "w") as f:
            f.write(str(msg_id))
    except Exception:
        pass

def get_route_board_msg_id():
    if os.path.exists(ROUTE_MSG_FILE):
        try:
            with open(ROUTE_MSG_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return None

ROUTING_FILE = "dispatch_route.txt"

def get_dispatch_route():
    if os.path.exists(ROUTING_FILE):
        try:
            with open(ROUTING_FILE, "r") as f:
                route = f.read().strip()
                if route in ["b1", "b2", "all"]:
                    return route
        except Exception:
            pass
    return "b1"

def set_dispatch_route(route):
    try:
        with open(ROUTING_FILE, "w") as f:
            f.write(route)
    except Exception:
        pass

def is_route_manager(user_id, username):
    u = (username or "").lstrip('@').lower()
    return (user_id in ALLOWED_ADMIN_IDS) or (u in [m.lower() for m in ALLOWED_ROUTE_MANAGERS])

# --- СТАЦИОНАРНОЕ МЕНЮ ВНИЗУ ЧАТА А ---
def get_chat_a_bottom_keyboard():
    route = get_dispatch_route()
    b1_icon = "🟢" if route == "b1" else "⚪️"
    b2_icon = "🟢" if route == "b2" else "⚪️"
    all_icon = "🟢" if route == "all" else "⚪️"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.row(
        types.KeyboardButton(f"{b1_icon} Диспетчер 1 (Чат Б)"),
        types.KeyboardButton(f"{b2_icon} Диспетчер 2 (Чат Б-2)")
    )
    markup.row(
        types.KeyboardButton(f"{all_icon} Оба диспетчера (параллельно)")
    )
    markup.row(
        types.KeyboardButton("🔄 Обновить меню")
    )
    return markup

@bot.message_handler(commands=['id'])
def handle_show_id(message):
    bot.reply_to(
        message, 
        f"📍 **Данные чата:**\n• Имя: `{message.chat.title or message.chat.first_name}`\n• Chat ID: `{message.chat.id}`\n• Тип: `{message.chat.type}`", 
        parse_mode="Markdown"
    )

@bot.message_handler(commands=['test_b2'])
def handle_test_b2(message):
    try:
        sent = bot.send_message(CHAT_B2_ID, "🔔 Тестовое оповещение: соединение с Чатом Б-2 успешно установлено!")
        bot.reply_to(message, f"✅ Успешно доставлено в Чат Б-2 (ID: `{CHAT_B2_ID}`)\nID сообщения: {sent.message_id}", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка отправки в Чат Б-2 (ID: `{CHAT_B2_ID}`):\n`{e}`", parse_mode="Markdown")

LEADS_FILE = "leads_db.json"
def load_leads_db():
    if os.path.exists(LEADS_FILE):
        try:
            with open(LEADS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_lead_to_db(lead_key, lead_info):
    db = load_leads_db()
    info_to_save = {k: v for k, v in lead_info.items() if k != 'image_bytes'}
    db[str(lead_key)] = info_to_save
    lead_num = str(info_to_save.get('lead_num', ''))
    if lead_num:
        db[f"num_{lead_num}"] = info_to_save
    try:
        with open(LEADS_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_lead_by_key_or_num(key):
    db = load_leads_db()
    if str(key) in db:
        return db[str(key)]
    if f"num_{key}" in db:
        return db[f"num_{key}"]
    return None

def find_agent_name_by_user(user_id, username):
    username_clean = (username or "").lstrip('@').lower().replace('ё', 'е')
    for name, data in AGENTS.items():
        if data[0] == user_id:
            return name
        if data[1] and data[1].lstrip('@').lower().replace('ё', 'е') == username_clean:
            return name
    return None

def get_lead_or_reconstruct(lead_id, message):
    lead = get_lead_by_key_or_num(lead_id)
    if lead:
        return lead

    text = (message.caption or message.text or "")
    lead_num_m = re.search(r'№(\d+)', text)
    addr_m = re.search(r'Адрес:\s*(.*?)(?=\n|👤|📞|$)', text, re.DOTALL)
    if not addr_m:
        addr_m = re.search(r'в работу:\s*\n?(.*?)(?=\n|Кто берет|$)', text, re.DOTALL)

    fio_m = re.search(r'ФИО:\s*(.*?)(?=\n|📞|📍|$)', text)
    phone_m = re.search(r'(\+7\d{10}|\+?7[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2})', text)

    photo_id = message.photo[-1].file_id if message.photo else None

    reconstructed = {
        'lead_num': lead_num_m.group(1) if lead_num_m else "1",
        'address': addr_m.group(1).strip() if addr_m else "Адрес из сообщения",
        'fio': fio_m.group(1).strip() if fio_m else "Не указано",
        'phone': phone_m.group(1).strip() if phone_m else "-",
        'photo_file_id': photo_id,
        'assigned_agent': None,
        'agent_phone': "-",
        'dispatcher_name': "Алина",
        'created_at': message.date
    }
    save_lead_to_db(lead_id, reconstructed)
    return reconstructed

pending_mimo_reasons = {}
pending_manual_leads = {}

LOCAL_STATUS_FILE = "agent_statuses.json"

def fetch_statuses_from_cloud():
    try:
        res = requests.get(f"{GOOGLE_SHEET_WEBHOOK_URL}?action=get_statuses", timeout=8)
        if res.status_code == 200:
            cloud_statuses = res.json()
            if isinstance(cloud_statuses, dict) and cloud_statuses:
                with open(LOCAL_STATUS_FILE, "w", encoding="utf-8") as f:
                    json.dump(cloud_statuses, f, ensure_ascii=False, indent=2)
                return cloud_statuses
    except Exception as e:
        print(f"⚠️ Ошибка загрузки статусов: {e}")
    return None

def load_agent_statuses():
    if os.path.exists(LOCAL_STATUS_FILE):
        try:
            with open(LOCAL_STATUS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if saved:
                    return saved
        except Exception:
            pass

    cloud = fetch_statuses_from_cloud()
    if cloud:
        return cloud

    return {name: False for name in AGENTS.keys()}

def save_agent_status(agent_name, is_active):
    statuses = load_agent_statuses()
    statuses[agent_name] = is_active
    try:
        with open(LOCAL_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(statuses, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        payload = {"action": "toggle_status", "agent_name": agent_name, "is_active": is_active}
        requests.post(GOOGLE_SHEET_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, allow_redirects=True, timeout=8)
    except Exception as e:
        print(f"Ошибка сохранения статуса: {e}")

def broadcast_status_change(changed_agent_name, is_active):
    statuses = load_agent_statuses()
    status_str = "🟢 вышел(ла) на смену" if is_active else "🔴 ушел(ла) со смены"
    
    lines = [
        f"📢 Смена статуса: Агент {changed_agent_name} {status_str}.\n",
        "📊 АКТУАЛЬНЫЙ СОСТАВ СМЕНЫ:"
    ]
    for name, data in AGENTS.items():
        st = statuses.get(name, False)
        icon = "🟢 На смене" if st else "🔴 Занят / Не работает"
        lines.append(f"• {name} ({data[1]}): {icon}")
    
    msg_text = "\n".join(lines)
    for name, data in AGENTS.items():
        if data[0]:
            try:
                bot.send_message(data[0], msg_text)
            except Exception:
                pass

def refresh_pinned_board():
    board_id = get_board_msg_id()
    if board_id:
        try:
            text, markup = render_status_board()
            bot.edit_message_text(text, CHAT_C_ID, board_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass

def refresh_route_board():
    board_id = get_route_board_msg_id()
    if board_id:
        try:
            text, markup = render_routing_menu()
            bot.edit_message_text(text, CHAT_A_ID, board_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass

ADDRESS_LOG_FILE = "known_addresses.json"

def check_address_repetition(address):
    if not address or address == "Не распознан":
        return False
    norm_addr = re.sub(r'\b(кв|комн|этаж)\b.*', '', address.lower()).strip()
    history = {}
    if os.path.exists(ADDRESS_LOG_FILE):
        try:
            with open(ADDRESS_LOG_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}
            
    count = history.get(norm_addr, 0)
    history[norm_addr] = count + 1
    
    try:
        with open(ADDRESS_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
        
    return count >= 1

COUNTER_FILE = "counter.txt"

def read_local_counter():
    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return 0

GLOBAL_LEAD_COUNTER = read_local_counter()

def sync_counter_from_cloud():
    global GLOBAL_LEAD_COUNTER
    try:
        res = requests.get(f"{GOOGLE_SHEET_WEBHOOK_URL}?action=get_counter", timeout=6)
        if res.status_code == 200:
            val = res.json().get("counter")
            if val and int(val) > GLOBAL_LEAD_COUNTER:
                GLOBAL_LEAD_COUNTER = int(val)
                with open(COUNTER_FILE, "w") as f:
                    f.write(str(GLOBAL_LEAD_COUNTER))
    except Exception as e:
        print(f"Ошибка синхронизации счетчика: {e}")

def get_next_lead_number():
    global GLOBAL_LEAD_COUNTER
    try:
        payload = {"action": "increment_counter"}
        res = requests.post(GOOGLE_SHEET_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, allow_redirects=True, timeout=5)
        if res.status_code == 200:
            val = res.json().get("lead_num")
            if val:
                val = int(val)
                if val > GLOBAL_LEAD_COUNTER:
                    GLOBAL_LEAD_COUNTER = val
                else:
                    GLOBAL_LEAD_COUNTER += 1
                with open(COUNTER_FILE, "w") as f:
                    f.write(str(GLOBAL_LEAD_COUNTER))
                return GLOBAL_LEAD_COUNTER
    except Exception as e:
        print(f"Ошибка increment_counter: {e}")

    if GLOBAL_LEAD_COUNTER <= 0:
        sync_counter_from_cloud()
        if GLOBAL_LEAD_COUNTER <= 0:
            GLOBAL_LEAD_COUNTER = 125
            
    GLOBAL_LEAD_COUNTER += 1
    try:
        with open(COUNTER_FILE, "w") as f:
            f.write(str(GLOBAL_LEAD_COUNTER))
    except Exception:
        pass
    return GLOBAL_LEAD_COUNTER

def export_to_google_sheet(agent_name, lead_num, status, phone, address, fio, reason="-"):
    if not GOOGLE_SHEET_WEBHOOK_URL or "ВСТАВЬТЕ_СЮДА" in GOOGLE_SHEET_WEBHOOK_URL:
        return
    try:
        msk_time = datetime.now(pytz.timezone('Europe/Moscow')).strftime("%d.%m.%Y %H:%M")
        payload = {
            "agent_name": agent_name,
            "lead_num": str(lead_num),
            "status": status,
            "phone": str(phone),
            "address": str(address),
            "fio": str(fio),
            "reason": str(reason),
            "datetime": msk_time
        }
        res = requests.post(GOOGLE_SHEET_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, allow_redirects=True, timeout=15)
        print(f"📊 Экспорт в лист '{agent_name}' (Заявка №{lead_num}): {res.status_code}")
    except Exception as e:
        print(f"Ошибка выгрузки в Google Sheets: {e}")

CITY_REPLACEMENTS = {
    r'(?i)[кр][оа]н[іишга-я]+': 'Кронштадт', r'(?i)ронітадт': 'Кронштадт',
    r'(?i)ронштадт': 'Кронштадт', r'(?i)петер[гв]оф': 'Петергоф',
    r'(?i)пушкин\w*': 'Пушкин', r'(?i)колпино': 'Колпино',
    r'(?i)сестрорецк': 'Сестрорецк', r'(?i)приморск\w*': 'Приморский',
    r'(?i)выборгск\w*': 'Выборгский', r'(?i)калин\w*': 'Калининский',
    r'(?i)кировск\w*': 'Кировский',
    r'(?i)кр[\s\-]*сельск\w*': 'Красносельский',
    r'(?i)красносельск\w*': 'Красносельский',
    r'(?i)красногвардейск\w*': 'Красногвардейский'
}

def clean_address(raw_addr):
    if not raw_addr or raw_addr == "Не распознан":
        return raw_addr

    addr = raw_addr
    for pattern, proper_city in CITY_REPLACEMENTS.items():
        addr = re.sub(pattern, proper_city, addr)

    addr = re.sub(r'(?i)\b(?:деупжина|сеупжина|деупкина)\b', 'Савушкина', addr)
    addr = re.sub(r'(?i)\bхрустицк\w*\b', 'Танкиста Хрустицкого', addr)
    addr = re.sub(r'(?i)\bголик\w*\b', 'Лени Голикова', addr)
    addr = re.sub(r'(?i)\bлитке\b', 'Литке', addr)
    addr = re.sub(r'(?i)\bсоболевск\w*\b', 'Соболевская', addr)
    addr = re.sub(r'(?i)\bалександровск\w*\b', 'Александровская', addr)
    addr = re.sub(r'(?i)\bбольшевик\w*\b', 'Большевиков', addr)
    addr = re.sub(r'(?i)\bмаршал\w*\s+жуков\w*\b', 'Маршала Жукова', addr)
    addr = re.sub(r'(?i)\bленин\w*\b', 'Ленина', addr)
    addr = re.sub(r'(?i)\bбайконурск\w*\b', 'Байконурская', addr)
    addr = re.sub(r'(?i)\bленск\w*\b', 'Ленская', addr)

    addr = re.sub(r'(?i)петербургск\w*\s+[иu]\b', 'Петербургское ш.', addr)
    addr = re.sub(r'(?i)\b[иu]\s+[лl]\b', 'ш. д.', addr)
    addr = re.sub(r'(?i)\bдор\.?\b', 'дорога', addr)
    addr = re.sub(r'(?i)\bпр[\s\-]*(?:кт|к)\b', 'пр-кт', addr)

    addr = re.sub(r'(?i)[дdлl]\s*[\.№N#ºоo]?\s*(\d+)', r'д.№ \1', addr)
    addr = re.sub(r'[уy][вbіi1!|]+\.?\s*[дd]?\.?\s*№?', 'ул. д.№ ', addr, flags=re.IGNORECASE)
    addr = re.sub(r'(?:ул\.?\s*){2,}', 'ул. ', addr, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', addr).strip()

def clean_fio(raw_fio):
    if not raw_fio or raw_fio == "Не распознано":
        return raw_fio
    fio = re.sub(r'[^а-яА-ЯёЁ\s]', '', raw_fio)
    return re.sub(r'\s+', ' ', fio).strip()

def parse_raw_text(full_text):
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    fio = "Не распознано"
    address = "Не распознан"
    phone = "-"
    district = ""

    phone_match = re.search(r'(?:\+?7|8)?[\s\-]?\(?(\d{3})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})', full_text)
    if phone_match:
        phone = f"+7{''.join(phone_match.groups())}"
    else:
        mob_digits = re.search(r'\b(9\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2})\b', full_text)
        if mob_digits:
            phone = f"+7{re.sub(r'\D', '', mob_digits.group(1))}"
        else:
            raw_ten = re.search(r'\b(9\d{9})\b', full_text)
            if raw_ten:
                phone = f"+7{raw_ten.group(1)}"
            else:
                landline = re.search(r'\b([2-8]\d{2}[\s\-]?\d{2}[\s\-]?\d{2})\b', full_text)
                if landline:
                    phone = f"+7812{re.sub(r'\D', '', landline.group(1))}"

    district_idx = -1
    for idx, line in enumerate(lines):
        l = line.lower()
        if any(r in l for r in ['приморский', 'выборгский', 'калининский', 'кировский', 'красногвардейский', 'красносельский', 'кр-сельск', 'московский', 'невский', 'петроградский', 'петергоф', 'крон', 'роні', 'пушкин', 'колпино', 'курортн']):
            if "корпус" not in l and "кв" not in l and "ул" not in l and "дор" not in l and "ш" not in l and "пр" not in l:
                district = line.strip()
                district_idx = idx
                break

    address_keywords = [
        'корпус', 'кв.', 'кв ', 'д. №', 'д.№', 'д.n', 'д. n', 'л.n', 'л.№', 'петербургск',
        'большевик', 'жуков', 'маршал', 'ленин', 'красное село', 'байконурск', 'ленск', 'литке', 
        'савушкина', 'хрустицк', 'голик', 'разведчика', 'бульвар', 'ул', 'дор', 'дорог', 
        'шоссе', 'проспект', 'просп', 'пр-кт', 'переулок', 'пер.', 'линия', 'аллея', 
        'тракт', 'проезд', 'частный дом', 'дом', 'александровск'
    ]

    for line in lines:
        l = line.lower()
        if any(k in l for k in address_keywords) or re.search(r'\b[дdлl]\s*[\.№n#º]?\s*\d+', l):
            if not any(stop in l for stop in ['время', 'полиция', '2026', 'заявка', 'милицейская', 'отдел', 'госпитальная', 'екатерининский', 'морг']):
                address = line
                break

    if address == "Не распознан" and district_idx != -1 and district_idx + 1 < len(lines):
        candidate = lines[district_idx + 1]
        if not any(stop in candidate.lower() for stop in ['время', 'полиция', 'морг', 'отдел', 'екатерининский']):
            address = candidate

    if address != "Не распознан":
        address = clean_address(address)
        if district:
            district_clean = clean_address(district)
            if district_clean.lower() not in address.lower():
                address = f"{district_clean}, {address}"

    blacklist = [
        'ПОЛИЦИЯ', 'ТЕЛЕФОН', 'ВЫЗОВ', 'ОТДЕЛ', 'КАРТОЧКА', 'СМП', 'МИЛИЦЕЙСКАЯ',
        'ЛНЕН', 'ПОЛН', 'ВЫПОЛН', 'ЗАЯВК', 'ЗАЯ', 'ДЕЖУРНЫЙ', 'ВРЕМЯ', 'БАХИЛЫ',
        'ОБРАБОТКА', 'ЗАКРЫТЬ', 'РЕГИСТРАЦИЯ', 'КРОНШТАДТ', 'РОНІТАДТ', 'ПРИМОРСКИЙ', 
        'ПЕТЕРГОФ', 'МУЖ', 'ЖЕН', 'ЛИТКЕ', 'САВУШКИНА', 'РАЗВЕДЧИКА', 'ВОДИТЕЛЬ', 'ПЕРЕДАЧИ',
        'ПЮЛНЕНИИ', 'ЯПЮЛНЕНИИ', 'ГЮЛНЕНИИ', 'ОЛЮЛНЕНИИ', 'ЛНЕНИИ', 'ПУШКИН', 'НЕВСКИЙ', 
        'БОЛЬШЕВИКОВ', 'КИРОВСКИЙ', 'ЕКАТЕРИНИНСКИЙ', 'ПЕТРОСЯН', 'КРАСНОЕ', 'КРАСНОСЕЛЬСКИЙ', 
        'ШИЛО', 'БАЙКОНУРСКАЯ', 'ЛЕНСКАЯ', 'КРАСНОГВАРДЕЙСКИЙ'
    ]
    
    for line in lines[:12]:
        norm_line = line.replace('6', 'Б').replace('b', 'Б').replace('3', 'З').replace('0', 'О')
        upper_line = norm_line.upper()
        if any(bad in upper_line for bad in blacklist):
            continue
        fio_match = re.search(r'([А-ЯЁ]{3,}\s+[А-ЯЁ]{1,2}\.?\s?[А-ЯЁ]?\.?)', upper_line)
        if fio_match:
            cand = fio_match.group(1).strip()
            clean_cand = clean_fio(cand)
            if len(clean_cand.replace(' ', '')) >= 5 and not any(bad in clean_cand.upper() for bad in blacklist):
                fio = clean_cand
                break

    return {"fio": fio, "address": address, "phone": phone}

def preprocess_and_compress_image(image_bytes):
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        h, w = img.shape[:2]
        if w > 1600:
            scale = 1600.0 / w
            img = cv2.resize(img, (1600, int(h * scale)), interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)

        quality = 85
        while quality >= 40:
            _, encoded = cv2.imencode('.jpg', contrast, [cv2.IMWRITE_JPEG_QUALITY, quality])
            raw_bytes = encoded.tobytes()
            if len(raw_bytes) < 850 * 1024:
                return raw_bytes
            quality -= 10

        return raw_bytes
    except Exception as e:
        print(f"Image Preprocessing Error: {e}")
        return image_bytes

def extract_card_data(image_bytes):
    processed_bytes = preprocess_and_compress_image(image_bytes)

    try:
        url = "https://api.ocr.space/parse/image"
        payload = {'apikey': 'K88998188888957', 'language': 'rus', 'isOverlayRequired': False, 'detectOrientation': True, 'scale': True, 'OCREngine': 1}
        files = {'file': ('card.jpg', processed_bytes, 'image/jpeg')}
        res = requests.post(url, data=payload, files=files, timeout=25)
        data = res.json()
        parsed_results = data.get("ParsedResults", [])
        if parsed_results and parsed_results[0].get("ParsedText"):
            parsed = parse_raw_text(parsed_results[0].get("ParsedText"))
            if parsed["address"] != "Не распознан" or parsed["fio"] != "Не распознано":
                return parsed
    except Exception as e:
        print(f"OCR Error 1: {e}")

    try:
        url2 = "https://api.ocr.space/parse/image"
        payload2 = {'apikey': 'helloworld', 'language': 'rus', 'isOverlayRequired': False, 'OCREngine': 2}
        files2 = {'file': ('card.jpg', processed_bytes, 'image/jpeg')}
        res2 = requests.post(url2, data=payload2, files=files2, timeout=25)
        data2 = res2.json()
        parsed_results2 = data2.get("ParsedResults", [])
        if parsed_results2 and parsed_results2[0].get("ParsedText"):
            return parse_raw_text(parsed_results2[0].get("ParsedText"))
    except Exception as e:
        print(f"OCR Error 2: {e}")

    return {"fio": "Не распознано", "address": "Не распознан", "phone": "-"}

def render_status_board():
    statuses = load_agent_statuses()
    lines = ["📊 **АКТУАЛЬНЫЙ СОСТАВ СМЕНЫ:**\n"]
    for name, data in AGENTS.items():
        is_active = statuses.get(name, False)
        status_text = "🟢 На смене" if is_active else "🔴 Занят / Не работает"
        lines.append(f"• **{name}** ({data[1]}): {status_text}")
    lines.append("\n_Нажмите на имя ниже для переключения статуса:_")
    text = "\n".join(lines)

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for name in AGENTS.keys():
        is_active = statuses.get(name, False)
        icon = "🟢" if is_active else "🔴"
        buttons.append(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"toggle_{name}"))
    markup.add(*buttons)
    return text, markup

def get_agent_persistent_keyboard(agent_name=None):
    statuses = load_agent_statuses()
    is_on_duty = statuses.get(agent_name, False) if agent_name else False
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    status_btn = types.KeyboardButton("🔴 Уйти со смены" if is_on_duty else "🟢 Выйти на смену")
    add_btn = types.KeyboardButton("✍️ Внести заявку вручную")
    stats_btn = types.KeyboardButton("📊 Отчеты и статистика")
    check_btn = types.KeyboardButton("👥 Состав смены")
    
    markup.add(status_btn, add_btn)
    markup.add(stats_btn, check_btn)
    return markup

def render_routing_menu():
    route = get_dispatch_route()
    d1_icon = "🟢" if route == "b1" else "⚪️"
    d2_icon = "🟢" if route == "b2" else "⚪️"
    all_icon = "🔀" if route == "all" else "⚪️"

    mode_titles = {
        "b1": "Только Диспетчер 1 (Чат Б)",
        "b2": "Только Диспетчер 2 (Чат Б-2)",
        "all": "Оба диспетчера (параллельно)"
    }

    text = (
        "🔀 **МАРШРУТИЗАЦИЯ ВХОДЯЩИХ ЗАЯВОК (ИЗ ЧАТА А):**\n\n"
        f"Текущий режим: **{mode_titles.get(route, 'Не определен')}**\n\n"
        "Нажмите кнопку для переключения потока заявок:"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton(f"{d1_icon} Только Диспетчер 1 (Чат Б)", callback_data="route_b1"),
        types.InlineKeyboardButton(f"{d2_icon} Только Диспетчер 2 (Чат Б-2)", callback_data="route_b2"),
        types.InlineKeyboardButton(f"{all_icon} Оба диспетчера (параллельно)", callback_data="route_all")
    )
    return text, markup

# --- ОБРАБОТКА НАЖАТИЯ СТАЦИОНАРНЫХ КНОПОК В ЧАТЕ А ---
@bot.message_handler(func=lambda msg: msg.chat.id == CHAT_A_ID and any(k in (msg.text or "") for k in ["Диспетчер 1", "Диспетчер 2", "Оба диспетчера", "Обновить меню"]))
def handle_chat_a_bottom_buttons(message):
    if not is_route_manager(message.from_user.id, message.from_user.username):
        bot.reply_to(message, "⛔ Управлять могут только @AndreyZhuravkin, @ms_ksunchik и @dred_rock")
        return

    text = message.text
    if "Обновить меню" in text:
        route_text = "🔄 Меню обновлено."
    elif "Диспетчер 1" in text:
        set_dispatch_route("b1")
        route_text = "🟢 Включен режим: **Только Диспетчер 1 (Чат Б)**"
    elif "Диспетчер 2" in text:
        set_dispatch_route("b2")
        route_text = "🟢 Включен режим: **Только Диспетчер 2 (Чат Б-2)**"
    else:
        set_dispatch_route("all")
        route_text = "🔀 Включен режим: **Оба диспетчера (параллельно)**"

    refresh_route_board()
    kb = get_chat_a_bottom_keyboard()
    bot.send_message(CHAT_A_ID, route_text, reply_markup=kb, parse_mode="Markdown")

@bot.message_handler(commands=['route', 'disp', 'pin_route', 'd1', 'd2', 'dall', 'b1', 'b2', 'ball', 'panel'])
def handle_route_commands(message):
    if not is_route_manager(message.from_user.id, message.from_user.username):
        bot.reply_to(message, "⛔ Доступно только @AndreyZhuravkin, @ms_ksunchik и @dred_rock")
        return

    cmd = message.text.lower().split()[0].replace('@trypbotspb_bot', '')

    if cmd in ['/d1', '/b1']:
        set_dispatch_route("b1")
        refresh_route_board()
        kb = get_chat_a_bottom_keyboard()
        bot.reply_to(message, "🟢 Режим включен: заявки идут **только Диспетчеру 1 (Чат Б)**!", reply_markup=kb, parse_mode="Markdown")
        return
    if cmd in ['/d2', '/b2']:
        set_dispatch_route("b2")
        refresh_route_board()
        kb = get_chat_a_bottom_keyboard()
        bot.reply_to(message, "🟢 Режим включен: заявки идут **только Диспетчеру 2 (Чат Б-2)**!", reply_markup=kb, parse_mode="Markdown")
        return
    if cmd in ['/dall', '/ball']:
        set_dispatch_route("all")
        refresh_route_board()
        kb = get_chat_a_bottom_keyboard()
        bot.reply_to(message, "🔀 Режим включен: заявки дублируются **обоим диспетчерам одновременно**!", reply_markup=kb, parse_mode="Markdown")
        return

    text, markup = render_routing_menu()
    kb = get_chat_a_bottom_keyboard()
    
    bot.send_message(message.chat.id, "🎛 **Кнопки управления закреплены внизу экрана.**\n_Если они свернулись — нажмите значок четырёх квадратиков 🎛 справа в строке ввода._", reply_markup=kb, parse_mode="Markdown")
    sent_inline = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")
    
    if cmd == '/pin_route':
        save_route_board_msg_id(sent_inline.message_id)
        try:
            bot.pin_chat_message(message.chat.id, sent_inline.message_id)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('route_'))
def handle_route_callback(call):
    if not is_route_manager(call.from_user.id, call.from_user.username):
        try:
            bot.answer_callback_query(call.id, "⛔ Управлять могут только @AndreyZhuravkin, @ms_ksunchik и @dred_rock", show_alert=True)
        except Exception:
            pass
        return

    new_route = call.data.replace('route_', '')
    set_dispatch_route(new_route)

    text, markup = render_routing_menu()
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass

    route_names = {
        "b1": "Только Диспетчер 1 (Чат Б)",
        "b2": "Только Диспетчер 2 (Чат Б-2)",
        "all": "Оба диспетчера (параллельно)"
    }
    try:
        bot.answer_callback_query(call.id, f"Включено: {route_names.get(new_route)}")
    except Exception:
        pass

    kb = get_chat_a_bottom_keyboard()
    try:
        bot.send_message(CHAT_A_ID, f"🔄 Режим переключен на: **{route_names.get(new_route)}**", reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass

MONTHS_RU = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

def create_calendar(year=None, month=None):
    now = datetime.now(pytz.timezone('Europe/Moscow'))
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton(f"📅 {MONTHS_RU[month]} {year}", callback_data="cal_ignore"))
    markup.row(types.InlineKeyboardButton(f"📊 Отчет за весь {MONTHS_RU[month]}", callback_data=f"cal_month_{year}_{month}"))

    days_header = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    markup.row(*[types.InlineKeyboardButton(d, callback_data="cal_ignore") for d in days_header])

    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row_buttons = []
        for day in week:
            if day == 0:
                row_buttons.append(types.InlineKeyboardButton(" ", callback_data="cal_ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row_buttons.append(types.InlineKeyboardButton(str(day), callback_data=f"cal_pick_{date_str}"))
        markup.row(*row_buttons)

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    markup.row(
        types.InlineKeyboardButton("<<", callback_data=f"cal_nav_{prev_year}_{prev_month}"),
        types.InlineKeyboardButton("Сегодня", callback_data=f"cal_pick_{now.strftime('%Y-%m-%d')}"),
        types.InlineKeyboardButton(">>", callback_data=f"cal_nav_{next_year}_{next_month}")
    )
    markup.row(
        types.InlineKeyboardButton("Вчера", callback_data=f"cal_pick_{(now - timedelta(days=1)).strftime('%Y-%m-%d')}"),
        types.InlineKeyboardButton("❌ Закрыть", callback_data="cal_close")
    )
    return markup

def send_chat_g_menu(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    now = datetime.now(pytz.timezone('Europe/Moscow'))
    markup.add(
        types.InlineKeyboardButton("📅 Выбрать день в календаре", callback_data="open_cal"),
        types.InlineKeyboardButton(f"📊 Отчет за весь {MONTHS_RU[now.month]}", callback_data=f"cal_month_{now.year}_{now.month}"),
        types.InlineKeyboardButton("📈 Отчет за Сегодня", callback_data=f"cal_pick_{now.strftime('%Y-%m-%d')}"),
        types.InlineKeyboardButton("📉 Отчет за Вчера", callback_data=f"cal_pick_{(now - timedelta(days=1)).strftime('%Y-%m-%d')}")
    )
    bot.send_message(chat_id, "📊 **Выберите тип отчёта по заявкам:**", reply_markup=markup, parse_mode="Markdown")

def send_long_message(chat_id, text, reply_markup=None):
    if len(text) <= 4000:
        bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode="Markdown")
        return

    parts = []
    current_part = ""
    for line in text.split("\n"):
        if len(current_part) + len(line) + 1 > 3900:
            parts.append(current_part)
            current_part = line + "\n"
        else:
            current_part += line + "\n"
    if current_part:
        parts.append(current_part)

    for i, part in enumerate(parts):
        is_last = (i == len(parts) - 1)
        bot.send_message(chat_id, part, reply_markup=(reply_markup if is_last else None), parse_mode="Markdown")

def format_analytics_report(period_title, stats, deals, b_mimo_count):
    total_ok = 0
    total_fail = 0

    lines = [f"📊 **ОТЧЕТ ПО ЗАЯВКАМ ЗА {period_title.upper()}**\n"]
    lines.append("👥 **СТАТИСТИКА ПО АГЕНТАМ:**")

    def clean_k(name):
        return str(name or "").strip().lower().replace('ё', 'е')

    norm_stats = {clean_k(k): v for k, v in stats.items()}

    for agent_name in AGENTS.keys():
        st = norm_stats.get(clean_k(agent_name), {"ok": 0, "fail": 0})
        ok = st.get("ok", 0)
        fail = st.get("fail", 0)
        total_agent = ok + fail
        total_ok += ok
        total_fail += fail

        conv = f"({int((ok / total_agent) * 100)}%)" if total_agent > 0 else ""
        lines.append(f"• **{agent_name}**: ✅ Оформлено: **{ok}** | ❌ Не оформлено: **{fail}** {conv}")

    alina_mimo = norm_stats.get("алина", {}).get("fail", 0) or b_mimo_count
    nastya_mimo = norm_stats.get("настя", {}).get("fail", 0)
    
    if alina_mimo > 0:
        lines.append(f"• **Отсеяно в Чате Б (Алина)**: 🚫 **{alina_mimo} шт.**")
    if nastya_mimo > 0:
        lines.append(f"• **Отсеяно в Чате Б-2 (Настя)**: 🚫 **{nastya_mimo} шт.**")

    dispatch_total_mimo = alina_mimo + nastya_mimo
    grand_total = total_ok + total_fail + dispatch_total_mimo

    lines.append("\n📈 **ОБЩИЕ ИТОГИ:**")
    lines.append(f"• Всего поступило в работу: **{grand_total} шт.**")
    lines.append(f"• Всего оформлено агентами: ✅ **{total_ok} шт.**")
    lines.append(f"• Срывов у агентов: ❌ **{total_fail} шт.**")
    
    if (total_ok + total_fail) > 0:
        overall_conv = int((total_ok / (total_ok + total_fail)) * 100)
        lines.append(f"• Конверсия агентов: **{overall_conv}%**")

    if deals:
        lines.append("\n📋 **СПИСОК ОФОРМЛЕННЫХ ЗАЯВОК:**\n")
        for i, d in enumerate(deals, start=1):
            item_text = (
                f"{i}. **№{d.get('lead_num', '-')}** ({d.get('agent', '-')})\n"
                f"   📍 Адрес: {d.get('address', '-')}\n"
                f"   👤 ФИО: {d.get('fio', '-')}\n"
                f"   📞 Телефон: {d.get('phone', '-')}\n"
                f"____________________"
            )
            lines.append(item_text)

    return "\n".join(lines)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('open_cal', 'cal_nav_', 'cal_pick_', 'cal_month_', 'cal_ignore', 'cal_close', 'cal_again')))
def handle_calendar_callbacks(call):
    if call.data == "cal_ignore":
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        return

    if call.data == "cal_close":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    if call.data in ["cal_again", "open_cal"]:
        markup = create_calendar()
        try:
            bot.edit_message_text("📅 **Выберите день или нажмите «Отчет за весь месяц»:**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            bot.send_message(call.message.chat.id, "📅 **Выберите день или нажмите «Отчет за весь месяц»:**", reply_markup=markup, parse_mode="Markdown")
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        return

    if call.data.startswith("cal_nav_"):
        _, _, yr, mo = call.data.split('_')
        markup = create_calendar(int(yr), int(mo))
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        except Exception:
            pass
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        return

    if call.data.startswith("cal_month_"):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        _, _, yr_s, mo_s = call.data.split('_')
        yr, mo = int(yr_s), int(mo_s)
        last_day = calendar.monthrange(yr, mo)[1]
        start_date = f"{yr}-{mo:02d}-01"
        end_date = f"{yr}-{mo:02d}-{last_day:02d}"
        period_title = f"{MONTHS_RU[mo]} {yr}"

        try:
            bot.edit_message_text(f"⏳ Формирую сводный отчет за **{period_title}**...", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        except Exception:
            pass

        url = f"{GOOGLE_SHEET_WEBHOOK_URL}?action=get_report&start={start_date}&end={end_date}"
        stats, deals, b_mimo = {}, [], 0
        try:
            res = requests.get(url, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    stats = data.get("stats", {})
                    deals = data.get("deals", [])
                    b_mimo = data.get("b_mimo", 0)
                elif isinstance(data, list):
                    deals = data
        except Exception as e:
            print(f"Ошибка выгрузки отчета: {e}")

        if not stats and not deals:
            db = load_leads_db()
            stats = {name: {"ok": 0, "fail": 0} for name in AGENTS.keys()}
            for k, v in db.items():
                if k.startswith("num_"):
                    continue
                c_time = v.get("closed_at") or v.get("created_at", 0)
                dt = datetime.fromtimestamp(c_time, pytz.timezone('Europe/Moscow'))
                if dt.year == yr and dt.month == mo:
                    ag = v.get("assigned_agent")
                    st = v.get("status")
                    if ag in stats:
                        if st == "ОФОРМЛЕНО!" or v.get("is_closed") is True:
                            stats[ag]["ok"] += 1
                            deals.append({
                                "lead_num": v.get("lead_num", "-"),
                                "agent": ag,
                                "address": v.get("address", "-"),
                                "fio": v.get("fio", "-"),
                                "phone": v.get("phone", "-")
                            })
                        elif st in ["СОРВАЛАСЬ", "МИМО"]:
                            stats[ag]["fail"] += 1

        back_markup = types.InlineKeyboardMarkup()
        back_markup.add(types.InlineKeyboardButton("📅 Выбрать другую дату", callback_data="cal_again"))

        report_text = format_analytics_report(period_title, stats, deals, b_mimo)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        send_long_message(call.message.chat.id, report_text, reply_markup=back_markup)
        return

    if call.data.startswith("cal_pick_"):
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

        date_str = call.data.replace("cal_pick_", "")
        d_parts = date_str.split('-')
        human_date = f"{d_parts[2]}.{d_parts[1]}.{d_parts[0]}"

        try:
            bot.edit_message_text(f"⏳ Формирую отчет за **{human_date}**...", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
        except Exception:
            pass

        url = f"{GOOGLE_SHEET_WEBHOOK_URL}?action=get_report&start={date_str}&end={date_str}"
        stats, deals, b_mimo = {}, [], 0
        try:
            res = requests.get(url, timeout=15)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    stats = data.get("stats", {})
                    deals = data.get("deals", [])
                    b_mimo = data.get("b_mimo", 0)
                elif isinstance(data, list):
                    deals = data
        except Exception as e:
            print(f"Ошибка выгрузки отчета: {e}")

        if not stats and not deals:
            db = load_leads_db()
            stats = {name: {"ok": 0, "fail": 0} for name in AGENTS.keys()}
            for k, v in db.items():
                if k.startswith("num_"):
                    continue
                c_time = v.get("closed_at") or v.get("created_at", 0)
                dt = datetime.fromtimestamp(c_time, pytz.timezone('Europe/Moscow'))
                if dt.strftime("%Y-%m-%d") == date_str:
                    ag = v.get("assigned_agent")
                    st = v.get("status")
                    if ag in stats:
                        if st == "ОФОРМЛЕНО!" or v.get("is_closed") is True:
                            stats[ag]["ok"] += 1
                            deals.append({
                                "lead_num": v.get("lead_num", "-"),
                                "agent": ag,
                                "address": v.get("address", "-"),
                                "fio": v.get("fio", "-"),
                                "phone": v.get("phone", "-")
                            })
                        elif st in ["СОРВАЛАСЬ", "МИМО"]:
                            stats[ag]["fail"] += 1

        back_markup = types.InlineKeyboardMarkup()
        back_markup.add(types.InlineKeyboardButton("📅 Выбрать другую дату", callback_data="cal_again"))

        report_text = format_analytics_report(human_date, stats, deals, b_mimo)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        send_long_message(call.message.chat.id, report_text, reply_markup=back_markup)

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and msg.text in ["🟢 Выйти на смену", "🔴 Уйти со смены"])
def handle_menu_duty_toggle(message):
    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Вы не найдены в списке агентов.")
        return

    new_status = (message.text == "🟢 Выйти на смену")
    save_agent_status(agent_name, new_status)
    refresh_pinned_board()
    broadcast_status_change(agent_name, new_status)

    status_text = "🟢 вышли на смену! Заявки будут поступать." if new_status else "🔴 ушли со смены. Заявки поступать не будут."
    markup = get_agent_persistent_keyboard(agent_name)
    bot.send_message(message.chat.id, f"**{agent_name}**, вы {status_text}", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and msg.text == "✍️ Внести заявку вручную")
def handle_menu_manual_add(message):
    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Вы не в списке агентов.")
        return

    pending_manual_leads[message.from_user.id] = True
    bot.send_message(
        message.chat.id,
        f"✍️ **Ручное внесение заявки (Агент: {agent_name})**\n\n"
        "Номер заявки проставится **автоматически**.\n"
        "Отправьте сообщением **ФИО клиента и номер телефона**.\n\n"
        "Пример:\n`Иванов Иван Иванович +79111234567`\nили\n`Смирнова А.В., 89210001122, ул. Мира д.5`",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and msg.text == "📊 Отчеты и статистика")
def handle_menu_stats(message):
    send_chat_g_menu(message.chat.id)

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and msg.text == "👥 Состав смены")
def handle_menu_duty_list(message):
    statuses = load_agent_statuses()
    report = ["🔍 **Текущий состав смены:**\n"]
    for name, data in AGENTS.items():
        st = statuses.get(name, False)
        icon = "🟢 На смене" if st else "🔴 Не работает"
        report.append(f"• **{name}** ({data[1]}): {icon}")
    bot.send_message(message.chat.id, "\n".join(report), parse_mode="Markdown")

@bot.message_handler(commands=['add'])
def handle_manual_add_cmd(message):
    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Вы не зарегистрированы в списке агентов.")
        return

    pending_manual_leads[message.from_user.id] = True
    bot.send_message(
        message.chat.id,
        f"✍️ **Ручное внесение заявки (Агент: {agent_name})**\n\n"
        "Отправьте **ФИО клиента и номер телефона**:\n`Иванов Иван Иванович +79111234567`",
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda msg: msg.from_user.id in pending_manual_leads and not msg.text.startswith('/'))
def handle_manual_lead_data_input(message):
    pending_manual_leads.pop(message.from_user.id, None)

    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Агент не определён.")
        return

    text = message.text.strip()
    phone_m = re.search(r'(?:\+?7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}|\b9\d{9}\b', text)
    phone_clean = "-"
    if phone_m:
        raw_p = re.sub(r'\D', '', phone_m.group(0))
        if len(raw_p) == 10:
            phone_clean = f"+7{raw_p}"
        elif len(raw_p) == 11:
            phone_clean = f"+7{raw_p[1:]}"

    text_wo_phone = re.sub(r'(?:\+?7|8)?[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}|\b9\d{9}\b', '', text).strip(' ,;')
    parts = [p.strip() for p in re.split(r'[,;\n]+', text_wo_phone) if p.strip()]

    fio = parts[0] if len(parts) > 0 else "Не указано"
    address = parts[1] if len(parts) > 1 else "-"

    lead_num = get_next_lead_number()
    agent_phone = AGENTS.get(agent_name, [None, None, "-"])[2]

    lead_entry = {
        'lead_num': lead_num,
        'address': address,
        'fio': fio,
        'phone': phone_clean,
        'assigned_agent': agent_name,
        'agent_phone': agent_phone,
        'status': "ОФОРМЛЕНО!",
        'is_closed': True,
        'closed_at': time.time(),
        'created_at': time.time()
    }
    save_lead_to_db(lead_num, lead_entry)

    export_to_google_sheet(
        agent_name=agent_name,
        lead_num=lead_num,
        status="ОФОРМЛЕНО",
        phone=phone_clean,
        address=address,
        fio=fio,
        reason="Ручное внесение"
    )

    markup = get_agent_persistent_keyboard(agent_name)
    bot.reply_to(
        message,
        f"✅ **Заявка №{lead_num} успешно добавлена и оформлена!**\n\n"
        f"👤 Агент: **{agent_name}**\n"
        f"👤 ФИО: {fio}\n"
        f"📞 Телефон: {phone_clean}\n"
        f"📍 Адрес: {address}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

    chat_g_text = (
        f"📋 Заявка №{lead_num} (Внесена вручную)\n"
        f"📍 Адрес: {address}\n"
        f"👤 ФИО: {fio}\n"
        f"📞 Телефон клиента: {phone_clean}\n"
        f"👤 Агент: {agent_name} ({agent_phone})\n"
        f"Статус: ОФОРМЛЕНО!"
    )
    try:
        bot.send_message(CHAT_D_ID, chat_g_text)
    except Exception as e:
        print(f"Ошибка отправки ручной заявки в Чат Г: {e}")

@bot.message_handler(commands=['start'])
def handle_start_command(message):
    global KSENIA_CHAT_ID
    if (message.from_user.username or "").lower() == "ms_ksunchik":
        KSENIA_CHAT_ID = message.chat.id
        AGENTS["Ксюша"][0] = message.chat.id

    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if agent_name and not AGENTS[agent_name][0]:
        AGENTS[agent_name][0] = message.from_user.id

    agent_str = f"Агент: **{agent_name}**" if agent_name else "Роль: Пользователь"
    markup = get_agent_persistent_keyboard(agent_name) if message.chat.type == "private" else None
    
    bot.reply_to(
        message, 
        f"🤖 **Рабочий бот активен!**\n{agent_str}\n\n"
        "Используйте кнопки меню внизу экрана для быстрого управления.", 
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.message_handler(func=lambda msg: msg.text and any(
    cmd in msg.text.lower() for cmd in ['/отчет', '/отчёт', '/report', '/menu', 'отчет', 'отчёт', 'меню']
))
def handle_report_triggers(message):
    send_chat_g_menu(message.chat.id)

@bot.message_handler(commands=['on'])
def handle_turn_on(message):
    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Вы не найдены в списке агентов.")
        return
    save_agent_status(agent_name, True)
    refresh_pinned_board()
    broadcast_status_change(agent_name, True)
    markup = get_agent_persistent_keyboard(agent_name) if message.chat.type == "private" else None
    bot.reply_to(message, f"🟢 **{agent_name}**, вы вышли на смену!", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['off'])
def handle_turn_off(message):
    agent_name = find_agent_name_by_user(message.from_user.id, message.from_user.username)
    if not agent_name:
        bot.reply_to(message, "❌ Вы не найдены в списке агентов.")
        return
    save_agent_status(agent_name, False)
    refresh_pinned_board()
    broadcast_status_change(agent_name, False)
    markup = get_agent_persistent_keyboard(agent_name) if message.chat.type == "private" else None
    bot.reply_to(message, f"🔴 **{agent_name}**, вы сняты со смены.", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['check'])
def handle_check_command(message):
    statuses = load_agent_statuses()
    report = ["🔍 **Статус готовности агентов:**\n"]
    for name, data in AGENTS.items():
        agent_id, tag = data[0], data[1]
        is_active = statuses.get(name, False)
        status_str = "🟢 На смене" if is_active else "🔴 Не на смене"
        id_str = "✅ Привязан" if agent_id else "⚠️ Нет ID (/start)"
        report.append(f"• **{name}** ({tag}): {status_str} | {id_str}")
    bot.reply_to(message, "\n".join(report), parse_mode="Markdown")

@bot.message_handler(commands=['setnum'])
def handle_set_number(message):
    global GLOBAL_LEAD_COUNTER
    user_username = (message.from_user.username or "").lower()
    user_id = message.from_user.id

    is_allowed = (user_id in ALLOWED_ADMIN_IDS) or (user_username in [m.lower() for m in MANAGERS])
    
    if not is_allowed:
        bot.reply_to(message, "⛔ У вас нет прав для изменения номера.")
        return

    parts = message.text.split()
    if len(parts) == 2 and parts[1].isdigit():
        target_num = int(parts[1]) - 1
        GLOBAL_LEAD_COUNTER = target_num
        with open(COUNTER_FILE, "w") as f:
            f.write(str(target_num))
        try:
            payload = {"action": "set_counter", "val": target_num}
            requests.post(GOOGLE_SHEET_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, allow_redirects=True, timeout=5)
        except Exception:
            pass
        bot.reply_to(message, f"✅ Номер обновлен! Следующая заявка выйдет под номером: **№{parts[1]}**", parse_mode="Markdown")
    else:
        bot.reply_to(message, "Используйте формат: `/setnum 2`", parse_mode="Markdown")

@bot.message_handler(commands=['pin_board'])
def handle_pin_board(message):
    text, markup = render_status_board()
    target_chat = CHAT_C_ID if message.chat.type == "private" else message.chat.id
    try:
        msg = bot.send_message(target_chat, text, reply_markup=markup, parse_mode="Markdown")
        save_board_msg_id(msg.message_id)
        bot.pin_chat_message(target_chat, msg.message_id)
        if message.chat.type == "private":
            bot.reply_to(message, "✅ Табло смены отправлено и закреплено в Кремле!")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_'))
def handle_agent_toggle_callback(call):
    target_name = call.data.split('_')[1]
    statuses = load_agent_statuses()
    current_status = statuses.get(target_name, False)
    new_status = not current_status
    save_agent_status(target_name, new_status)

    text, markup = render_status_board()
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass

    status_word = "🟢 На смене" if new_status else "🔴 Занят / Не работает"
    try:
        bot.answer_callback_query(call.id, f"{target_name}: {status_word}")
    except Exception:
        pass
    broadcast_status_change(target_name, new_status)

@bot.message_handler(commands=['agents'])
def handle_manage_agents_menu(message):
    user_id = message.from_user.id
    username = (message.from_user.username or "").lower().lstrip('@')

    if user_id != 661842368 and username != "andreyzhuravkin":
        bot.reply_to(message, "⛔ Доступ только для Андрея.")
        return

    statuses = load_agent_statuses()
    lines = ["🛠 **Управление сменой агентов (ЛС):**\n"]
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for name, data in AGENTS.items():
        st = statuses.get(name, False)
        icon = "🟢" if st else "🔴"
        status_desc = "На смене" if st else "Не работает"
        lines.append(f"• **{name}**: {icon} {status_desc}")
        buttons.append(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"adm_toggle_{name}"))

    markup.add(*buttons)
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_toggle_'))
def handle_admin_agent_toggle(call):
    user_id = call.from_user.id
    username = (call.from_user.username or "").lower().lstrip('@')

    if user_id != 661842368 and username != "andreyzhuravkin":
        try:
            bot.answer_callback_query(call.id, "⛔ Доступно только Андрею", show_alert=True)
        except Exception:
            pass
        return

    target_name = call.data.split('_')[2]
    statuses = load_agent_statuses()
    current_status = statuses.get(target_name, False)
    new_status = not current_status

    save_agent_status(target_name, new_status)
    refresh_pinned_board()
    broadcast_status_change(target_name, new_status)

    statuses[target_name] = new_status
    lines = ["🛠 **Управление сменой агентов (ЛС):**\n"]
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []

    for name, data in AGENTS.items():
        st = statuses.get(name, False)
        icon = "🟢" if st else "🔴"
        status_desc = "На смене" if st else "Не работает"
        lines.append(f"• **{name}**: {icon} {status_desc}")
        buttons.append(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"adm_toggle_{name}"))

    markup.add(*buttons)

    try:
        bot.edit_message_text("\n".join(lines), call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass

    status_word = "🟢 на смене" if new_status else "🔴 снят(а) со смены"
    try:
        bot.answer_callback_query(call.id, f"{target_name} теперь {status_word}")
    except Exception:
        pass

# --- ОБРАБОТКА КОММЕНТАРИЕВ ПРИ МИМО / СРЫВЕ ---

@bot.message_handler(func=lambda msg: msg.reply_to_message and msg.reply_to_message.message_id in pending_mimo_reasons and not msg.text.startswith('/'))
def handle_manual_mimo_reason(message):
    data_info = pending_mimo_reasons.pop(message.reply_to_message.message_id, None)
    if not data_info:
        return

    lead_id = data_info.get("lead_id")
    source = data_info.get("source", "")
    lead = get_lead_or_reconstruct(lead_id, message.reply_to_message)

    lead_num = lead.get('lead_num', '') if lead else ""
    address = lead.get('address', '-') if lead else "-"
    fio = lead.get('fio', '-') if lead else "-"
    phone = lead.get('phone', '-') if lead else "-"
    agent_display = lead.get('assigned_agent', 'Не назначен') if lead else 'Не назначен'
    agent_phone = lead.get('agent_phone', '-') if lead else '-'
    photo_id = lead.get('photo_file_id') if lead else None

    reason = message.text.strip()
    who_rejected = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    sender_username = (message.from_user.username or "").lower().lstrip('@')
    source_chat_id = message.chat.id
    origin_chat = lead.get('active_dispatch_chat') if lead else None
    disp_assigned = lead.get('dispatcher_name') if lead else None

    if "chat_b" in str(source):
        if sender_username in ["anastaishass"] or source_chat_id == CHAT_B2_ID or origin_chat == CHAT_B2_ID or disp_assigned == "Настя":
            sheet_dest = "Настя"
            status_label = "МИМО (Чат Б-2 / Настя)"
        else:
            sheet_dest = "Алина"
            status_label = "МИМО (Чат Б / Алина)"
    else:
        sheet_dest = agent_display if (agent_display not in ["Не назначен", "Неизвестно"]) else "Алина"
        status_label = "МИМО (Сорвалась у агента)"

    bot.reply_to(message, f"✅ Комментарий по Заявке №{lead_num} зафиксирован.")

    status_text = (
        f"📋 Заявка №{lead_num}\n📍 Адрес: {address}\n👤 ФИО: {fio}\n📞 Телефон клиента: {phone}\n"
        f"👤 Агент: {agent_display} ({agent_phone})\n❌ Статус: {status_label}\n"
        f"👤 Автор комментария: {who_rejected}\n📝 Причина: {reason}"
    )

    if photo_id:
        bot.send_photo(CHAT_D_ID, photo_id, caption=status_text)
    else:
        bot.send_message(CHAT_D_ID, status_text)

    export_to_google_sheet(
        agent_name=sheet_dest,
        lead_num=lead_num, status="МИМО", phone=phone, address=address, fio=fio, reason=reason
    )

# --- ПРИЕМ ФОТО ИЗ ЧАТА А ---

@bot.message_handler(content_types=['photo', 'document'])
def handle_incoming_photo(message):
    if message.chat.id != CHAT_A_ID and message.chat.type != "private":
        return

    try:
        if message.content_type == 'photo':
            file_id = message.photo[-1].file_id
        elif message.content_type == 'document' and message.document.mime_type.startswith('image/'):
            file_id = message.document.file_id
        else:
            return

        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        lead_num = get_next_lead_number()
        lead_info = extract_card_data(downloaded_file)
        
        address_val = lead_info.get('address', '-')
        is_repeat = check_address_repetition(address_val)
        repeat_warning = "\n⚠️ ВНИМАНИЕ: Повторный адрес! Возможно, это дом престарелых!\n" if is_repeat else ""

        caption = (
            f"📋 Заявка №{lead_num}:{repeat_warning}\n"
            f"📍 Адрес: {address_val}\n"
            f"👤 ФИО: {lead_info.get('fio', '-')}\n"
            f"📞 Тел клиента: {lead_info.get('phone', '-')}"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("АГЕНТ!", callback_data=f"to_c_{lead_num}"),
            types.InlineKeyboardButton("МИМО!", callback_data=f"pass_b_{lead_num}")
        )

        b1_msg_id = None
        b2_msg_id = None
        route = get_dispatch_route()

        if route in ["b1", "all"]:
            try:
                sent_msg_b1 = bot.send_photo(CHAT_B_ID, downloaded_file, caption=caption, reply_markup=markup)
                b1_msg_id = sent_msg_b1.message_id
                print(f"✅ Успешно отправлено в Чат Б1, msg_id={b1_msg_id}")
            except Exception as e:
                print(f"❌ Ошибка отправки в Чат Б1: {e}")

        if route in ["b2", "all"] and CHAT_B2_ID and CHAT_B2_ID != -1000000000000:
            try:
                sent_msg_b2 = bot.send_photo(CHAT_B2_ID, downloaded_file, caption=caption, reply_markup=markup)
                b2_msg_id = sent_msg_b2.message_id
                print(f"✅ Успешно отправлено в Чат Б2, msg_id={b2_msg_id}")
            except Exception as e:
                print(f"❌ Ошибка отправки в Чат Б2: {e}")

        lead_info['lead_num'] = lead_num
        lead_info['photo_file_id'] = file_id
        lead_info['created_at'] = time.time()
        lead_info['b1_msg_id'] = b1_msg_id
        lead_info['b2_msg_id'] = b2_msg_id
        lead_info['route_assigned'] = route
        lead_info['dispatcher_name'] = "Настя" if route == "b2" else "Алина"
        save_lead_to_db(str(lead_num), lead_info)

    except Exception as e:
        print(f"Ошибка приема фото: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('to_c_', 'pass_b_')))
def handle_chat_b_actions(call):
    action = "agent" if "to_c_" in call.data else "pass"
    lead_key = call.data.split('_')[-1]
    
    lead = get_lead_or_reconstruct(lead_key, call.message)
    if not lead:
        try:
            bot.answer_callback_query(call.id, "❌ Данные заявки устарели", show_alert=True)
        except Exception:
            pass
        return

    lead_num = lead.get('lead_num', lead_key)
    created_at = lead.get('created_at', time.time())

    if time.time() - created_at > BUTTON_TTL_CHAT_B_SECONDS:
        try:
            bot.answer_callback_query(call.id, "⏱ Срок действия заявки истек!", show_alert=True)
            bot.edit_message_caption(f"⏰ Срок Заявки №{lead_num} истек.\n📍 {lead['address']}", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    if lead.get('taken_by_dispatch') is True:
        try:
            bot.answer_callback_query(call.id, "Заявка уже взята в обработку", show_alert=True)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    lead['taken_by_dispatch'] = True
    current_chat = call.message.chat.id
    lead['active_dispatch_chat'] = current_chat
    lead['dispatcher_name'] = "Настя" if current_chat == CHAT_B2_ID else "Алина"
    save_lead_to_db(lead_num, lead)

    other_chat = CHAT_B2_ID if current_chat == CHAT_B_ID else CHAT_B_ID
    other_msg_id = lead.get('b2_msg_id') if current_chat == CHAT_B_ID else lead.get('b1_msg_id')

    if other_chat and other_msg_id:
        try:
            bot.edit_message_caption(
                f"📋 Заявка №{lead_num} (В обработке)\n📍 {lead.get('address', '-')}",
                other_chat,
                other_msg_id,
                reply_markup=None
            )
        except Exception:
            pass

    if action == "pass":
        try:
            bot.edit_message_caption(f"❌ Заявка №{lead_num} отклонена (МИМО)\n📍 {lead['address']}\n\n⏳ Ожидается комментарий...", current_chat, call.message.message_id, reply_markup=None)
        except Exception:
            pass

        prompt_msg = bot.send_message(current_chat, f"✏️ Напишите причину «МИМО» по Заявке №{lead_num}:", reply_markup=types.ForceReply(selective=True))
        pending_mimo_reasons[prompt_msg.message_id] = {"lead_id": lead_num, "source": "chat_b"}
        try:
            bot.answer_callback_query(call.id, "Напишите причину")
        except Exception:
            pass
        return

    statuses = load_agent_statuses()
    active_agents = [name for name in AGENTS.keys() if statuses.get(name, False)]
    if not active_agents:
        active_agents = list(AGENTS.keys())

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(name, callback_data=f"take_{lead_num}_{name}") for name in active_agents]
    markup.add(*buttons)

    caption_text = f"📍 Заявка №{lead_num} в работу:\n{lead.get('address', '-')}\n\nКто берет?"
    photo_id = lead.get('photo_file_id') or (call.message.photo[-1].file_id if call.message.photo else None)
    
    if photo_id:
        kremlin_msg = bot.send_photo(CHAT_C_ID, photo_id, caption=caption_text, reply_markup=markup)
    else:
        kremlin_msg = bot.send_message(CHAT_C_ID, caption_text, reply_markup=markup)

    if kremlin_msg:
        save_lead_to_db(str(kremlin_msg.message_id), lead)

    try:
        bot.edit_message_caption(f"⏳ Заявка №{lead_num} передана в Кремль...\n📍 {lead.get('address', '-')}", current_chat, call.message.message_id, reply_markup=None)
        bot.answer_callback_query(call.id)
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('take_'))
def handle_agent_take(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    try:
        parts = call.data.split('_')
        lead_num = parts[1]
        target_agent_name = parts[2]
    except Exception:
        return

    user_username = (call.from_user.username or "").lower().lstrip('@')
    user_id = call.from_user.id
    clicker_name = f"@{call.from_user.username}" if call.from_user.username else (call.from_user.first_name or "Неизвестный")

    is_distributor = (user_id in DISTRIBUTOR_IDS) or (user_username in [d.lower() for d in DISTRIBUTORS])
    caller_agent_name = find_agent_name_by_user(user_id, user_username)

    is_vika_allowed = (caller_agent_name == "Вика" and target_agent_name in ["Вика", "Дима"])

    if not is_distributor and not is_vika_allowed and caller_agent_name != target_agent_name:
        try:
            bot.answer_callback_query(call.id, "⛔ Вы можете брать заявку только на себя!", show_alert=True)
        except Exception:
            pass
        return

    agent_info = AGENTS.get(target_agent_name, [None, None, ""])
    target_id, target_tag, target_phone = agent_info[0], agent_info[1], agent_info[2]

    lead = get_lead_by_key_or_num(lead_num)
    if not lead:
        lead = get_lead_or_reconstruct(lead_num, call.message)

    lead['assigned_agent'] = target_agent_name
    lead['agent_id'] = target_id
    lead['agent_tag'] = target_tag
    lead['agent_phone'] = target_phone
    lead['assigned_by'] = clicker_name
    save_lead_to_db(lead_num, lead)

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    kremlin_notice = (
        f"🎯 Заявка №{lead_num} в работу: агенту {target_agent_name} ({target_tag})\n"
        f"📍 Адрес: {lead.get('address', '-')}\n"
        f"👤 Назначил(а): {clicker_name}"
    )
    try:
        bot.send_message(CHAT_C_ID, kremlin_notice)
    except Exception as e:
        print(f"Ошибка отправки в Кремль: {e}")

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("📞 ЗВОНИ", callback_data=f"call_{lead_num}"),
        types.InlineKeyboardButton("🚫 МИМО", callback_data=f"final_mimo_{lead_num}")
    )

    chat_b_text = (
        f"🎯 Заявка №{lead_num} принята в работу!\n"
        f"👤 Агент: {target_agent_name} ({target_tag})\n"
        f"📱 Телефон: {target_phone}\n"
        f"📞 Клиент: {lead.get('phone', '-')}\n"
        f"📍 Адрес: {lead.get('address', '-')}\n"
        f"👤 Распределил: {clicker_name}"
    )

    dest_chat = lead.get('active_dispatch_chat') or CHAT_B_ID
    try:
        bot.send_message(dest_chat, chat_b_text, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка отправки диспетчеру: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('call_', 'final_mimo_')))
def handle_call_decision(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    action = "call" if "call_" in call.data else "mimo"
    lead_num = call.data.split('_')[-1]
    lead = get_lead_by_key_or_num(lead_num)
    if not lead:
        lead = get_lead_or_reconstruct(lead_num, call.message)

    photo_id = lead.get('photo_file_id') or (call.message.photo[-1].file_id if call.message.photo else None)

    if action == "call":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ ОФОРМЛЕНО", callback_data=f"deal_ok_{lead_num}"),
            types.InlineKeyboardButton("❌ СОРВАЛАСЬ", callback_data=f"deal_fail_{lead_num}")
        )
        
        assigned_name = lead.get('assigned_agent', 'Не назначен')
        target_agent_id = lead.get('agent_id')

        if not target_agent_id and assigned_name in AGENTS:
            target_agent_id = AGENTS[assigned_name][0]
            lead['agent_id'] = target_agent_id
            save_lead_to_db(lead_num, lead)

        caption_for_agent = (
            f"📥 Вам назначена заявка №{lead_num}!\n\n"
            f"👤 Агент: {assigned_name}\n"
            f"📍 Адрес: {lead.get('address', '-')}\n"
            f"👤 ФИО клиента: {lead.get('fio', '-')}\n"
            f"📞 Телефон: {lead.get('phone', '-')}\n\n"
            f"📞 ЗВОНИ"
        )
        
        if target_agent_id:
            lead['agent_sent_at'] = time.time()
            save_lead_to_db(lead_num, lead)

            try:
                if photo_id:
                    bot.send_photo(target_agent_id, photo_id, caption=caption_for_agent, reply_markup=markup)
                else:
                    bot.send_message(target_agent_id, caption_for_agent, reply_markup=markup)
            except Exception as e:
                bot.send_message(call.message.chat.id, f"⚠️ Не удалось доставить в ЛС агенту {assigned_name}.")

            try:
                bot.edit_message_text(
                    f"🎯 Заявка №{lead_num} (В РАБОТЕ)\n👤 Агент: {assigned_name}\n🚀 Отправлена агенту в личку!", 
                    call.message.chat.id, 
                    call.message.message_id, 
                    reply_markup=None
                )
            except Exception:
                pass
        else:
            bot.send_message(call.message.chat.id, f"⚠️ У агента {assigned_name} отсутствует привязка Telegram ID. Ему нужно нажать /start в диалоге с ботом.")
    else:
        try:
            bot.edit_message_text(f"❌ Заявка №{lead_num} отклонена (МИМО)\n📍 {lead.get('address', '-')}\n\n⏳ Ожидается комментарий...", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        prompt_msg = bot.send_message(call.message.chat.id, f"✏️ Напишите комментарий/причину «МИМО» по Заявке №{lead_num}:", reply_markup=types.ForceReply(selective=True))
        pending_mimo_reasons[prompt_msg.message_id] = {"lead_id": lead_num, "source": "chat_b"}

# --- ФИНАЛЬНЫЙ СТАТУС ОТ АГЕНТА В ЛС ---

@bot.callback_query_handler(func=lambda call: call.data.startswith(('deal_ok_', 'deal_fail_')))
def handle_agent_final_status(call):
    lead_num = call.data.split('_')[-1]
    
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    lead = get_lead_by_key_or_num(lead_num)
    if not lead:
        lead = get_lead_or_reconstruct(lead_num, call.message)

    if lead.get('is_closed') is True:
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    lead['is_closed'] = True
    lead['closed_at'] = time.time()
    save_lead_to_db(lead_num, lead)

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    is_ok = "deal_ok_" in call.data
    agent_name = lead.get('assigned_agent')
    if not agent_name or agent_name in ["Неизвестно", "Не назначен"]:
        clicked_agent = find_agent_name_by_user(call.from_user.id, call.from_user.username)
        if clicked_agent:
            agent_name = clicked_agent
            lead['assigned_agent'] = clicked_agent
            lead['agent_phone'] = AGENTS[clicked_agent][2]
        else:
            agent_name = "Неизвестно"

    agent_phone = lead.get('agent_phone') or (AGENTS.get(agent_name, [None, None, "-"])[2] if agent_name in AGENTS else "-")
    dispatcher_name = lead.get('dispatcher_name') or ("Настя" if lead.get('active_dispatch_chat') == CHAT_B2_ID else "Алина")

    if is_ok:
        status = "ОФОРМЛЕНО!"
        lead['status'] = "ОФОРМЛЕНО!"
        save_lead_to_db(lead_num, lead)

        # 1. Запись на лист агента
        export_to_google_sheet(
            agent_name=agent_name, lead_num=lead_num, status="ОФОРМЛЕНО",
            phone=lead.get('phone', '-'), address=lead.get('address', '-'), fio=lead.get('fio', '-'), reason="-"
        )

        # 2. Дублирование на лист диспетчера (Настя / Алина)
        export_to_google_sheet(
            agent_name=dispatcher_name, lead_num=lead_num, status="ОФОРМЛЕНО",
            phone=lead.get('phone', '-'), address=lead.get('address', '-'), fio=lead.get('fio', '-'), reason=f"Оформил агент: {agent_name}"
        )

        status_text = (
            f"📋 Заявка №{lead_num}\n📍 Адрес: {lead.get('address', '-')}\n👤 ФИО: {lead.get('fio', '-')}\n📞 Телефон клиента: {lead.get('phone', '-')}\n"
            f"👤 Агент: {agent_name} ({agent_phone})\n👤 Диспетчер: {dispatcher_name}\nСтатус: {status}"
        )

        photo_id = lead.get('photo_file_id') or (call.message.photo[-1].file_id if call.message.photo else None)
        if photo_id:
            bot.send_photo(CHAT_D_ID, photo_id, caption=status_text)
        else:
            bot.send_message(CHAT_D_ID, status_text)

        try:
            bot.edit_message_caption(f"Статус по заявке №{lead_num} зафиксирован: {status}", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
    else:
        lead['status'] = "СОРВАЛАСЬ"
        save_lead_to_db(lead_num, lead)
        try:
            bot.edit_message_caption(f"❌ Заявка №{lead_num} сорвалась.\n📍 {lead.get('address', '-')}\n\n⏳ Ожидается комментарий...", call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        prompt_msg = bot.send_message(call.message.chat.id, f"✏️ Напишите причину срыва/комментарий по Заявке №{lead_num}:", reply_markup=types.ForceReply(selective=True))
        pending_mimo_reasons[prompt_msg.message_id] = {"lead_id": lead_num, "source": "agent_fail"}

# --- ВЕБХУК ДЛЯ RENDER ---

@app.route('/')
def home():
    return "Bot Webhook Server is Live!"

@app.route(f"/{TELEGRAM_TOKEN}", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

def setup_webhook():
    time.sleep(2)
    bot.remove_webhook()
    time.sleep(1)
    webhook_url = f"{RENDER_APP_URL}/{TELEGRAM_TOKEN}"
    bot.set_webhook(url=webhook_url)
    print(f"Webhook set to {webhook_url}")
    sync_counter_from_cloud()
    fetch_statuses_from_cloud()

if __name__ == '__main__':
    setup_webhook()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
