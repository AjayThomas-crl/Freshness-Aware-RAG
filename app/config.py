from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    firecrawl_api_key: str = ""
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'rag.db').as_posix()}"
    chroma_dir: str = str(BASE_DIR / "data" / "chroma")
    embedding_model: str = "all-MiniLM-L6-v2"
    default_interval_seconds: int = 21600
    top_k: int = 5
    # Hosts scraped with the plain HTTP scraper (no Firecrawl key needed).
    local_scrape_hosts: str = "localhost,127.0.0.1"


settings = Settings()
