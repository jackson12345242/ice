import aiosqlite
from config import BRAINROTS

DB_PATH = "brainrot_bot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                coin TEXT NOT NULL,
                network TEXT NOT NULL DEFAULT '',
                address TEXT NOT NULL,
                UNIQUE(user_id, coin, network)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS fund_items (
                brainrot TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS fund_money (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                amount REAL NOT NULL DEFAULT 0
            )
            """
        )
        # seed rows so we can always UPDATE instead of worrying about INSERT-vs-UPDATE
        for key in BRAINROTS:
            await db.execute(
                "INSERT OR IGNORE INTO fund_items (brainrot, quantity) VALUES (?, 0)",
                (key,),
            )
        await db.execute("INSERT OR IGNORE INTO fund_money (id, amount) VALUES (1, 0)")
        await db.commit()


# ---------- Wallets ----------

async def add_wallet(user_id: int, coin: str, address: str, network: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO wallets (user_id, coin, network, address)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, coin, network)
            DO UPDATE SET address = excluded.address
            """,
            (user_id, coin.upper(), network.upper(), address),
        )
        await db.commit()


async def get_wallets(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT coin, network, address FROM wallets WHERE user_id = ? ORDER BY coin",
            (user_id,),
        )
        rows = await cursor.fetchall()
        return [{"coin": r[0], "network": r[1], "address": r[2]} for r in rows]


# ---------- Fund: brainrots ----------

async def add_brainrot(key: str, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE fund_items SET quantity = quantity + ? WHERE brainrot = ?",
            (amount, key),
        )
        await db.commit()


async def remove_brainrot(key: str, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE fund_items SET quantity = MAX(quantity - ?, 0) WHERE brainrot = ?",
            (amount, key),
        )
        await db.commit()


async def get_brainrot_totals():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT brainrot, quantity FROM fund_items")
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}


# ---------- Fund: money ----------

async def add_money(amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE fund_money SET amount = amount + ? WHERE id = 1", (amount,))
        await db.commit()


async def remove_money(amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE fund_money SET amount = MAX(amount - ?, 0) WHERE id = 1", (amount,)
        )
        await db.commit()


async def get_money_total() -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT amount FROM fund_money WHERE id = 1")
        row = await cursor.fetchone()
        return row[0] if row else 0.0
