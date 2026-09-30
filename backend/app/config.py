from functools import lru_cache
import secrets
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Production Process Sales & Action Management System"
    environment: str = "development"
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_expire_minutes: int = 720
    database_url: str = "sqlite:///./pms.db"
    cors_origins: str = "http://localhost:5173,http://localhost:8000"
    admin_username: str = "admin"
    admin_password: str = "ChangeMe123!"
    admin_full_name: str = "System Administrator"
    plant_name: str = "Main Plant"
    upload_dir: str = "./uploads"
    attachments_dir: str = "./attachments"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def secure_configuration(self):
        value = self.secret_key
        if len(value) < 32 or any(x in value.lower() for x in ("change", "dev-secret", "placeholder")) or len(set(value)) < 12:
            raise ValueError("SECRET_KEY must be a random secret of at least 32 characters")
        if self.environment.lower() == "production" and "secret_key" not in self.model_fields_set:
            raise ValueError("Production requires a persistent SECRET_KEY supplied through the environment")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
