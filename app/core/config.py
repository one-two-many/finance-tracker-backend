from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    FT_DATABASE_URL: str = "sqlite:///./finance.db"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Application
    DEBUG: bool = False
    PROJECT_NAME: str = "Finance Tracker"
    VERSION: str = "1.0.0"

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
