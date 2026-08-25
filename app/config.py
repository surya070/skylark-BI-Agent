from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    monday_api_token: str
    monday_deals_board_id: str
    monday_work_orders_board_id: str

    # gemini | openai
    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"

    monday_api_url: str = "https://api.monday.com/v2"
    monday_api_version: str = "2024-10"
    cache_ttl_seconds: int = 120

    # Model / product constraints
    llm_temperature: float = 0.1
    llm_max_output_tokens: int = 1200
    max_history_turns: int = 8
    max_user_message_chars: int = 2000
    max_tool_rounds: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
