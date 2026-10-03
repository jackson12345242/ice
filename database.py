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
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        try:
            await db.execute("ALTER TABLE splits ADD COLUMN reminder_sent INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
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
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS used_tx_ids (
                tx_id TEXT PRIMARY KEY,
                split_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                brainrot_key TEXT,
                other_name TEXT,
                direction TEXT,
                quantity INTEGER,
                amount REAL,
                image_url TEXT,
                batch_id TEXT,
                logged_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        try:
            await db.execute("ALTER TABLE payment_logs ADD COLUMN direction TEXT")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE payment_logs ADD COLUMN batch_id TEXT")
        except Exception:
            pass
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                brainrot_key TEXT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS rule_agreements (
                user_id INTEGER PRIMARY KEY,
                agreed_at TEXT NOT NULL DEFAULT (datetime('now'))
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


async def remove_wallet(user_id: int, coin: str, network: str = "") -> int:
    """Deletes the wallet matching this exact (user_id, coin, network) — the same composite
    key add_wallet upserts on. coin/network should be passed exactly as returned by
    get_wallets (already upper-cased), not re-normalized, so the match is exact.
    Returns the number of rows deleted (0 or 1, since that key is unique)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM wallets WHERE user_id = ? AND coin = ? AND network = ?",
            (user_id, coin, network or ""),
        )
        await db.commit()
        return cursor.rowcount


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
            "SELECT id, creator_id, brainrot, total_amount, team_size, per_person_amount, channel_id, "
            "message_id, reminder_sent, created_at "
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
            "reminder_sent": bool(row[8]),
            "created_at": row[9],
        }


async def mark_split_reminder_sent(split_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE splits SET reminder_sent = 1 WHERE id = ?", (split_id,))
        await db.commit()


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


async def is_tx_used(tx_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM used_tx_ids WHERE tx_id = ?", (tx_id,))
        row = await cursor.fetchone()
        return row is not None


async def mark_tx_used(tx_id: str, split_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO used_tx_ids (tx_id, split_id, user_id) VALUES (?, ?, ?)",
            (tx_id, split_id, user_id),
        )
        await db.commit()


async def get_split_summary(split_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, amount_paid, coin, tx_id FROM split_payments WHERE split_id = ? AND paid = 1",
            (split_id,),
        )
        rows = await cursor.fetchall()
        return [{"user_id": r[0], "amount_paid": r[1], "coin": r[2], "tx_id": r[3]} for r in rows]


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


# ---------- Payment logs ----------

async def log_payment_brainrot(user_id: int, brainrot_key: str, other_name: str, quantity: int, image_url: str, direction: str = "received", batch_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO payment_logs (user_id, kind, brainrot_key, other_name, direction, quantity, amount, image_url, batch_id)
            VALUES (?, 'brainrot', ?, ?, ?, ?, NULL, ?, ?)
            """,
            (user_id, brainrot_key, other_name, direction, quantity, image_url, batch_id),
        )
        await db.commit()


async def log_payment_money(user_id: int, amount: float, image_url: str = None, batch_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO payment_logs (user_id, kind, brainrot_key, other_name, quantity, amount, image_url, batch_id)
            VALUES (?, 'money', NULL, NULL, NULL, ?, ?, ?)
            """,
            (user_id, amount, image_url, batch_id),
        )
        await db.commit()


async def get_payment_summary(user_id: int):
    """Returns (received_totals, paid_totals, money_total). Each totals dict is
    {group_key: {'key', 'other_name', 'quantity'}}."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT brainrot_key, other_name, quantity, direction FROM payment_logs WHERE user_id = ? AND kind = 'brainrot'",
            (user_id,),
        )
        rows = await cursor.fetchall()

        cursor2 = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payment_logs WHERE user_id = ? AND kind = 'money'",
            (user_id,),
        )
        money_row = await cursor2.fetchone()

    received = {}
    paid = {}
    for key, other_name, qty, direction in rows:
        target = paid if direction == "paid" else received
        group_key = key if key != "other" else f"other:{(other_name or 'Other').lower()}"
        if group_key not in target:
            target[group_key] = {"key": key, "other_name": other_name, "quantity": 0}
        target[group_key]["quantity"] += qty or 0

    return received, paid, (money_row[0] if money_row else 0.0)


async def get_leaderboard_money():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT user_id, SUM(amount) as total
            FROM payment_logs
            WHERE kind = 'money'
            GROUP BY user_id
            HAVING total > 0
            ORDER BY total DESC
            """
        )
        rows = await cursor.fetchall()
        return [{"user_id": r[0], "total": r[1]} for r in rows]


async def get_leaderboard_brainrot_rows():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, brainrot_key, other_name, quantity, direction FROM payment_logs WHERE kind = 'brainrot'"
        )
        return await cursor.fetchall()


async def clear_payment_money(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM payment_logs WHERE user_id = ? AND kind = 'money'", (user_id,))
        await db.commit()


async def adjust_payment_money(user_id: int, amount: float):
    await log_payment_money(user_id, -amount, None)


async def clear_payment_brainrot(user_id: int, brainrot_key: str = None, direction: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        query = "DELETE FROM payment_logs WHERE user_id = ? AND kind = 'brainrot'"
        params = [user_id]
        if brainrot_key:
            query += " AND brainrot_key = ?"
            params.append(brainrot_key)
        if direction:
            query += " AND direction = ?"
            params.append(direction)
        await db.execute(query, params)
        await db.commit()


async def adjust_payment_brainrot(user_id: int, brainrot_key: str, quantity: int, direction: str):
    await log_payment_brainrot(user_id, brainrot_key, None, -quantity, None, direction)


async def get_last_brainrot_trade(user_id: int):
    """Returns the user's most recent *real* received-brainrot log (quantity > 0, so
    admin corrections via adjust_payment_brainrot — which log negative quantities —
    are ignored), paired with whatever was given in that same batch. This doubles as
    'last payment activity' for inactivity tracking, since every /payment log action
    (trade or money payment) always logs a received-brainrot row in its batch.

    Returns None if the user has never received a brainrot, else:
    {
        "logged_at": "YYYY-MM-DD HH:MM:SS" (UTC, sqlite's datetime('now') format),
        "received": {"key": str, "other_name": str|None, "quantity": int},
        "paid_brainrot": {"key": str, "other_name": str|None, "quantity": int} | None,
        "paid_money": float | None,
    }
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT brainrot_key, other_name, quantity, logged_at, batch_id FROM payment_logs "
            "WHERE user_id = ? AND kind = 'brainrot' AND direction = 'received' AND quantity > 0 "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        key, other_name, qty, logged_at, batch_id = row
        result = {
            "logged_at": logged_at,
            "received": {"key": key, "other_name": other_name, "quantity": qty},
            "paid_brainrot": None,
            "paid_money": None,
        }

        if batch_id:
            cursor2 = await db.execute(
                "SELECT kind, brainrot_key, other_name, quantity, amount FROM payment_logs "
                "WHERE user_id = ? AND batch_id = ? AND (direction != 'received' OR direction IS NULL)",
                (user_id, batch_id),
            )
            for kind, p_key, p_other_name, p_qty, p_amount in await cursor2.fetchall():
                if kind == "brainrot" and p_qty and p_qty > 0:
                    result["paid_brainrot"] = {"key": p_key, "other_name": p_other_name, "quantity": p_qty}
                elif kind == "money" and p_amount and p_amount > 0:
                    result["paid_money"] = p_amount

        return result


# ---------- Contributions (who gave what to the fund) ----------

async def add_contribution(kind: str, brainrot_key: str, user_id: int, amount: float):
    """kind is 'brainrot' or 'money'. brainrot_key is the brainrot's key for 'brainrot'
    contributions, or None for 'money' ones."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO contributions (kind, brainrot_key, user_id, amount) VALUES (?, ?, ?, ?)",
            (kind, brainrot_key, user_id, amount),
        )
        await db.commit()


async def get_contribution_totals(kind: str, brainrot_key: str = None) -> dict:
    """Returns {user_id: total_amount} for this kind (and brainrot_key, if given),
    only including contributors whose running total is still > 0."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, SUM(amount) FROM contributions "
            "WHERE kind = ? AND brainrot_key IS ? "
            "GROUP BY user_id HAVING SUM(amount) > 0",
            (kind, brainrot_key),
        )
        rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}


async def remove_contributions(kind: str, brainrot_key: str, amount: float):
    """Consumes `amount` from the oldest still-positive contribution records for this
    kind/brainrot_key (FIFO — first contributed, first removed), reducing each record's
    remaining amount as it goes. Returns (taken, shortfall):
        taken: [{'user_id': ..., 'amount': ...}, ...] — how much was taken from whom
        shortfall: amount that couldn't be matched to any contributor record
    """
    taken = []
    remaining = amount
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, user_id, amount FROM contributions "
            "WHERE kind = ? AND brainrot_key IS ? AND amount > 0 "
            "ORDER BY id ASC",
            (kind, brainrot_key),
        )
        rows = await cursor.fetchall()

        for row_id, user_id, row_amount in rows:
            if remaining <= 0:
                break
            take = min(row_amount, remaining)
            await db.execute(
                "UPDATE contributions SET amount = ? WHERE id = ?",
                (row_amount - take, row_id),
            )
            remaining -= take
            taken.append({"user_id": user_id, "amount": take})

        await db.commit()

    return taken, remaining


# ---------- Rule agreements ----------

async def has_agreed_to_rules(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM rule_agreements WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row is not None


async def record_rule_agreement(user_id: int) -> bool:
    """Inserts the agreement if this user hasn't agreed before.
    Returns True if this call actually recorded it (first time),
    False if they had already agreed (INSERT was ignored)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT OR IGNORE INTO rule_agreements (user_id) VALUES (?)", (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def clear_all_payments():
    """Deletes every row from payment_logs — resets money + brainrot logs (paid and
    received) for every user. Does not touch fund_items/fund_money or splits."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM payment_logs")
        await db.commit()
