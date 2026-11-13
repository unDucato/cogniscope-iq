"""Точка входа веб-приложения MVP IQ-теста."""
import asyncio
import mimetypes
from collections.abc import Awaitable, Callable

from aiohttp import web
from loguru import logger

from app.config import APP_ENV, APP_HOST, APP_PORT, BASE_DIR, IP_HASH_SALT
from app.db import close_db, init_db
from app.locales import get_request_lang, t
from app.log import setup_logging
from app.questions import validate_bank
from app.routes import routes

STATIC_DIR = BASE_DIR / "static"
INDEX_HTML_KEY = web.AppKey("index_html", str)
mimetypes.add_type("image/svg+xml", ".svg")


def _calc_asset_version() -> str:
    """Вычисляет версию статики по времени изменения CSS/JS/SVG для сброса кэша."""
    mtimes = [
        int(p.stat().st_mtime)
        for name in ("style.css", "app.js", "icons.svg", "i18n.js")
        if (p := STATIC_DIR / name).exists()
    ]
    return str(max(mtimes)) if mtimes else "1"


def _render_index_html() -> str:
    raw = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return raw.replace("{{VERSION}}", _calc_asset_version())


@web.middleware
async def error_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Логирует необработанные ошибки на сервере и не отдаёт стек клиенту."""
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Ошибка запроса {} {}", request.method, request.path)
        lang = get_request_lang(request)
        return web.json_response({"error": t(lang, "internal_server_error")}, status=500)


async def index_handler(request: web.Request) -> web.Response:
    """Отдаёт SPA-оболочку index.html без агрессивного кэширования."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return web.Response(text="Frontend ещё не добавлен (static/index.html)", status=404)
    html_text = (
        await asyncio.to_thread(_render_index_html)
        if APP_ENV == "dev"
        else (request.app.get(INDEX_HTML_KEY) or await asyncio.to_thread(_render_index_html))
    )
    return web.Response(
        text=html_text,
        content_type="text/html",
        charset="utf-8",
        headers={"Cache-Control": "no-cache"},
    )


async def on_startup(app: web.Application) -> None:
    """Проверяет банк, инициализирует БД и предзагружает HTML в память."""
    problems = validate_bank()
    if problems:
        raise RuntimeError(f"Ошибки в банке вопросов: {problems}")
    if APP_ENV == "prod" and not IP_HASH_SALT:
        logger.warning("⚠️ IP_HASH_SALT не задан в tokens.env")
    if (STATIC_DIR / "index.html").exists():
        app[INDEX_HTML_KEY] = await asyncio.to_thread(_render_index_html)
    await init_db()


async def on_cleanup(app: web.Application) -> None:
    """Закрывает соединение с SQLite при остановке сервера."""
    await close_db()


def create_app() -> web.Application:
    """Конфигурирует aiohttp-приложение, маршруты и статику."""
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app = web.Application(middlewares=[error_middleware])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.add_routes(routes)
    app.router.add_get("/", index_handler)
    app.router.add_static("/static", STATIC_DIR, show_index=False)
    return app


if __name__ == "__main__":
    setup_logging()
    logger.info("🚀 Запуск IQ-сервиса на http://{}:{} (env={})", APP_HOST, APP_PORT, APP_ENV)
    web.run_app(create_app(), host=APP_HOST, port=APP_PORT, access_log=None)