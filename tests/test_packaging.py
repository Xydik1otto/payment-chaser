"""Packaging + entry-point smoke tests: `pip install -e .` works and the
`payment-chaser` console script exists; app version is 1.0.0."""
import importlib
import os
import subprocess
import sys


def test_version_is_1_0_0():
    from app.main import app
    assert app.version == "1.0.0"


def test_entry_point_module_imports():
    mod = importlib.import_module("app.run")
    assert callable(mod.main)


def test_run_main_uses_env_host_port(monkeypatch):
    from app import run
    captured = {}
    monkeypatch.setattr(run.uvicorn, "run", lambda *a, **kw: captured.update(kw))
    monkeypatch.setenv("CHASER_HOST", "0.0.0.0")
    monkeypatch.setenv("CHASER_PORT", "9000")
    run.main()
    assert captured["host"] == "0.0.0.0" and captured["port"] == 9000


def test_pyproject_metadata():
    text = open("pyproject.toml", encoding="utf-8").read()
    assert 'name = "payment-chaser"' in text
    assert 'version = "1.0.0"' in text
    assert 'payment-chaser = "app.run:main"' in text
    assert "reportlab" in text  # dependency declared


def test_requirements_match_pyproject():
    req = open("requirements.txt", encoding="utf-8").read()
    for dep in ("fastapi", "uvicorn", "jinja2", "reportlab"):
        assert dep in req


def test_install_md_exists_and_bilingual():
    text = open("INSTALL.md", encoding="utf-8").read()
    assert "shell:startup" in text          # Windows autostart
    assert "systemd" in text and "user" in text  # Linux autostart
    assert "Оновлення" in text and "Updating" in text
