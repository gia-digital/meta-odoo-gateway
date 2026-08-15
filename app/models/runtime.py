"""Ajustes de modelo y llaves editables desde el dashboard (una fila)."""
from datetime import datetime

from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
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
    debounce_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_max_bubbles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reply_bubble_delay_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reply_min_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_think_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_chars_per_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reply_max_delay_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
