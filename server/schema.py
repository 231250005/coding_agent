"""表结构自动同步：启动时比对 Model 定义与实际库表，自动补齐差异。

- 新表：自动创建（按 Model 定义生成 DDL）
- 已有表：对比列与索引，缺失的自动 ALTER TABLE ADD COLUMN / CREATE INDEX
- 只增不减（不删除列/表，避免误删数据；结构性变更如主键建议手动处理）
- 无需版本记录表：每次启动以 Model 定义为唯一事实来源，幂等
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.inspection import inspect
from sqlalchemy.sql.schema import Column

from .base import Base

# 废弃列清理：Model 中已移除的历史字段（启动时自动 DROP COLUMN）
_DROPPED_COLUMNS: dict[str, list[str]] = {
    "sessions": ["strategy", "status"],
}


def _column_ddl(col: Column, engine: Engine) -> str:
    """手动拼列的 ADD COLUMN 片段（类型/非空/默认值）。"""
    dialect = engine.dialect
    parts = [f"`{col.name}`", str(col.type.compile(dialect=dialect))]
    if col.nullable is False:
        parts.append("NOT NULL")
    if col.server_default is not None:
        default = col.server_default.arg
        if isinstance(default, str):
            default = f"'{default}'"
        else:
            default = str(default)  # 函数默认值如 now()
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


def sync_schema(engine: Engine) -> None:
    """启动时自动同步表结构（幂等，可安全重复调用）。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # 清理旧版迁移机制的记录表（schema_migrations 已废弃）
    if "schema_migrations" in existing_tables:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            # 新表：按 Model 定义自动创建
            table.create(engine)
            continue

        # 已有表：比对列
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}

        # 清理废弃列（Model 已移除、明确声明废弃的字段；MySQL 不支持 IF EXISTS，先查存在性）
        for col_name in _DROPPED_COLUMNS.get(table.name, []):
            if col_name in existing_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE `{table.name}` DROP COLUMN `{col_name}`"))
                existing_cols.discard(col_name)

        # 补齐缺失列（Model 定义了但库中没有）
        missing_cols = [c for c in table.columns if c.name not in existing_cols]
        if missing_cols:
            with engine.begin() as conn:
                for col in missing_cols:
                    col_ddl = _column_ddl(col, engine)
                    conn.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN {col_ddl}"))

        # 补齐缺失索引（Model 定义了但库中没有）
        existing_idx = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name and index.name not in existing_idx:
                col_names = ", ".join(f"`{c.name}`" for c in index.columns)
                with engine.begin() as conn:
                    conn.execute(
                        text(f"CREATE INDEX `{index.name}` ON `{table.name}` ({col_names})")
                    )
