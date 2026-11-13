"""Фикстуры pytest: изолированная временная SQLite-БД для каждого теста."""
import asyncio
from pathlib import Path

import pytest

from app import config as config_module
from app import db as db_module
from main import create_app


@pytest.fixture
async def client(aiohttp_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Создаёт тестовый клиент aiohttp со своей временной БД в tmp_path."""
    test_db = tmp_path / "test_iq.db"
    monkeypatch.setattr(config_module, "DB_PATH", test_db)
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    monkeypatch.setattr(db_module, "_db", None)
    monkeypatch.setattr(db_module, "_write_lock", asyncio.Lock())
    app = create_app()
    test_client = await aiohttp_client(app)
    try:
        yield test_client
    finally:
        await test_client.close()
        await asyncio.sleep(0)