import aiosqlite
from config import BRAINROTS

DB_PATH = "/data/brainrot_bot.db"


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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS splits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL,
                brainrot TEXT NOT NULL,
                total_amount REAL NOT NULL,
                team_size INTEGER NOT NULL,
                per_person_amount REAL NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS split_payments (
                split_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                paid INTEGER NOT NULL DEFAULT 0,
                tx_id TEXT,
                amount_paid REAL,
                coin TEXT,
                verified_at TEXT,
                PRIMARY KEY (split_id, user_id)
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


# ---------- Splits ----------

async def create_split(creator_id: int, brainrot: str, total_amount: float, team_size: int, channel_id: int) -> int:
    per_person_amount = total_amount / team_size
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO splits (creator_id, brainrot, total_amount, team_size, per_person_amount, channel_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            """,
            (creator_id, brainrot, total_amount, team_size, per_person_amount, channel_id),
        )
        await db.commit()
        return cursor.lastrowid


async def set_split_message(split_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE splits SET message_id = ? WHERE id = ?", (message_id, split_id)
        )
        await db.commit()


async def get_active_split():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, creator_id, brainrot, total_amount, team_size, per_person_amount, channel_id, message_id "
            "FROM splits WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "creator_id": row[1],
            "brainrot": row[2],
            "total_amount": row[3],
            "team_size": row[4],
            "per_person_amount": row[5],
            "channel_id": row[6],
            "message_id": row[7],
        }


async def get_split_payment(split_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT paid, tx_id, amount_paid, coin FROM split_payments WHERE split_id = ? AND user_id = ?",
            (split_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {"paid": bool(row[0]), "tx_id": row[1], "amount_paid": row[2], "coin": row[3]}


async def end_split(split_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE splits SET status = 'ended' WHERE id = ?", (split_id,))
        await db.commit()


async def get_split_paid_users(split_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM split_payments WHERE split_id = ? AND paid = 1", (split_id,)
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def mark_split_payment(split_id: int, user_id: int, tx_id: str, amount_paid: float, coin: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO split_payments (split_id, user_id, paid, tx_id, amount_paid, coin, verified_at)
            VALUES (?, ?, 1, ?, ?, ?, datetime('now'))
            ON CONFLICT(split_id, user_id)
            DO UPDATE SET paid = 1, tx_id = excluded.tx_id, amount_paid = excluded.amount_paid,
                          coin = excluded.coin, verified_at = excluded.verified_at
            """,
            (split_id, user_id, tx_id, amount_paid, coin),
        )
        await db.commit()
