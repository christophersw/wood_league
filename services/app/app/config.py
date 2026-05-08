"""Application configuration and settings management via Pydantic.

Defines the Settings class that loads configuration from environment variables and .env files.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Wood League Chess"
    database_url: str = ""
    default_history_days: int = 90
    recent_games_limit: int = 20
    opening_analysis_max_rows: int = 999
    chess_com_usernames: str = ""
    chess_com_user_agent: str = "wood-league-chess/0.1 (+club analytics app)"
    ingest_month_limit: int = 24
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-haiku-20240307"
    auth_enabled: bool = False
    auth_bootstrap_admin_email: str = ""
    auth_bootstrap_admin_password: str = ""
    auth_signing_key: str = ""
    auth_token_ttl_seconds: int = 604800
    stockfish_path: str = ""
    analysis_depth: int = 20
    analysis_threads: int = 1
    analysis_hash_mb: int = 256
    lc0_path: str = ""
    lc0_nodes: int = 800
    lc0_network: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def chess_usernames(self) -> list[str]:
        """Parse and normalize comma-separated Chess.com usernames."""
        if not self.chess_com_usernames.strip():
            return []
        return [u.strip().lower() for u in self.chess_com_usernames.split(",") if u.strip()]


def get_settings() -> Settings:
    """Factory function to create and return a Settings instance."""
    return Settings()
