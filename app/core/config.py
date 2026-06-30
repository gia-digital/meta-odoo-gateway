"""Configuración centralizada del gateway."""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # App
    app_name: str = "Meta-Odoo Lead Gateway"
    app_env: str = "production"
    app_debug: bool = False
    log_level: str = "INFO"

    # Meta
    meta_verify_token: str
    meta_app_secret: str
    meta_access_token: str
    whatsapp_phone_number_id: str
    messenger_page_id: str
    meta_graph_version: str = "v21.0"

    # Odoo
    odoo_url: str
    odoo_db: str
    odoo_username: str
    odoo_api_key: str
    odoo_default_sales_team_id: int = 1
    odoo_default_salesperson_id: int = 2

    # DB
    database_url: str

    # Scoring
    lead_creation_threshold: int = 6
    human_handoff_threshold: int = 9

    # Admin
    admin_api_token: str
    admin_allowed_ips: str = ""

    @property
    def admin_ips_list(self) -> List[str]:
        return [ip.strip() for ip in self.admin_allowed_ips.split(",") if ip.strip()]

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.meta_graph_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
