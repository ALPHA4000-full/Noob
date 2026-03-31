CURRENCIES = [
    {"id": "uzcard",      "name": "UZCARD",        "icon": "💎", "type": "card"},
    {"id": "humo",        "name": "HUMO",           "icon": "💎", "type": "card"},
    {"id": "tron",        "name": "TRON (TRX)",     "icon": "💎", "type": "crypto"},
    {"id": "bnb",         "name": "BINANCECOIN (BNB)", "icon": "💎", "type": "crypto"},
    {"id": "solana",      "name": "SOLANA (SOL)",   "icon": "💎", "type": "crypto"},
    {"id": "litecoin",    "name": "LITECOIN (LTC)",  "icon": "💎", "type": "crypto"},
    {"id": "dogecoin",    "name": "DOGECOIN (DOGE)", "icon": "💎", "type": "crypto"},
    {"id": "toncoin",     "name": "TONCOIN (TON)",   "icon": "💎", "type": "crypto"},
]

PAYMENT_CARDS = {
    "uzcard": "8600 0000 0000 0000",
    "humo":   "9860 0000 0000 0000",
}

def get_currency_by_id(currency_id: str) -> dict | None:
    for c in CURRENCIES:
        if c["id"] == currency_id:
            return c
    return None


def get_rate_key(from_id: str, to_id: str) -> str:
    return f"{from_id}:{to_id}"
