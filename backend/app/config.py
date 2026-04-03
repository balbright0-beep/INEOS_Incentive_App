from pydantic_settings import BaseSettings
from pathlib import Path
import os


class Settings(BaseSettings):
    APP_NAME: str = "INEOS Incentive Management System"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{Path(__file__).resolve().parent.parent / 'ims.db'}"
    )
    JWT_SECRET: str = os.getenv("JWT_SECRET", "ineos-ims-dev-secret-change-in-prod")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 8
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
    ADMIN_DEFAULT_PASSWORD: str = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
    OUTPUT_DIR: str = os.getenv(
        "OUTPUT_DIR",
        str(Path(__file__).resolve().parent.parent.parent.parent / "INEOS_Incentive_Dashboard_Output")
    )
    UPLOAD_MAX_SIZE: int = 10 * 1024 * 1024  # 10MB

    class Config:
        env_file = ".env"


settings = Settings()
