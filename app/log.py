"""Настройка loguru: цветные логи с идентификатором пользователя или SYSTEM."""
import sys

from loguru import logger

LOG_FORMAT: str = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{extra[uid]}</cyan> | <cyan>{file}:{line}</cyan> - <level>{message}</level>"
)


def setup_logging() -> None:
    """Сбрасывает настройки по умолчанию и включает единый формат логов."""
    logger.remove()
    # Для системных событий идентификатор по умолчанию SYSTEM
    logger.configure(extra={"uid": "SYSTEM"})
    logger.add(sys.stderr, format=LOG_FORMAT, colorize=True, level="INFO")