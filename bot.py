import os
import sqlite3
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "shop.db")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

ADD_NAME, ADD_PRICE, ADD_DESCRIPTION, ADD_PHOTO, ORDER_NAME, ORDER_PHONE, ORDER_REGION, ORDER_DISTRICT, ORDER_LOCATION = range(9)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL,
        description TEXT DEFAULT '',
        photo_id TEXT,
        created_at TEXT NOT NULL
    );

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
);
    """)
    conn.commit()
    conn.close()


def get_setting(key):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def is_admin(user_id):
    admin_id = get_setting("admin_id")
    return admin_id and str(user_id) == admin_id


def money(n):
    return f"{n:,}".replace(",", " ") + " so'm"


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Katalog", callback_data="catalog")],
        [InlineKeyboardButton("📦 Mening buyurtmalarim", callback_data="my_orders")],
        [InlineKeyboardButton("📞 Aloqa", callback_data="contact")],
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="admin_add")],
        [InlineKeyboardButton("📦 Mahsulotlar", callback_data="admin_products")],
        [InlineKeyboardButton("📋 Buyurtmalar", callback_data="admin_orders")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "🛍 KXS Brand Shop'ga xush kelibsiz.\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu(),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current = get_setting("admin_id")

    if current is None:
        set_setting("admin_id", user_id)
        await update.message.reply_text(
            "🔐 Siz birinchi admin sifatida belgilandingiz.\n\n"
            "Admin panel:",
            reply_markup=admin_menu(),
        )
        return

    if is_admin(user_id):
        await update.message.reply_text("👨‍💼 Admin panel", reply_markup=admin_menu())
    else:
        await update.message.reply_text("⛔ Sizda admin huquqi yo'q.")


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if q.data == "catalog":
        conn = db()
        products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        conn.close()

        if not products:
            await q.message.reply_text("📭 Hozircha katalog bo'sh.")
            return

        for p in products:
            text = f"🛍 <b>{p['name']}</b>\n💰 {money(p['price'])}"
            if p["description"]:
                text += f"\n\n{p['description']}"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Buyurtma berish", callback_data=f"order:{p['id']}")]
            ])
            if p["photo_id"]:
                await q.message.reply_photo(
                    photo=p["photo_id"], caption=text,
                    parse_mode="HTML", reply_markup=kb
                )
            else:
                await q.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        return

    if q.data == "contact":
        await q.message.reply_text(
            "📞 Aloqa\n\n"
            "Buyurtma yoki savollar bo'yicha admin bilan bog'laning."
        )
        return

    if q.data == "my_orders":
        conn = db()
        rows = conn.execute("""
            SELECT o.id, o.status, o.created_at, p.name
            FROM orders o JOIN products p ON p.id=o.product_id
            WHERE o.user_id=? ORDER BY o.id DESC
        """, (user_id,)).fetchall()
        conn.close()
        if not rows:
            await q.message.reply_text("📭 Sizda hali buyurtmalar yo'q.")
            return
        text = "📦 <b>Mening buyurtmalarim</b>\n\n"
        for r in rows:
            text += f"#{r['id']} — {r['name']} — <b>{r['status']}</b>\n"
        await q.message.reply_text(text, parse_mode="HTML")
        return

    if q.data.startswith("order:"):
        product_id = int(q.data.split(":")[1])
        conn = db()
        
        p = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not p:
            conn.close()
            await q.message.reply_text("❌ Mahsulot topilmadi.")
            return
        conn.execute(
            "INSERT INTO orders(user_id,username,product_id,status,created_at) VALUES(?,?,?,?,?)",
            (user_id, q.from_user.username or "", product_id, "new",
             datetime.now().isoformat(timespec="seconds"))
        )
        order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        admin_id = get_setting("admin_id")
        if admin_id:
            await q.get_bot().send_message(
                chat_id=int(admin_id),
                text=(
                    f"🔔 YANGI BUYURTMA!\n\n"
                    f"📦 Mahsulot: {p['name']}\n"
                    f"💰 Narxi: {money(p['price'])}\n"
                    f"👤 Xaridor: @{q.from_user.username or 'username yo‘q'}\n"
                    f"🆔 User ID: {user_id}\n"
                    f"📋 Buyurtma №{order_id}"
                )
        )
 
        await q.message.reply_text(
            f"✅ Buyurtmangiz qabul qilindi!\n\n"
            f"🛍 {p['name']}\n"
            f"💰 {money(p['price'])}\n"
            f"📋 Buyurtma №{order_id}\n\n"
            "Admin siz bilan bog'lanadi."
        )
        return

    if q.data.startswith("admin_"):
        if not is_admin(user_id):
            await q.message.reply_text("⛔ Admin huquqi yo'q.")
            return

        if q.data == "admin_add":
            context.user_data["adding"] = {}
            await q.message.reply_text("1/4 📝 Mahsulot nomini yuboring:")
            return ADD_NAME

        if q.data == "admin_products":
            conn = db()
            rows = conn.execute("SELECT id,name,price FROM products ORDER BY id DESC").fetchall()
            conn.close()
            if not rows:
                await q.message.reply_text("📭 Mahsulotlar yo'q.")
                return
            text = "📦 <b>Mahsulotlar</b>\n\n"
            for r in rows:
                text += f"#{r['id']} — {r['name']} — {money(r['price'])}\n"
            await q.message.reply_text(text, parse_mode="HTML")
            return

        if q.data == "admin_orders":
            conn = db()
            rows = conn.execute("""
                SELECT o.id,o.username,o.status,o.created_at,p.name,p.price
                FROM orders o JOIN products p ON p.id=o.product_id
                ORDER BY o.id DESC LIMIT 30
            """).fetchall()
            conn.close()
            if not rows:
                await q.message.reply_text("📭 Buyurtmalar yo'q.")
                return
            text = "📋 <b>So'nggi buyurtmalar</b>\n\n"
            for r in rows:
                who = "@" + r["username"] if r["username"] else "username yo'q"
                text += f"#{r['id']} | {r['name']} | {who} | {r['status']}\n"
            await q.message.reply_text(text, parse_mode="HTML")
            return


async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    product_id = int(q.data.split(":")[1])

    conn = db()
    p = conn.execute(
        "SELECT * FROM products WHERE id=?",
        (product_id,)
    ).fetchone()
    conn.close()

    if not p:
        await q.message.reply_text("❌ Mahsulot topilmadi.")
        return ConversationHandler.END

    context.user_data["order"] = {
        "product_id": product_id,
        "product_name": p["name"],
        "price": p["price"],
    }

    await q.message.reply_text(
        "👤 Buyurtma uchun ismingizni kiriting:"
    )

    return ORDER_NAME


async def order_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order"]["customer_name"] = update.message.text.strip()

    await update.message.reply_text(
        "📞 Telefon raqamingizni yuboring:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
    )

    return ORDER_PHONE


async def order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()

    context.user_data["order"]["phone"] = phone

    await update.message.reply_text(
        "🏙 Qaysi viloyatga yetkazib beramiz?",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["Toshkent shahri", "Toshkent viloyati"],
                ["Andijon", "Farg‘ona"],
                ["Namangan", "Sirdaryo"],
                ["Jizzax", "Samarqand"],
                ["Qashqadaryo", "Surxondaryo"],
                ["Buxoro", "Navoiy"],
                ["Xorazm", "Qoraqalpog‘iston"]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
    )

    async def order_district(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order"]["district"] = update.message.text.strip()

    await update.message.reply_text(
        "📌 Endi yetkazib berish lokatsiyangizni yuboring:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Lokatsiyani yuborish", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
    )

    return ORDER_LOCATION
    
    

    




    
    async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data["adding"]["name"] = update.message.text.strip()
    await update.message.reply_text("2/4 💰 Narxini faqat raqam bilan yuboring. Masalan: 250000")
    return ADD_PRICE


async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    try:
        price = int(update.message.text.replace(" ", "").replace(",", ""))
        if price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Narx noto'g'ri. Masalan: 250000")
        return ADD_PRICE
    context.user_data["adding"]["price"] = price
    await update.message.reply_text("3/4 📝 Mahsulot tavsifini yuboring:")
    return ADD_DESCRIPTION


async def add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data["adding"]["description"] = update.message.text.strip()
    await update.message.reply_text("4/4 🖼 Mahsulot rasmini yuboring:")
    return ADD_PHOTO


async def add_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text("❌ Iltimos, rasm yuboring.")
        return ADD_PHOTO

    data = context.user_data["adding"]
    photo_id = update.message.photo[-1].file_id

    conn = db()
    conn.execute(
        "INSERT INTO products(name,price,description,photo_id,created_at) VALUES(?,?,?,?,?)",
        (data["name"], data["price"], data["description"], photo_id,
         datetime.now().isoformat(timespec="seconds"))
    )
    conn.commit()
    product_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()

    context.user_data.pop("adding", None)
    await update.message.reply_text(
        f"✅ Mahsulot qo'shildi!\n\n"
        f"ID: #{product_id}\n"
        f"🛍 {data['name']}\n"
        f"💰 {money(data['price'])}",
        reply_markup=admin_menu(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("adding", None)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=admin_menu())
    return ConversationHandler.END


async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Quyidagi menyudan foydalaning:",
        reply_markup=main_menu()
    )

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    add_product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(buttons, pattern="^admin_add$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_price)],
            ADD_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_description)],
            ADD_PHOTO: [MessageHandler(filters.PHOTO, add_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(add_product_conv)
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback))

    log.info("KXS BRAND SHOP BOT STARTED")
    threading.Thread(target=run_web_server, daemon=True).start()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
