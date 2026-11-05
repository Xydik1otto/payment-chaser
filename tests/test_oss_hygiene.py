"""OSS hygiene: community files, no leaked secrets/paths, gitignore coverage."""
import os
import re

import pytest


def test_community_files_exist():
    for path in ("CONTRIBUTING.md", "SECURITY.md",
                 ".github/ISSUE_TEMPLATE/bug_report.md",
                 ".github/ISSUE_TEMPLATE/feature_request.md"):
        assert os.path.exists(path), path


def test_contributing_and_security_bilingual_no_russian():
    for path in ("CONTRIBUTING.md", "SECURITY.md",
                 ".github/ISSUE_TEMPLATE/bug_report.md",
                 ".github/ISSUE_TEMPLATE/feature_request.md"):
        text = open(path, encoding="utf-8").read()
        # bilingual: Cyrillic (Ukrainian) + Latin present in every file
        assert re.search(r"[а-яіїєґ]", text.lower()), path
        assert re.search(r"[a-z]{4,}", text.lower()), path
        for ru_marker in ("напоминание", "установка", "пожалуйста", "спасибо",
                          "отчет", "настройка"):
            assert ru_marker not in text.lower(), (path, ru_marker)
    # the explicit no-Russian rule lives in CONTRIBUTING + both issue templates
    for path in ("CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/bug_report.md",
                 ".github/ISSUE_TEMPLATE/feature_request.md"):
        text = open(path, encoding="utf-8").read().lower()
        assert "російськ" in text or "no other languages" in text, path


def test_security_md_covers_smtp_credentials():
    text = open("SECURITY.md", encoding="utf-8").read()
    assert "ніколи не зберігаються в коді" in text.lower() or "never" in text.lower()
    assert "write-only" in text
    assert ".env" in text and "EnvironmentFile" in text
    assert "App Password" in text


def test_no_leaked_secrets_or_local_paths():
    """Scan every tracked file for local paths, emails-as-credentials,
    hardcoded passwords/tokens. GitHub repo URLs (bigpi/payment-chaser) are
    the intended public identity and allowed."""
    from subprocess import run
    files = run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    bad_patterns = [
        (re.compile(r"G:[/\\]", re.I), "local drive path"),
        (re.compile(r"[A-Z]:\\\\Users\\\\", re.I), "windows user path"),
        (re.compile(r"/home/\w+/"), "home path"),
        (re.compile(r"smtp_pass\s*[=:]\s*['\"][^'\"\s]{4,}['\"]", re.I), "hardcoded smtp pass"),
        (re.compile(r"sk-[A-Za-z0-9]{16,}"), "openai-style key"),
        (re.compile(r"ghp_[A-Za-z0-9]{10,}"), "github token"),
        (re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"), "private key"),
    ]
    for f in files:
        if f.startswith(".git"):
            continue
        data = open(f, encoding="utf-8", errors="ignore").read()
        for rx, what in bad_patterns:
            m = rx.search(data)
            if m:
                # placeholder example values are allowed
                ctx = data[max(0, m.start() - 40):m.end() + 40].lower()
                assert "пароль додатку" in ctx or "app password" in ctx \
                    or "you@gmail.com" in ctx, (f, what, m.group(0))


def test_gitignore_covers_env_and_db():
    gi = open(".gitignore", encoding="utf-8").read()
    assert ".env" in gi and "*.db" in gi and ".venv" in gi
    assert "*.egg-info" in gi


def test_no_db_or_env_tracked():
    from subprocess import run
    files = run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    assert not [f for f in files if f.endswith(".db") or f == ".env"]


def test_readme_has_contributing_and_topics():
    for path in ("README.md", "README.en.md"):
        text = open(path, encoding="utf-8").read()
        assert "CONTRIBUTING.md" in text and "SECURITY.md" in text
    topics = ("invoicing", "freelancing", "payments", "fastapi", "reminders")
    en = open("README.en.md", encoding="utf-8").read()
    assert all(t in en for t in topics)
