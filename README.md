# KXS Brand Shop Bot v1.0

## Render Environment Variable
BOT_TOKEN = BotFather token

## Local run
pip install -r requirements.txt
python bot.py

## First admin
After deployment, open the bot and send:
 /admin

The first Telegram account that sends /admin becomes the admin.

## Add a product
Admin -> ➕ Mahsulot qo'shish
1. Name
2. Price
3. Description
4. Photo

## Important
For Render production, use a Persistent Disk if you want SQLite data to survive redeploys/restarts.
Set:
DB_PATH=/var/data/shop.db
and mount the Render disk at /var/data.
