"""Конфигурация приложения. Все значения читаются из tokens.env / окружения."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR: Path = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "tokens.env")

APP_ENV: str = os.getenv("APP_ENV", "dev")
APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT: int = int(os.getenv("APP_PORT", "8080"))
IP_HASH_SALT: str = os.getenv("IP_HASH_SALT", "")
DB_PATH: Path = (BASE_DIR / os.getenv("IQ_DB_PATH", os.path.join("data", "iq.db"))).resolve()