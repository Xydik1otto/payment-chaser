"""Docs release checks: bilingual README, INSTALL guide, changelog, version."""
import re


def test_readme_en_exists_and_bilingual_pairing():
    ua = open("README.md", encoding="utf-8").read()
    en = open("README.en.md", encoding="utf-8").read()
    assert "README.en.md" in ua          # UA README links the EN one
    assert "README.md" in en and "Українська версія" in en  # EN links back
    assert "v1.0.0" in ua and "v1.0.0" in en
    assert "SMTP setup wizard" in en and "base currency" in en


def test_no_russian_localization_anywhere_in_docs():
    for path in ("README.md", "README.en.md", "INSTALL.md", "CHANGELOG.md"):
        text = open(path, encoding="utf-8").read()
        for ru_marker in ("напоминание", "напоминания", "счет-фактура",
                          "настройка", "установка", "активация:"):
            assert ru_marker not in text.lower(), (path, ru_marker)


def test_changelog_has_1_0_0_with_all_features():
    ch = open("CHANGELOG.md", encoding="utf-8").read()
    assert "## [1.0.0] — 2026-11-05" in ch
    for feature in ("SMTP setup wizard", "шаблони PDF", "базовій валюті",
                    "payment terms", "i18n UI UA/EN", "демо", "Експорт даних"):
        assert feature in ch


def test_readme_mentions_install_and_contributing():
    ua = open("README.md", encoding="utf-8").read()
    assert "INSTALL.md" in ua
    # Contributing section is added by the OSS commit; README.en already points to it
    en = open("README.en.md", encoding="utf-8").read()
    assert "CONTRIBUTING.md" in en and "SECURITY.md" in en


def test_stats_page_ukrainian_untouched():
    import re as _re
    src = open("app/main.py", encoding="utf-8").read()
    assert 'lang="uk"' in src  # effectiveness page stays Ukrainian
