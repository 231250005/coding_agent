"""SQLAlchemy 声明式基类：所有数据表 Model 继承此基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
