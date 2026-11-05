"""Feature: i18n UA/EN in the UI — JSON dictionaries, browser-language
auto-detect, saved choice, a language switcher. Russian is never added
(political decision of the owner)."""
import json
import re

from fastapi.testclient import TestClient


def test_i18n_js_served(client):
    r = client.get("/static/i18n.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]


def test_dictionaries_cover_both_languages(client):
    src = client.get("/static/i18n.js").text
    def block(lang):
        m = re.search(rf"{lang}: (\{{.*?\n  \}}),\n", src, re.S)
        text = re.sub(r"^(\s*)([A-Za-z_]\w*): ", r'\1"\2": ', m.group(1), flags=re.M)
        text = re.sub(r",(\s*\})$", r"\1", text)  # trailing comma -> valid JSON
        return json.loads(text)
    uk, en = block("uk"), block("en")
    assert set(uk) == set(en) and len(uk) >= 50
    # every key differs (actually translated, not copy-paste)
    different = sum(1 for k in uk if uk[k] != en[k])
    assert different >= len(uk) * 0.9


def test_no_russian_localization(client):
    """Cyrillic strings in the dictionaries must be Ukrainian only:
    Ukrainian glossary markers present, Russian-only markers absent."""
    src = client.get("/static/i18n.js").text
    assert "і" in src.lower() or "нагадування" in src  # ukrainian words present
    for ru_word in ("напоминание", "напоминания", "счёт", "счета", "настройки",
                    "клиент", "оплата объявлена"):
        assert ru_word not in src


def test_index_has_language_switch_and_i18n_hooks(client):
    html = client.get("/").text
    assert 'id="langSwitch"' in html
    assert html.count("data-i18n=") >= 20
    assert "applyLang" in html and "currentLang" in html
    # auto-detect + localStorage persistence logic present
    assert "localStorage" in html or "localStorage" in client.get("/static/i18n.js").text


def test_index_is_ukrainian_by_default(client):
    html = client.get("/").text
    assert '<html lang="uk">' in html
    assert "нагадування пишуться самі" in html


def test_static_asset_not_traversed(client):
    assert client.get("/static/../main.py").status_code in (404, 307)
