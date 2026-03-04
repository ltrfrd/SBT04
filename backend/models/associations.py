# ===========================================================
# backend/models/associations.py — BST Many-to-Many Tables
# -----------------------------------------------------------
# Defines association tables for relationships between models
# ===========================================================

from sqlalchemy import Table, Column, Integer, ForeignKey
from database import Base  # Root-level Base

# -----------------------------------------------------------
# route_schools: Many-to-Many between Route and School
# -----------------------------------------------------------
route_schools = Table(
    "route_schools",
    Base.metadata,
    Column("route_id", Integer, ForeignKey("routes.id"), primary_key=True),
    Column("school_id", Integer, ForeignKey("schools.id"), primary_key=True),
)
