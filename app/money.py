"""Localized money formatting for letters and PDFs (uk/en).

uk: 1 234,56 ₴   (space thousands, comma decimals, symbol after)
en: $1,234.56    (comma thousands, dot decimals, symbol before)
"""
SYMBOLS = {
    "UAH": "₴",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "PLN": "zł",
}

LANGUAGES = ("uk", "en", "de")


def _group(digits: str, sep: str) -> str:
    """'1234567' -> '1,234,567' (sep every 3 digits from the right)."""
    out = []
    while len(digits) > 3:
        out.append(digits[-3:])
        digits = digits[:-3]
    out.append(digits)
    return sep.join(reversed(out))


def format_money(amount: float, currency: str, lang: str = "uk",
                 symbol: str | None = None) -> str:
    """Localized amount, e.g. format_money(1234.5, 'UAH', 'uk') == '1 234,50 ₴'.
    `symbol` overrides the default currency symbol (PDF fonts can't render all
    of them — pass the currency code instead)."""
    if lang not in LANGUAGES:
        lang = "en"
    symbol = symbol if symbol is not None else SYMBOLS.get(currency.upper(), currency.upper())
    negative = amount < 0
    text = f"{abs(round(amount, 2)):.2f}"
    int_part, dec_part = text.split(".")
    if lang == "uk":
        formatted = f"{_group(int_part, ' ')},{dec_part} {symbol}"
    elif lang == "de":
        formatted = f"{_group(int_part, '.')},{dec_part} {symbol}"
    else:
        formatted = f"{symbol}{_group(int_part, ',')}.{dec_part}"
    return f"-{formatted}" if negative else formatted


def pdf_symbol(currency: str) -> str:
    """Symbol usable in base-14 PDF fonts (WinAnsi); falls back to the ISO code."""
    s = SYMBOLS.get(currency.upper(), currency.upper())
    try:
        s.encode("cp1252")
        return s
    except UnicodeEncodeError:
        return currency.upper()
