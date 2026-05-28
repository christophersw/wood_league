"""
Title: app/config.py — Application configuration and environment settings
Description:
    Application-level configuration management using Pydantic Settings. Defines the Settings
    class that loads configuration from environment variables and .env files, including
    database URLs, API keys, chess engine paths, analysis parameters, and feature flags.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-14: Added RUNPOD_API_KEY / RUNPOD_WORKER_POD_ID / RUNPOD_ENABLED
        fields for the admin start-pod endpoint (issue #83).
    2026-05-18: Added VAST_* settings (issue #155 Sub-project A).
    2026-05-20: Added VAST_VERIFIED_ONLY — restrict offer search to
        vast.ai verified hosts (datacenter tier).
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
    runpod_api_key: str = ""
    runpod_worker_pod_id: str = ""
    runpod_enabled: bool = False
    vast_enabled: bool = False
    vast_api_key: str = ""
    vast_template_hash: str = ""
    vast_campaign_id: str = ""
    vast_offer_gpu_name: str = "L40S"
    vast_offer_max_dph: float = 1.50
    vast_verified_only: bool = False
    vast_max_jobs: int = 100
    vast_hard_deadline_hours: float = 6.0
    vast_worker_stale_minutes: int = 15
    email_provider: str = "console"
    resend_api_key: str = ""
    email_from: str = "Wood League <noreply@woodleague.club>"
    email_reply_to: str = ""
    app_base_url: str = ""
    magic_link_invite_ttl_hours: int = 168
    magic_link_login_ttl_minutes: int = 15
    magic_link_throttle_per_minute: int = 1
    magic_link_throttle_per_hour: int = 5
    session_ttl_days: int = 14

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def chess_usernames(self) -> list[str]:
        """Parse and normalize comma-separated Chess.com usernames."""
        if not self.chess_com_usernames.strip():
            return []
        return [u.strip().lower() for u in self.chess_com_usernames.split(",") if u.strip()]


def get_settings() -> Settings:
    """Factory function to create and return a Settings instance."""
    return Settings()
