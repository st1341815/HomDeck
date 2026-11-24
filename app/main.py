"""HomDeck 应用入口。

设计约束（对应三条硬要求）：
1. 安全可靠 —— 依赖只有 7 个、出站请求只有「管理员手动抓图标」这一处、SQL 全部手写可审计；
2. 功能不受限 —— 无授权、无账号上限、无付费墙；
3. 随时加需求 —— 路由/模板/静态资源三层分明，加一个页面 = 加一个 router + 一个模板。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routers import admin, auth, files, health, panel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("homedeck")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        from .services import uploads

        result = uploads.dedupe_icons()
        if result["merged"] or result["backfilled"]:
            log.info(
                "图标去重：合并 %d 条重复、回填 %d 条 sha",
                result["merged"], result["backfilled"],
            )
    except Exception:  # 去重失败不该挡住启动
        log.exception("图标去重失败，已跳过")
    log.info("HomDeck %s 启动，数据目录 %s", config.VERSION, config.DATA_DIR)
    yield
    db.close()


app = FastAPI(
    title="HomDeck",
    version=config.VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(config.BASE_DIR / "app" / "static")),
    name="static",
)

for r in (health.router, auth.router, panel.router, admin.router, files.router):
    app.include_router(r)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';"
        " script-src 'self'; connect-src 'self'; frame-ancestors 'self'",
    )
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse({"error": "服务器内部错误"}, status_code=500)
