# bot.py — оновлено: бронювання без дати/телефону; "Вартість" з портфоліо; Фотокнига: Standard/Premium/Light з розрахунком; HTML parse_mode
import os
import re
import html
import math
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

# ---------- Налаштування / Логи ----------
logging.basicConfig(level=logging.INFO)
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Не знайдено TELEGRAM_TOKEN у .env")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # опційно

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")  # HTML за замовчуванням
)
dp = Dispatcher(storage=MemoryStorage())

def norm(t: str) -> str:
    return (t or "").strip().lower()

# ---------- Головне меню (reply-кнопки) ----------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Вартість роботи"), KeyboardButton(text="📖 Фотокнига")],
        [KeyboardButton(text="🎁 Сертифікат"), KeyboardButton(text="📝 Замовити фотосесію")],
        [KeyboardButton(text="📅 Вільні дати"), KeyboardButton(text="ℹ️ FAQ")],
        [KeyboardButton(text="📞 Контакти")],
    ],
    resize_keyboard=True
)

# ---------- Статичні відповіді ----------
FREE_DATES = (
    "📅 <b>Вільні дати</b>\n"
    "Напишіть бажаний день/діапазон (наприклад: «12.10» або «12–14.10») — я перевірю доступність і відповім."
)

CERT_GIFT = (
    "🎁 <b>Подарунковий сертифікат</b>\n"
    "Зручний спосіб подарувати фотосесію близьким.\n"
    "Діє 6 місяців, можна використати на будь-яку зйомку.\n"
    "Вартість: <b>від 2000 грн</b> (налаштовується під обраний формат)."
)

CONTACTS = (
    "📞 <b>Контакти</b>\n"
    "Instagram: https://www.instagram.com/lena_shunkina_photo/\n"
    "Сайт: https://shunkinaphoto.com\n"
    "Telegram: @shunkinaphoto\n"
    "Телефон: +380509896036"
)

# ---------- FAQ (inline) — пункти 5,7,8,9 ----------
def faq_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Умови роботи", callback_data="faq_terms")],
        [InlineKeyboardButton(text="👗 Як підібрати одяг", callback_data="faq_outfit")],
        [InlineKeyboardButton(text="️💄 Зачіска / Макіяж", callback_data="faq_style")],
        [InlineKeyboardButton(text="📍️ Локація: студія / вдома / природа", callback_data="faq_location")],
        [InlineKeyboardButton(text="⬅️ Закрити", callback_data="faq_close")],
    ])

def faq_answer(code: str) -> str:
    mapping = {
        "faq_terms": (
            "📌 <b>Умови роботи</b>\n"
            "• Передоплата: 30%\n"
            "• Термін обробки: 5–10 днів\n"
            "• Віддача: онлайн-галерея\n"
            "• Друк / фотокнига — за домовленістю"
        ),
        "faq_outfit": (
            "👗 <b>Як підібрати одяг</b>\n"
            "• Гармонійні кольори без великих логотипів\n"
            "• 2–3 комплекти на вибір\n"
            "• Перевага однотонних/пастельних тонів\n"
            "• Уникайте занадто строкатих принтів"
        ),
        "faq_style": (
            "💄 <b>Зачіска / Макіяж</b>\n"
            "• Легка укладка / акуратна зачіска\n"
            "• Природний макіяж, що підкреслює риси\n"
            "• Для чоловіків — охайна стрижка, доглянута борода"
        ),
        "faq_location": (
            "📍 <b>Яку локацію краще обрати?</b>\n"
            "• <b>Фотостудія</b> — контрольоване світло, чисті фони\n"
            "• <b>Вдома</b> — затишна атмосфера, особливо для сімей\n"
            "• <b>Природа</b> — парки, вулиці, захід сонця"
        ),
    }
    return mapping.get(code, "Інформація уточнюється 🙂")

@dp.message(F.text == "ℹ️ FAQ")
async def open_faq(message: Message):
    await message.answer("Виберіть пункт:", reply_markup=faq_menu())

@dp.callback_query(F.data.startswith("faq_"))
async def cb_faq(call: CallbackQuery):
    code = call.data
    if code == "faq_close":
        await call.message.edit_text("Закрито. Оберіть пункт у меню 👇")
        await call.message.answer("Обирайте пункт у меню 👇", reply_markup=main_kb)
        await call.answer()
        return
    await call.message.edit_text(faq_answer(code), reply_markup=faq_menu())
    await call.answer()

# ---------- КАСКАД “Вартість роботи”: Місто → Тип → (Пакет/Одразу для Київ/Сімейна) ----------
# Маркування callback_data: p:<city> | p:<city>:<cat> | p:<city>:<cat>:<pkg>
# city: kyiv | krdn  (Кривий Ріг/Дніпро)
# cat: family | indiv
# pkg: exp | std | all

def price_city_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Київ", callback_data="p:kyiv")],
        [InlineKeyboardButton(text="Кривий Ріг / Дніпро", callback_data="p:krdn")],
        [InlineKeyboardButton(text="⬅️ Закрити", callback_data="p:close")],
    ])

def price_category_menu(city_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сімейна / Вагітність", callback_data=f"p:{city_key}:family")],
        [InlineKeyboardButton(text="Індивідуальна", callback_data=f"p:{city_key}:indiv")],
        [InlineKeyboardButton(text="⬅️ Назад до міст", callback_data="p:back_cities")],
    ])

def portfolio_row_for(cat_key: str) -> list:
    if cat_key == "family":
        return [
            InlineKeyboardButton(text="Подивитись портфоліо: Сімейна фотосесія", url="https://shunkinaphoto.com/semja"),
            InlineKeyboardButton(text="Подивитись портфоліо: Вагітність", url="https://shunkinaphoto.com/beremennost"),
        ]
    else:
        return [InlineKeyboardButton(text="Подивитись портфоліо: Індивідуальна фотосесія ", url="https://shunkinaphoto.com/fotosessii")]

def price_packages_menu(city_key: str, cat_key: str) -> InlineKeyboardMarkup:
    # Якщо Київ + Сімейна — пакета лише один → покажемо одразу текст (меню не потрібне)
    btns = []
    if not (city_key == "kyiv" and cat_key == "family"):
        if cat_key == "family":
            btns.append([InlineKeyboardButton(text="Пакет «Стандарт»", callback_data=f"p:{city_key}:{cat_key}:std")])
        else:
            btns.append([InlineKeyboardButton(text="Пакет «Експрес-фотосесія»", callback_data=f"p:{city_key}:{cat_key}:exp")])
            btns.append([InlineKeyboardButton(text="Пакет «Стандарт»", callback_data=f"p:{city_key}:{cat_key}:std")])
            btns.append([InlineKeyboardButton(text="Пакет «Все враховано»", callback_data=f"p:{city_key}:{cat_key}:all")])
    # Додамо рядок портфоліо
    btns.append(portfolio_row_for(cat_key))
    # Навігація
    btns.append([InlineKeyboardButton(text="⬅️ Назад до типів", callback_data=f"p:{city_key}:back_cats")])
    btns.append([InlineKeyboardButton(text="⬅️ Назад до міст", callback_data="p:back_cities")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def price_text(city_key: str, cat_key: str, pkg_key: str) -> str:
    city_label = "Київ" if city_key == "kyiv" else "Кривий Ріг / Дніпро"

    # Сімейна (Київ — тільки «Стандарт»; КР/Дніпро — «Стандарт» інша ціна)
    if cat_key == "family":
        if city_key == "kyiv":
            return (
                f"👨‍👩‍👧 <b>Сімейна/вагітність — {city_label}</b>\n"
                "<b>Пакет «Стандарт» — 10 000 грн</b>\n\n"
                "• Консультації перед фотосесією, допомога з ідеями, підбором одягу та локацій\n"
                "• 1,5–2 години зйомки\n"
                "• Близько 20 фото в авторській обробці та ретуші\n"
                "• Усі вдалі фото в базовій обробці (близько 90 шт.)\n"
                "• Знижка на фотокнигу 10%"
            )
        else:
            return (
                f"👨‍👩‍👧 <b>Сімейна/вагітність — {city_label}</b>\n"
                "<b>Пакет «Стандарт» — 7 000 грн</b>\n\n"
                "• Консультації перед фотосесією, допомога з ідеями, підбором одягу та локацій\n"
                "• 1,5–2 години зйомки\n"
                "• Близько 20 фото в авторській обробці та ретуші\n"
                "• Усі вдалі фото в базовій обробці (близько 90 шт.)\n"
                "• Знижка на фотокнигу 10%"
            )

    # Індивідуальна
    if pkg_key == "exp":
        price = "7 000 грн" if city_key == "kyiv" else "6 000 грн"
        return (
            f"🧑 <b>Індивідуальна — {city_label}</b>\n"
            f"<b>Пакет «Експрес-фотосесія» — {price}</b>\n\n"
            "Формат лаконічної портретної студійної фотосесії\n"
            "• Оренда студії\n"
            "• 1 година зйомки\n"
            "• Близько 10 фото в авторській обробці"
        )
    if pkg_key == "std":
        price = "10 000 грн" if city_key == "kyiv" else "7 000 грн"
        return (
            f"🧑 <b>Індивідуальна — {city_label}</b>\n"
            f"<b>Пакет «Стандарт» — {price}</b>\n\n"
            "• Консультації перед фотосесією: допомога із ідеями, підбором одягу та локацій\n"
            "• 1,5–2 години зйомки\n"
            "• Близько 15 фото в авторській обробці\n"
            "• Усі вдалі фото в базовій обробці (близько 80 шт.)\n"
            "• Знижка на фотокнигу 10%"
        )
    if pkg_key == "all":
        price = "26 000 грн" if city_key == "kyiv" else "18 000 грн"
        return (
            f"🧑 <b>Індивідуальна — {city_label}</b>\n"
            f"<b>Пакет «Все враховано» — {price}</b>\n\n"
            "• Консультації перед фотосесією\n"
            "• 2 години зйомки\n"
            "• Оренда фотостудії\n"
            "• Робота візажиста та перукаря\n"
            "• Робота стиліста (2 різних образи)\n"
            "• Близько 20 фото в авторській обробці\n"
            "• Усі вдалі фото в базовій обробці (близько 90 шт.)\n\n"
            "Обираючи цей пакет, Вам не потрібно турбуватися ні про що: студію підбирають і бронюють. "
            "Візажист/перукар приїжджає до Вас або в студію та створює образ. "
            "Стиліст підбирає та привозить одяг та аксесуари, супроводжуючи на зйомці. "
            "І Ви — у дбайливому оточенні професіоналів, які думають за Вас."
        )
    return "Опис пакета в підготовці 🙂"

@dp.message(F.text == "💰 Вартість роботи")
async def price_flow_start(message: Message):
    await message.answer("Оберіть місто:", reply_markup=price_city_menu())

@dp.callback_query(F.data == "p:close")
async def price_close(call: CallbackQuery):
    await call.message.edit_text("Закрито. Оберіть пункт у меню 👇")
    await call.message.answer("Обирайте пункт у меню 👇", reply_markup=main_kb)
    await call.answer()

@dp.callback_query(F.data.in_({"p:kyiv", "p:krdn"}))
async def price_choose_city(call: CallbackQuery):
    city_key = call.data.split(":")[1]
    await call.message.edit_text(f"Місто вибрано: <b>{'Київ' if city_key=='kyiv' else 'Кривий Ріг / Дніпро'}</b>\nОберіть тип зйомки:",
                                 reply_markup=price_category_menu(city_key))
    await call.answer()

@dp.callback_query(F.data == "p:back_cities")
async def price_back_cities(call: CallbackQuery):
    await call.message.edit_text("Оберіть місто:", reply_markup=price_city_menu())
    await call.answer()

@dp.callback_query(F.data.regexp(r"^p:(kyiv|krdn):(family|indiv)$"))
async def price_choose_category(call: CallbackQuery):
    m = re.match(r"^p:(kyiv|krdn):(family|indiv)$", call.data)
    if not m:
        await call.answer(); return
    city_key, cat_key = m.group(1), m.group(2)
    label_city = "Київ" if city_key == "kyiv" else "Кривий Ріг / Дніпро"
    label_cat = "Сімейна / Вагітність" if cat_key == "family" else "Індивідуальна"

    # Якщо Київ + Сімейна — показуємо пакет одразу (без ще одного вибору)
    if city_key == "kyiv" and cat_key == "family":
        text = price_text(city_key, cat_key, "std")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            portfolio_row_for("family"),
            [InlineKeyboardButton(text="📝 Замовити цей пакет", callback_data="start_booking")],
            [InlineKeyboardButton(text="⬅️ Назад до типів", callback_data=f"p:{city_key}:back_cats")],
            [InlineKeyboardButton(text="⬅️ Назад до міст", callback_data="p:back_cities")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
        return

    await call.message.edit_text(
        f"Місто: <b>{label_city}</b>\nКатегорія: <b>{label_cat}</b>\nОберіть пакет:",
        reply_markup=price_packages_menu(city_key, cat_key)
    )
    await call.answer()

@dp.callback_query(F.data.regexp(r"^p:(kyiv|krdn):(family|indiv):(exp|std|all)$"))
async def price_show_package(call: CallbackQuery):
    m = re.match(r"^p:(kyiv|krdn):(family|indiv):(exp|std|all)$", call.data)
    if not m:
        await call.answer(); return
    city_key, cat_key, pkg_key = m.group(1), m.group(2), m.group(3)
    text = price_text(city_key, cat_key, pkg_key)
    order_kb = InlineKeyboardMarkup(inline_keyboard=[
        portfolio_row_for(cat_key),
        [InlineKeyboardButton(text="📝 Замовити цей пакет", callback_data="start_booking")],
        [InlineKeyboardButton(text="⬅️ Назад до пакетів", callback_data=f"p:{city_key}:{cat_key}")],
        [InlineKeyboardButton(text="⬅️ Назад до типів", callback_data=f"p:{city_key}:back_cats")],
        [InlineKeyboardButton(text="⬅️ Назад до міст", callback_data="p:back_cities")],
    ])
    await call.message.edit_text(text, reply_markup=order_kb)
    await call.answer()

@dp.callback_query(F.data.regexp(r"^p:(kyiv|krdn):back_cats$"))
async def price_back_categories(call: CallbackQuery):
    m = re.match(r"^p:(kyiv|krdn):back_cats$", call.data)
    if not m:
        await call.answer(); return
    city_key = m.group(1)
    await call.message.edit_text(f"Місто вибрано: <b>{'Київ' if city_key=='kyiv' else 'Кривий Ріг / Дніпро'}</b>\nОберіть тип зйомки:",
                                 reply_markup=price_category_menu(city_key))
    await call.answer()

# ---------- ФОТОКНИГА: Standard / Premium / Light ----------
class PhotoBookFlow(StatesGroup):
    kind = State()      # standard / premium / light
    format = State()    # s_30x20, s_30x30, p_20x20, p_30x30
    photos = State()    # кількість фото (тільки для standard/premium)

def photobook_kind_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Standard", callback_data="bk:std")],
        [InlineKeyboardButton(text="Premium", callback_data="bk:pre")],
        [InlineKeyboardButton(text="Light (4500 грн)", callback_data="bk:light")],
        [InlineKeyboardButton(text="⬅️ Скасувати", callback_data="bk:cancel")],
    ])

def photobook_format_menu(kind: str) -> InlineKeyboardMarkup:
    if kind == "std":
        # Вартість за 10 розворотів (UAH)
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="30×20 см — 1950 грн (за 10 розворотів)", callback_data="bkf:s_30x20")],
            [InlineKeyboardButton(text="30×30 см — 2300 грн (за 10 розворотів)", callback_data="bkf:s_30x30")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="bk:back")],
        ])
    if kind == "pre":
        # Вартість за 10 розворотів (USD)
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="20×20 см — $90 (за 10 розворотів)", callback_data="bkf:p_20x20")],
            [InlineKeyboardButton(text="30×30 см — $145 (за 10 розворотів)", callback_data="bkf:p_30x30")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="bk:back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[])

# База: ціни за 10 розворотів і макс. розвороти
BOOK_BASE = {
    "s_30x20": {"currency": "UAH", "base10": 1950, "title": "Standard 30×20 см", "max_photos": 120, "extra_rate": 0.10},
    "s_30x30": {"currency": "UAH", "base10": 2300, "title": "Standard 30×30 см", "max_photos": 120, "extra_rate": 0.10},
    "p_20x20": {"currency": "USD", "base10": 90,  "title": "Premium 20×20 см", "max_photos": 150, "extra_rate": 0.10},
    "p_30x30": {"currency": "USD", "base10": 145, "title": "Premium 30×30 см", "max_photos": 150, "extra_rate": 0.10},
}

STANDARD_DESC = (
    "<b>Standard</b>\n"
    "Ідеальне поєднання поліграфії та фотодруку. Сторінки надруковані на фотопапері — щільні, красиві, не деформуються. "
    "Розвороти на 180°.\n"
    "Обкладинка — фотообкладинка з вашим фото.\n"
    "На виготовлення дублікату книги — знижка 30%.\n"
    "Максимальна кількість розворотів: 40.\n\n"
    "<u>Додаткові можливості</u>:\n"
    "• Обкладинка з тканини або шкірозамінника — 1300 грн\n"
    "• Подарунковий короб — 750 грн"
)

PREMIUM_DESC = (
    "<b>Premium</b>\n"
    "Книги мають титульний розворот із калькою, паспарту, форзац з італійського акварельного картону, друк на шовковому папері. "
    "Технологія розгортання на 180° дає широкі можливості дизайну.\n"
    "Знижка 30% на дублікат книги.\n"
    "Максимальна кількість розворотів: 50.\n\n"
    "<u>Варіанти обкладинок</u>:\n"
    "• Тканина (можна з фото/написом)\n"
    "• Шкіра (можна з фото/написом)\n"
    "• Кожзам (можна з фото/написом)\n\n"
    "<u>Додатково</u>:\n"
    "• Короб для фотокниг із високоякісних палітурних матеріалів — 600–1000 грн (залежно від розміру)"
)

LIGHT_DESC = (
    "<b>Light — 4500 грн</b>\n"
    "Чудовий варіант, якщо у вас багато фото й хочеться надрукувати все.\n"
    "Розмір: 30×30 см. Вміщує до 100 фотографій.\n"
    "Поліграфічний друк на висококласному обладнанні; сторінки схожі на журнальні, але щільніші.\n"
    "Обкладинка — тканина або шкірзам (на вибір).\n"
    "Легка та візуально виразна книга. Знижка 30% на дублікат."
)

@dp.message(F.text == "📖 Фотокнига")
async def photobook_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(PhotoBookFlow.kind)
    await message.answer("Оберіть тип фотокниги:", reply_markup=photobook_kind_menu())

@dp.callback_query(F.data == "bk:cancel")
async def bk_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Скасовано. Обирайте пункт у меню 👇")
    await call.message.answer("Обирайте пункт у меню 👇", reply_markup=main_kb)
    await call.answer()

@dp.callback_query(F.data == "bk:back")
async def bk_back(call: CallbackQuery, state: FSMContext):
    await state.set_state(PhotoBookFlow.kind)
    await call.message.edit_text("Оберіть тип фотокниги:", reply_markup=photobook_kind_menu())
    await call.answer()

@dp.callback_query(F.data.in_({"bk:std", "bk:pre", "bk:light"}))
async def bk_choose_kind(call: CallbackQuery, state: FSMContext):
    kind = call.data.split(":")[1]  # std/pre/light
    await state.update_data(kind=kind)
    if kind == "light":
        # Без розрахунків — просто показуємо опис і ціну
        text = LIGHT_DESC
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="bk:back")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="bk:cancel")],
        ])
        await call.message.edit_text(text, reply_markup=kb)
        await call.answer()
        return

    await state.set_state(PhotoBookFlow.format)
    await call.message.edit_text("Оберіть формат (вартість вказана за <b>10 розворотів</b>):",
                                 reply_markup=photobook_format_menu(kind))
    await call.answer()

@dp.callback_query(F.data.regexp(r"^bkf:(s_30x20|s_30x30|p_20x20|p_30x30)$"))
async def bk_choose_format(call: CallbackQuery, state: FSMContext):
    m = re.match(r"^bkf:(s_30x20|s_30x30|p_20x20|p_30x30)$", call.data)
    if not m:
        await call.answer(); return
    fmt = m.group(1)
    await state.update_data(format=fmt)
    await state.set_state(PhotoBookFlow.photos)

    base = BOOK_BASE[fmt]
    cur = "грн" if base["currency"] == "UAH" else "$"
    await call.message.edit_text(
        (
            f"Вибрано: <b>{base['title']}</b>\n"
            f"Вартість за 10 розворотів: <b>{base['base10']} {cur}</b>\n"
            f"Додатковий розворот: <b>10% від вартості за 10 розворотів</b>\n"
            f"Межі кількості фото: <b>мін. 5</b> · <b>макс. {base['max_photos']}</b>\n\n"
            "Хочете, я порахую необхідні Вам розвороти? Введіть кількість ваших фото (числом)."
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="bk:back")]
        ])
    )

@dp.message(PhotoBookFlow.photos, F.text.regexp(r"^\d{1,4}$"))
async def bk_enter_photos(message: Message, state: FSMContext):
    data = await state.get_data()
    fmt = data.get("format")
    if not fmt or fmt not in BOOK_BASE:
        await state.clear()
        await message.answer("Сталася помилка. Почніть знову: «📖 Фотокнига».")
        return

    photos = int(message.text.strip())
    base = BOOK_BASE[fmt]
    base10 = base["base10"]
    currency = base["currency"]
    max_photos = base["max_photos"]      # 120 для Standard, 150 для Premium
    min_photos = 5

    # --- Валідація: якщо поза межами, не рахуємо, лише підказка ---
    if photos < min_photos or photos > max_photos:
        await message.answer(
            (
                f"Будь ласка, введіть кількість фото в межах: "
                f"<b>{min_photos}…{max_photos}</b> для «{base['title']}».\n"
                "Спробуйте ще раз 🙂"
            )
        )
        # залишаємо стан PhotoBookFlow.photos, щоб користувач ввів знову
        return

    # --- Розрахунок ---
    spreads = math.ceil(photos / 3)                     # 1 розворот = 3 фото
    extra_spreads = max(0, spreads - 10)                # все, що понад базові 10
    extra_cost_per_spread = base10 * base["extra_rate"] # 10% від бази за 10 розворотів
    total = base10 + extra_spreads * extra_cost_per_spread

    cur = "грн" if currency == "UAH" else "$"
    detail = (
        f"📖 <b>Розрахунок</b>\n"
        f"Формат: {base['title']}\n"
        f"Фото: {photos}\n"
        f"Розворотів потрібно: {spreads} (1 розворот = 3 фото)\n"
        f"Базова ціна (10 розворотів): {base10} {cur}\n"
        f"Додаткові розвороти: {extra_spreads} × {extra_cost_per_spread:.0f} {cur}\n"
        f"До сплати: <b>{total:.0f} {cur}</b>\n\n"
    )

    desc = STANDARD_DESC if fmt.startswith("s_") else PREMIUM_DESC
    await state.clear()
    await message.answer(detail + desc)
    await message.answer("Повертаюсь до меню 👇", reply_markup=main_kb)


@dp.message(PhotoBookFlow.photos)
async def bk_photos_invalid(message: Message):
    await message.answer("Будь ласка, введіть число (кількість фото), наприклад: 24, 37 або 90.")

# ---------- БРОНЮВАННЯ (без дати та телефону) ----------
class Booking(StatesGroup):
    name = State()
    note = State()

@dp.message(F.text == "📝 Замовити фотосесію")
async def booking_start_btn(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Booking.name)
    await message.answer("Як до вас звертатися? (Ім’я)")

@dp.callback_query(F.data == "start_booking")
async def booking_start_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(Booking.name)
    await call.message.edit_text("Як до вас звертатися? (Ім’я)")
    await call.answer()

@dp.message(Booking.name, F.text)
async def booking_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(Booking.note)
    await message.answer("Коротко опишіть запит (місто/тип/пакет/побажання). Або «–».")

@dp.message(Booking.note, F.text)
async def booking_finish(message: Message, state: FSMContext):
    await state.update_data(note=message.text.strip())
    data = await state.get_data()
    await state.clear()

    name = html.escape(data.get('name',''))
    note = html.escape(data.get('note',''))
    user = html.escape(message.from_user.username or str(message.from_user.id))

    summary = (
        "✅ <b>Нова заявка на зйомку</b>\n"
        f"• Ім'я: {name}\n"
        f"• Коментар: {note}\n"
        f"• Від: @{user}"
    )
    if ADMIN_ID > 0:
        try:
            await bot.send_message(ADMIN_ID, summary)
        except Exception as e:
            logging.warning(f"Не вдалося надіслати адміну: {e}")
    await message.answer(summary)
    await message.answer("Дякую! Я на зв'язку й підтверджу бронювання найближчим часом.")
    await message.answer("Повертаюсь до меню 👇", reply_markup=main_kb)

# ---------- Інші головні кнопки ----------
@dp.message(F.text == "📅 Вільні дати")
async def free_dates(message: Message):
    await message.answer(FREE_DATES)

@dp.message(F.text == "🎁 Сертифікат")
async def cert_gift(message: Message):
    await message.answer(CERT_GIFT)

@dp.message(F.text == "📞 Контакти")
async def contacts(message: Message):
    await message.answer(CONTACTS)

# ---------- ЗАГАЛЬНИЙ роутер (тільки коли немає стану) ----------
@dp.message(StateFilter(None), F.text)
async def router(message: Message, state: FSMContext):
    await message.answer("Скористайтесь кнопками нижче або напишіть /help 🙂", reply_markup=main_kb)

# ---------- Команди ----------
@dp.message(CommandStart())
async def start(message: Message):
    await message.answer("Обирайте пункт у меню 👇", reply_markup=main_kb)

@dp.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer("Скористайтесь кнопками нижче — головні розділи вже готові.", reply_markup=main_kb)

@dp.message(Command("ping"))
async def ping(message: Message):
    await message.answer("pong ✅")

# ---------- Запуск ----------
if __name__ == "__main__":
    import asyncio
    print("Bot is running…")
    async def main():
        await dp.start_polling(bot)
    asyncio.run(main())
