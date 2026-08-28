"""FastAPI 应用入口。

当前阶段：仅验证数据库层（启动时自动建库/建表/迁移 + 健康检查）。
业务接口（会话/变更/工作区）在后续版本补充。
"""

import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .db import database, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动：建库 → create_all 建表 → 版本化迁移
    init_db()
    yield


app = FastAPI(title="Coding Agent Server", lifespan=lifespan)


@app.get("/health")
def health():
    """健康检查：确认数据库连通、表结构就绪。"""
    try:
        session = database.get_session()
        with session:
            tables = [row[0] for row in session.execute(text("SHOW TABLES")).fetchall()]
            migrations = [
                row[0]
                for row in session.execute(text("SELECT version FROM schema_migrations")).fetchall()
            ]
        return {
            "status": "ok",
            "database": database.db_name,
            "tables": tables,
            "migrations": migrations,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": f"{type(e).__name__}: {e}"},
        )


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动后端服务（python -m server.main 一键运行）。"""
    print(f"🚀 Coding Agent Server: http://{host}:{port} （数据库: {database.db_name}）")
    print("   健康检查: GET /health")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
