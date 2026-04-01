# ===========================================================
# alembic/env.py — SBT01 Alembic Environment
# -----------------------------------------------------------
# Responsibilities:
#   - Load SQLAlchemy metadata (Base.metadata) for autogenerate
#   - Configure Alembic logging (exactly once)
#   - Run migrations in offline or online mode
# ===========================================================

from __future__ import annotations                       # Typing forward refs

# -----------------------------------------------------------
# Standard library
# -----------------------------------------------------------
import os                                                 # Path utilities
import sys                                                # sys.path editing

# -----------------------------------------------------------
# Alembic / SQLAlchemy
# -----------------------------------------------------------
from logging.config import fileConfig                     # Logging from ini
from sqlalchemy import engine_from_config                 # Build engine from ini
from sqlalchemy import pool                               # Pool control
from alembic import context                               # Alembic context

# -----------------------------------------------------------
# Alembic config
# -----------------------------------------------------------
config = context.config                                   # Alembic config object

# -----------------------------------------------------------
# Logging (configure once)
# -----------------------------------------------------------
if config.config_file_name is not None:                   # Only if ini exists
    fileConfig(config.config_file_name)                   # Configure logging once

# -----------------------------------------------------------
# Import path
# - Ensure repo root is importable when running alembic
# - Keeps "from database import Base" working reliably
# -----------------------------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # Repo root path
if REPO_ROOT not in sys.path:                             # Avoid duplicate path entries
    sys.path.append(REPO_ROOT)                            # Add repo root to sys.path

# -----------------------------------------------------------
# Target metadata
# - Import models before Base.metadata so autogenerate sees tables
# -----------------------------------------------------------
import backend.models  # noqa: F401                        # Register ORM tables on Base metadata
from database import Base                                  # Declarative base (root database.py)

target_metadata = Base.metadata                            # Model metadata for autogenerate


# -----------------------------------------------------------
# run_migrations_offline
# - Generates SQL script output without DB connection
# -----------------------------------------------------------
def run_migrations_offline() -> None:                      # Offline mode
    url = config.get_main_option("sqlalchemy.url")         # URL from alembic.ini

    context.configure(                                     # Configure Alembic context
        url=url,                                           # DB URL
        target_metadata=target_metadata,                   # Model metadata
        literal_binds=True,                                # Inline literal values
        dialect_opts={"paramstyle": "named"},              # Named parameters
    )

    with context.begin_transaction():                      # Begin offline transaction
        context.run_migrations()                           # Run migrations


# -----------------------------------------------------------
# run_migrations_online
# - Applies migrations to the DB using a real connection
# -----------------------------------------------------------
def run_migrations_online() -> None:                       # Online mode
    connectable = engine_from_config(                      # Create engine from ini
        config.get_section(config.config_ini_section),      # ini section dict
        prefix="sqlalchemy.",                              # keys start with sqlalchemy.*
        poolclass=pool.NullPool,                           # No pooling for migrations
    )

    with connectable.connect() as connection:              # Open DB connection
        context.configure(                                 # Configure Alembic context
            connection=connection,                         # Live connection
            target_metadata=target_metadata,               # Model metadata
        )

        with context.begin_transaction():                  # Begin transaction
            context.run_migrations()                       # Run migrations


# -----------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------
if context.is_offline_mode():                              # Offline mode?
    run_migrations_offline()                               # Run offline migrations
else:                                                      # Otherwise online
    run_migrations_online()                                # Run online migrations
