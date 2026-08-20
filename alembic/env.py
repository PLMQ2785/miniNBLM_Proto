from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# 이 표현식 인덱스는 migration의 원시 SQL로만 관리한다.
MANUALLY_MANAGED_INDEXES = {"chunks_content_fts_gin"}


def include_object(obj, name, type_, reflected, compare_to):
    """자동 생성 비교에서 수동 관리 인덱스를 제외한다."""
    if type_ == "index" and name in MANUALLY_MANAGED_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    """DB 연결 없이 SQL 스크립트 형태로 migration을 실행한다."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """실제 DB 연결과 트랜잭션 안에서 migration을 실행한다."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
