"""Shared coin-name normalization.

Wallets are saved by free-typed text (`/wallet add coin:<text>`), so the same coin can end up
stored as "LTC", "Litecoin", "LITECOIN", "ltc", etc. Anything that compares coins across two
different wallets (matching a split payment, grouping addresses) should normalize through this
first instead of doing a raw string comparison.
"""

COIN_ALIASES = {
    "LTC": {"LTC", "LITECOIN"},
    "USDT": {
        "USDT", "TETHER",
        "USDTBEP20", "BEP20USDT", "USDT-BEP20", "USDT(BEP20)",
        "USDTBSC", "BSCUSDT",
    },
}


def normalize_coin(coin: str) -> str:
    """Map a free-typed coin string to its canonical symbol (e.g. 'Litecoin' -> 'LTC').
    Unrecognized input is just upper-cased/stripped so it still compares consistently."""
    cleaned = "".join((coin or "").split()).upper().replace("-", "").replace("(", "").replace(")", "")
    for canonical, aliases in COIN_ALIASES.items():
        if cleaned in aliases:
            return canonical
    return cleaned
