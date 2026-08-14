"""Ajustes de modelo y llaves editables desde el dashboard (una fila)."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import Base


class RuntimeSettings(Base):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_model: Mapped[str] = mapped_column(String(255), default="")
    llm_provider: Mapped[str] = mapped_column(String(32), default="")
    openai_api_key: Mapped[str] = mapped_column(Text, default="")
    anthropic_api_key: Mapped[str] = mapped_column(Text, default="")
    openai_embedding_model: Mapped[str] = mapped_column(String(255), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
