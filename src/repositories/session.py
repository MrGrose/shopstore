from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

async_engine = create_async_engine(
    settings.database_url,
    # echo=True,
    pool_pre_ping=True,
    connect_args={"server_settings": {"timezone": "UTC"}},
)

async_session_maker = async_sessionmaker(
    async_engine, expire_on_commit=False, class_=AsyncSession
)
