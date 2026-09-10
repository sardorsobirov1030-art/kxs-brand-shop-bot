import os
import sqlite3
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ============================================================
# KXS BRAND SHOP BOT
# Clean version for Render + SQLite + python-telegram-bot
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "shop.db")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable topilmadi.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("kxs-shop")


# ============================================================
# STATES
# ============================================================

(
    ADD_NAME,
    ADD_PRICE,
    ADD_DESCRIPTION,
    ADD_PHOTO,
    ORDER_NAME,
    ORDER_PHONE,
    ORDER_REGION,
    ORDER_DISTRICT,
    ORDER_LOCATION,
) = range(9)


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            description TEXT DEFAULT '',
            photo_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            product_id INTEGER NOT NULL,
            customer_name TEXT,
            phone TEXT,
            region TEXT,
            district TEXT,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TEXT NOT NULL
        )
        """
    )

    # Existing old database bo'lsa, yangi ustunlarni qo'shib beradi.
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    }

    migrations = {
        "customer_name": "ALTER TABLE orders ADD COLUMN customer_name TEXT",
        "phone": "ALTER TABLE orders ADD COLUMN phone TEXT",
        "region": "ALTER TABLE orders ADD COLUMN region TEXT",
        "district": "ALTER TABLE orders ADD COLUMN district TEXT",
        "location": "ALTER TABLE orders ADD COLUMN location TEXT",
    }

    for column, sql in migrations.items():
        if column not in existing:
            conn.execute(sql)

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def is_admin(user_id):
    admin_id = get_setting("admin_id")
    return bool(admin_id and int(admin_id) == int(user_id))


def money(value):
    return f"{int(value):,}".replace(",", " ") + " so'm"


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛍 Mahsulotlar", callback_data="catalog")],
            [InlineKeyboardButton("📦 Mening buyurtmalarim", callback_data="my_orders")],
            [InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="admin_add")],
            [InlineKeyboardButton("📦 Mahsulotlar", callback_data="admin_products")],
            [InlineKeyboardButton("🧾 Buyurtmalar", callback_data="admin_orders")],
        ]
    )


def product_keyboard(product_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛒 Buyurtma berish", callback_data=f"order:{product_id}")],
            [InlineKeyboardButton("⬅️ Mahsulotlarga qaytish", callback_data="catalog")],
        ]
    )


def regions_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["Toshkent shahri", "Toshkent viloyati"],
            ["Andijon", "Farg'ona"],
            ["Namangan", "Sirdaryo"],
            ["Jizzax", "Samarqand"],
            ["Qashqadaryo", "Surxondaryo"],
            ["Buxoro", "Navoiy"],
            ["Xorazm", "Qoraqalpog'iston"],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ============================================================
# USER COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "🛍 KXS BRAND SHOP botiga xush kelibsiz.\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu(),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_admin = get_setting("admin_id")

    if not current_admin:
        set_setting("admin_id", user_id)
        await update.message.reply_text(
            "👑 Siz botning admini sifatida o'rnatildingiz.",
            reply_markup=admin_menu(),
        )
        return

    if is_admin(user_id):
        await update.message.reply_text(
            "⚙️ Admin panel",
            reply_markup=admin_menu(),
        )
    else:
        await update.message.reply_text("❌ Sizda admin huquqi yo'q.")


# ============================================================
# CATALOG
# ============================================================

async def show_catalog_message(message):
    conn = db()
    products = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not products:
        await message.reply_text(
            "🛍 Hozircha mahsulotlar mavjud emas.",
            reply_markup=main_menu(),
        )
        return

    for p in products:
        text = f"🛍 {p['name']}\n💰 {money(p['price'])}"
        if p["description"]:
            text += f"\n\n📝 {p['description']}"

        markup = product_keyboard(p["id"])

        if p["photo_id"]:
            await message.reply_photo(
                photo=p["photo_id"],
                caption=text,
                reply_markup=markup,
            )
        else:
            await message.reply_text(text, reply_markup=markup)


async def catalog_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    conn = db()
    products = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not products:
        await q.message.reply_text(
            "🛍 Hozircha mahsulotlar mavjud.",
            reply_markup=main_menu(),
        )
        return

    await q.message.reply_text("🛍 Mahsulotlar:")

    for p in products:
        text = f"🛍 {p['name']}\n💰 {money(p['price'])}"
        if p["description"]:
            text += f"\n\n📝 {p['description']}"

        if p["photo_id"]:
            await q.message.reply_photo(
                photo=p["photo_id"],
                caption=text,
                reply_markup=product_keyboard(p["id"]),
            )
        else:
            await q.message.reply_text(
                text,
                reply_markup=product_keyboard(p["id"]),
            )


# ============================================================
# ORDER FLOW
# ============================================================

async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    product_id = int(q.data.split(":")[1])

    conn = db()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,),
    ).fetchone()
    conn.close()

    if not product:
        await q.message.reply_text("❌ Mahsulot topilmadi.")
        return ConversationHandler.END

    context.user_data["order"] = {
        "product_id": product_id,
        "product_name": product["name"],
        "price": product["price"],
    }

    await q.message.reply_text(
        "👤 Buyurtma uchun ismingizni kiriting:"
    )
    return ORDER_NAME


async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()

    if not name:
        await update.message.reply_text("❌ Ismni kiriting:")
        return ORDER_NAME

    context.user_data["order"]["customer_name"] = name

    await update.message.reply_text(
        "📞 Telefon raqamingizni yuboring yoki yozib kiriting:",
        reply_markup=ReplyKeyboardMarkup(
            [[
                KeyboardButton(
                    "📱 Telefon raqamni yuborish",
                    request_contact=True,
                )
            ]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return ORDER_PHONE


async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()

    if not phone:
        await update.message.reply_text("❌ Telefon raqamingizni yuboring:")
        return ORDER_PHONE

    context.user_data["order"]["phone"] = phone

    await update.message.reply_text(
        "🏙 Qaysi viloyatga yetkazib beramiz?",
        reply_markup=regions_keyboard(),
    )
    return ORDER_REGION


async def order_region(update: Update, context: ContextTypes.DEFAULT_TYPE):
    region = (update.message.text or "").strip()

    if not region:
        await update.message.reply_text("❌ Viloyatni tanlang:")
        return ORDER_REGION

    context.user_data["order"]["region"] = region

    await update.message.reply_text(
        "📍 Tuman yoki shahar nomini kiriting:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ORDER_DISTRICT


async def order_district(update: Update, context: ContextTypes.DEFAULT_TYPE):
    district = (update.message.text or "").strip()

    if not district:
        await update.message.reply_text("❌ Tuman/shaharni kiriting:")
        return ORDER_DISTRICT

    context.user_data["order"]["district"] = district

    await update.message.reply_text(
        "📌 Endi Telegram orqali yetkazib berish lokatsiyangizni yuboring:",
        reply_markup=ReplyKeyboardMarkup(
            [[
                KeyboardButton(
                    "📍 Lokatsiyani yuborish",
                    request_location=True,
                )
            ]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return ORDER_LOCATION


async def order_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.location:
        await update.message.reply_text(
            "❌ Iltimos, pastdagi «📍 Lokatsiyani yuborish» tugmasini bosing."
        )
        return ORDER_LOCATION

    location = update.message.location

    order = context.user_data.get("order")
    if not order:
        await update.message.reply_text(
            "❌ Buyurtma ma'lumotlari topilmadi. Qaytadan urinib ko'ring.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    location_text = (
        f"{location.latitude:.6f}, {location.longitude:.6f}"
    )
    order["location"] = location_text

    conn = db()
    conn.execute(
        """
        INSERT INTO orders(
            user_id, username, product_id,
            customer_name, phone, region, district, location,
            status, created_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            update.effective_user.id,
            update.effective_user.username or "",
            order["product_id"],
            order["customer_name"],
            order["phone"],
            order["region"],
            order["district"],
            location_text,
            "new",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    order_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    admin_id = get_setting("admin_id")

    admin_text = (
        "🔔 YANGI BUYURTMA!\n\n"
        f"📋 Buyurtma №{order_id}\n"
        f"📦 Mahsulot: {order['product_name']}\n"
        f"💰 Narxi: {money(order['price'])}\n\n"
        f"👤 Xaridor: {order['customer_name']}\n"
        f"📞 Telefon: {order['phone']}\n"
        f"🏙 Viloyat: {order['region']}\n"
        f"📍 Tuman/shahar: {order['district']}\n"
        f"🗺 Lokatsiya: {location_text}\n"
        f"🆔 User ID: {update.effective_user.id}\n"
        f"👤 Username: @{update.effective_user.username or 'username yo‘q'}"
    )

    if admin_id:
        try:
            await context.bot.send_message(
                chat_id=int(admin_id),
                text=admin_text,
            )
            await context.bot.send_location(
                chat_id=int(admin_id),
                latitude=location.latitude,
                longitude=location.longitude,
            )
        except Exception:
            log.exception("Admin'ga buyurtma yuborishda xato")

    await update.message.reply_text(
        "✅ Buyurtmangiz qabul qilindi!\n\n"
        f"📋 Buyurtma №{order_id}\n"
        f"📦 {order['product_name']}\n"
        f"💰 {money(order['price'])}\n\n"
        "Tez orada siz bilan bog'lanamiz. Rahmat! ❤️",
        reply_markup=ReplyKeyboardRemove(),
    )

    context.user_data.pop("order", None)
    return ConversationHandler.END


async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("order", None)

    await update.message.reply_text(
        "❌ Buyurtma bekor qilindi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ============================================================
# MY ORDERS
# ============================================================

async def my_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    conn = db()
    orders = conn.execute(
        """
        SELECT o.*, p.name AS product_name, p.price AS product_price
        FROM orders o
        LEFT JOIN products p ON p.id=o.product_id
        WHERE o.user_id=?
        ORDER BY o.id DESC
        LIMIT 20
        """,
        (q.from_user.id,),
    ).fetchall()
    conn.close()

    if not orders:
        await q.message.reply_text("📦 Sizda hali buyurtmalar yo'q.")
        return

    status_map = {
        "new": "🆕 Yangi",
        "confirmed": "✅ Tasdiqlangan",
        "delivering": "🚚 Yetkazilmoqda",
        "completed": "🏁 Yetkazildi",
        "cancelled": "❌ Bekor qilingan",
    }

    lines = ["📦 Mening buyurtmalarim:\n"]

    for o in orders:
        status = status_map.get(o["status"], o["status"])
        lines.append(
            f"📋 №{o['id']} — {o['product_name'] or 'Mahsulot'}\n"
            f"💰 {money(o['product_price'] or 0)}\n"
            f"📊 {status}\n"
        )

    await q.message.reply_text("\n".join(lines))


# ============================================================
# ADMIN: ADD PRODUCT
# ============================================================

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("❌ Admin huquqi kerak.")
        return ConversationHandler.END

    context.user_data["adding"] = {}

    await q.message.reply_text("1/4 🏷 Mahsulot nomini kiriting:")
    return ADD_NAME


async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ Mahsulot nomini kiriting:")
        return ADD_NAME

    context.user_data["adding"]["name"] = name

    await update.message.reply_text("2/4 💰 Narxini faqat raqam bilan kiriting:")
    return ADD_PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    text = (update.message.text or "").replace(" ", "").replace(",", "").strip()

    if not text.isdigit():
        await update.message.reply_text(
            "❌ Narx faqat raqam bo'lishi kerak.\nMasalan: 250000"
        )
        return ADD_PRICE

    context.user_data["adding"]["price"] = int(text)

    await update.message.reply_text(
        "3/4 📝 Mahsulot tavsifini kiriting.\n"
        "Agar tavsif kerak bo'lmasa, «-» yuboring."
    )
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    description = (update.message.text or "").strip()
    if description == "-":
        description = ""

    context.user_data["adding"]["description"] = description

    await update.message.reply_text(
        "4/4 🖼 Mahsulot rasmini yuboring:"
    )
    return ADD_PHOTO


async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    if not update.message.photo:
        await update.message.reply_text("❌ Iltimos, rasm yuboring.")
        return ADD_PHOTO

    data = context.user_data.get("adding")
    if not data:
        await update.message.reply_text("❌ Ma'lumot topilmadi.")
        return ConversationHandler.END

    photo_id = update.message.photo[-1].file_id

    conn = db()
    conn.execute(
        """
        INSERT INTO products(
            name, price, description, photo_id, created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            data["name"],
            data["price"],
            data["description"],
            photo_id,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()

    product_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.close()

    context.user_data.pop("adding", None)

    await update.message.reply_text(
        "✅ Mahsulot qo'shildi!\n\n"
        f"🆔 ID: {product_id}\n"
        f"🛍 Nomi: {data['name']}\n"
        f"💰 Narxi: {money(data['price'])}",
        reply_markup=admin_menu(),
    )

    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("adding", None)

    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=admin_menu(),
    )
    return ConversationHandler.END


# ============================================================
# ADMIN: PRODUCTS
# ======
async def admin_products_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("❌ Admin huquqi kerak.")
        return

    conn = db()
    products = conn.execute(
        "SELECT * FROM products ORDER BY id DESC"
    ).fetchall()
    conn.close()

    if not products:
        await q.message.reply_text("📦 Mahsulotlar yo'q.")
        return

    for p in products:
        text = (
            f"🆔 ID: {p['id']}\n"
            f"🛍 {p['name']}\n"
            f"💰 {money(p['price'])}"
        )
        if p["description"]:
            text += f"\n📝 {p['description']}"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🗑 O'chirish",
                        callback_data=f"delete_product:{p['id']}",
                    )
                ]
            ]
        )

        await q.message.reply_text(text, reply_markup=keyboard)


async def delete_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("❌ Admin huquqi kerak.")
        return

    product_id = int(q.data.split(":")[1])

    conn = db()
    product = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,),
    ).fetchone()

    if not product:
        conn.close()
        await q.message.reply_text("❌ Mahsulot topilmadi.")
        return

    conn.execute(
        "DELETE FROM products WHERE id=?",
        (product_id,),
    )
    conn.commit()
    conn.close()

    await q.message.reply_text(
        f"🗑 «{product['name']}» o'chirildi."
    )


# ============================================================
# ADMIN: ORDERS
# ============================================================

async def admin_orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("❌ Admin huquqi kerak.")
        return

    conn = db()
    orders = conn.execute(
        """
        SELECT o.*, p.name AS product_name, p.price AS product_price
        FROM orders o
        LEFT JOIN products p ON p.id=o.product_id
        ORDER BY o.id DESC
        LIMIT 30
        """
    ).fetchall()
    conn.close()

    if not orders:
        await q.message.reply_text("🧾 Hali buyurtmalar yo'q.")
        return

    status_map = {
        "new": "🆕 Yangi",
        "confirmed": "✅ Tasdiqlangan",
        "delivering": "🚚 Yetkazilmoqda",
        "completed": "🏁 Yetkazildi",
        "cancelled": "❌ Bekor qilingan",
    }

    for o in orders:
        product_name = o["product_name"] or "O'chirilgan mahsulot"
        text = (
            f"📋 BUYURTMA №{o['id']}\n\n"
            f"📦 Mahsulot: {product_name}\n"
            f"💰 Narxi: {money(o['product_price'] or 0)}\n\n"
            f"👤 Xaridor: {o['customer_name'] or '-'}\n"
            f"📞 Telefon: {o['phone'] or '-'}\n"
            f"🏙 Viloyat: {o['region'] or '-'}\n"
            f"📍 Tuman/shahar: {o['district'] or '-'}\n"
            f"🗺 Lokatsiya: {o['location'] or '-'}\n"
            f"📊 Holat: {status_map.get(o['status'], o['status'])}"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data=f"status:{o['id']}:confirmed",
                    ),
                    InlineKeyboardButton(
                        "🚚 Yetkazish",
                        callback_data=f"status:{o['id']}:delivering",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🏁 Yetkazildi",
                        callback_data=f"status:{o['id']}:completed",
                    ),
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data=f"status:{o['id']}:cancelled",
                    ),
                ],
            ]
        )

        await q.message.reply_text(text, reply_markup=keyboard)


async def order_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.message.reply_text("❌ Admin huquqi kerak.")
        return

    _, order_id, new_status = q.data.split(":")

    conn = db()
    order = conn.execute(
        "SELECT user_id FROM orders WHERE id=?",
        (int(order_id),),
    ).fetchone()

    if not order:
        conn.close()
        await q.message.reply_text("❌ Buyurtma topilmadi.")
        return

    conn.execute(
        "UPDATE orders SET status=? WHERE id=?",
        (new_status, int(order_id)),
    )
    conn.commit()
    conn.close()

    status_map = {
        "confirmed": "✅ Buyurtmangiz tasdiqlandi.",
        "delivering": "🚚 Buyurtmangiz yetkazib berishga chiqarildi.",
        "completed": "🏁 Buyurtmangiz yetkazib berildi. Rahmat!",
        "cancelled": "❌ Buyurtmangiz bekor qilindi.",
    }

    try:
        await context.bot.send_message(
            chat_id=order["user_id"],
            text=(
                f"📋 Buyurtma №{order_id}\n\n"
                f"{status_map.get(new_status, '📊 Buyurtma holati o‘zgardi.')}"
            ),
        )
    except Exception:
        log.exception("Mijozga status yuborishda xato")

    await q.message.reply_text(
        f"✅ Buyurtma №{order_id} holati o'zgartirildi."
    )


# ============================================================
# BUTTON ROUTER
# ============================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    if q.data == "catalog":
        await catalog_callback(update, context)
        return

    if q.data == "my_orders":
        await my_orders_callback(update, context)
        return

    if q.data == "help":
        await q.answer()
        await q.message.reply_text(
            "ℹ️ Yordam\n\n"
            "🛍 Mahsulotni tanlang → 🛒 Buyurtma berish tugmasini bosing.\n"
            "Keyin ism, telefon, viloyat, tuman/shahar va lokatsiyangizni yuborasiz.\n\n"
            "Savollar bo'lsa, administrator bilan bog'laning."
        )
        return

    if q.data == "admin_products":
        await admin_products_callback(update, context)
        return

    if q.data == "admin_orders":
        await admin_orders_callback(update, context)
        return

    if q.data.startswith("delete_product:"):
        await delete_product_callback(update, context)
        return

    if q.data.startswith("status:"):
        await order_status_callback(update, context)
        return

    await q.answer()


# ============================================================
# TEXT FALLBACK
# ============================================================

async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text.lower() in {"mahsulotlar", "mahsulot", "katalog"}:
        await show_catalog_message(update.message)
        return

    if text.lower() in {"admin", "admin panel"}:
        await admin(update, context)
        return

    await update.message.reply_text(
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu(),
    )


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"KXS BRAND SHOP BOT OK")

    def log_message(self, format, *args):
        return


def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    log.info("Health server started on port %s", PORT)
    server.serve_forever()


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Customer order conversation
    order_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(order_start, pattern=r"^order:\d+$")
        ],
        states={
            ORDER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_name)
            ],
            ORDER_PHONE: [
                MessageHandler(
                    filters.CONTACT | (filters.TEXT & ~filters.COMMAND),
                    order_phone,
                )
            ],
            ORDER_REGION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_region)
            ],
            ORDER_DISTRICT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, order_district)
            ],
            ORDER_LOCATION: [
                MessageHandler(filters.LOCATION, order_location)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", order_cancel)
        ],
        allow_reentry=True,
    )

    # Admin add-product conversation
    add_product_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_start, pattern=r"^admin_add$")
        ],
        states={
            ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)
            ],
            ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)
            ],
            ADD_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)
            ],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO, add_photo)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel)
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))

    # Conversations first
    app.add_handler(order_conv)
    app.add_handler(add_product_conv)

    # Other callback buttons
    app.add_handler(CallbackQueryHandler(buttons))

    # Normal text
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback)
    )

    log.info("KXS BRAND SHOP BOT STARTED")

    threading.Thread(
        target=run_web_server,
        daemon=True,
    ).start()

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
