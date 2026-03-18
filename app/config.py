from pathlib import Path

from pydantic_settings import BaseSettings

# Project root — all default paths resolve relative to this
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    db_path: Path = BASE_DIR / "data" / "sizing.db"
    screenshots_dir: Path = BASE_DIR / "data" / "screenshots"
    max_upload_size_mb: int = 20
    port: int = 8000
    debug: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
