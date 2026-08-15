"""Configuración centralizada del gateway."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # App
    app_name: str = "GIA Prospectos"
    app_env: str = "production"
    app_debug: bool = False
    log_level: str = "INFO"
    # Zona horaria para fechas del dashboard (IANA). Los datos siguen en UTC.
    display_timezone: str = "America/Mexico_City"

    # Token para POST /leads (cabecera X-Lead-Token o query ?token=)
    lead_webhook_token: str = ""

    # Odoo (fase posterior; desactivado por defecto)
    odoo_enabled: bool = False
    odoo_url: str = ""
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_api_key: str = ""
    odoo_default_sales_team_id: int = 1
    odoo_default_salesperson_id: int = 2

    # DB
    database_url: str

    # Scoring (señal secundaria; no crea leads mientras Odoo esté off)
    lead_creation_threshold: int = 6
    human_handoff_threshold: int = 9

    # Admin
    admin_api_token: str
    admin_allowed_ips: str = ""

    # Chatwoot Agent Bot
    chatwoot_enabled: bool = False
    chatwoot_base_url: str = ""
    chatwoot_account_id: int = 0
    chatwoot_bot_token: str = ""
    chatwoot_webhook_secret: str = ""
    # Junta mensajes rápidos del mismo hilo antes de llamar al LLM (1 worker).
    chatwoot_debounce_seconds: float = 4.0
    # Fallos seguidos del agente antes de abrir el ticket (0 = nunca por error).
    agent_error_handoff_threshold: int = 3
    # Si el handoff sigue sin asignar, el bot retoma el hilo (0 = no auto-retomar).
    chatwoot_handoff_resume_minutes: int = 15
    # Tope de burbujas si el LLM las marca con ---.
    chatwoot_reply_max_bubbles: int = 4
    # Piso entre burbujas; el delay real simula escritura.
    chatwoot_reply_bubble_delay_ms: int = 700
    # Tiempo percibido hasta el primer envío (el LLM cuenta). Rango 8–16 s.
    chatwoot_reply_min_seconds: float = 8.0
    chatwoot_reply_think_seconds: float = 1.2
    chatwoot_reply_chars_per_sec: float = 16.0
    chatwoot_reply_max_delay_seconds: float = 16.0

    # LLM (OpenAI Agents SDK): openai/* → Responses API; anthropic/* → LiteLLM
    # Examples: openai/gpt-5.6-luna | openai/gpt-4.1-mini | anthropic/claude-sonnet-4-20250514
    agent_model: str = "openai/gpt-5.6-luna"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    agent_max_history_messages: int = 20
    agent_faq_char_limit: int = 12000
    openai_embedding_model: str = "text-embedding-3-small"
    knowledge_retrieve_k: int = 8
    knowledge_uploads_dir: str = "knowledge_uploads"

    @property
    def admin_ips_list(self) -> List[str]:
        return [ip.strip() for ip in self.admin_allowed_ips.split(",") if ip.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
