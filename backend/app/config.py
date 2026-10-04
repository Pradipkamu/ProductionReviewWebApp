from functools import lru_cache
import secrets
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Production Process Sales & Action Management System"
    environment: str = "development"
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    access_token_expire_minutes: int = 720
    session_idle_timeout_minutes: int = 60
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    require_https: bool = False
    trust_proxy_headers: bool = False
    database_url: str = "sqlite:///./pms.db"
    cors_origins: str = "http://localhost:5173,http://localhost:8000"
    db_bind: str = "127.0.0.1"
    backend_bind: str = "127.0.0.1"
    frontend_bind: str = "0.0.0.0"
    frontend_port: int = 5173
    admin_username: str = "admin"
    admin_password: str = "ChangeMe123!"
    admin_full_name: str = "System Administrator"
    plant_name: str = "Main Plant"
    upload_dir: str = "./uploads"
    attachments_dir: str = "./attachments"
    backup_dir: str = "./backups"
    import_max_mb: int = 32
    attachment_max_mb: int = 25
    office_max_uncompressed_mb: int = 128
    attachment_allowed_extensions: str = ".pdf,.png,.jpg,.jpeg,.webp,.xlsx,.xlsm,.docx,.pptx,.txt,.csv"
    backup_max_age_hours: int = 48
    restore_verify_max_age_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def secure_configuration(self):
        value = self.secret_key
        if len(value) < 32 or any(x in value.lower() for x in ("change", "dev-secret", "placeholder")) or len(set(value)) < 12:
            raise ValueError("SECRET_KEY must be a random secret of at least 32 characters")
        if self.environment.lower() == "production" and "secret_key" not in self.model_fields_set:
            raise ValueError("Production requires a persistent SECRET_KEY supplied through the environment")
        if self.access_token_expire_minutes < 15 or self.access_token_expire_minutes > 1440:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 15 and 1440")
        if self.session_idle_timeout_minutes < 5 or self.session_idle_timeout_minutes > self.access_token_expire_minutes:
            raise ValueError("SESSION_IDLE_TIMEOUT_MINUTES must be between 5 and ACCESS_TOKEN_EXPIRE_MINUTES")
        if self.login_max_failures < 3 or self.login_max_failures > 20:
            raise ValueError("LOGIN_MAX_FAILURES must be between 3 and 20")
        if self.login_lock_minutes < 1 or self.login_lock_minutes > 1440:
            raise ValueError("LOGIN_LOCK_MINUTES must be between 1 and 1440")
        if self.import_max_mb < 1 or self.import_max_mb > 256:
            raise ValueError("IMPORT_MAX_MB must be between 1 and 256")
        if self.attachment_max_mb < 1 or self.attachment_max_mb > 256:
            raise ValueError("ATTACHMENT_MAX_MB must be between 1 and 256")
        if self.office_max_uncompressed_mb < self.import_max_mb or self.office_max_uncompressed_mb > 1024:
            raise ValueError("OFFICE_MAX_UNCOMPRESSED_MB must be at least IMPORT_MAX_MB and no more than 1024")
        if self.backup_max_age_hours < 1 or self.restore_verify_max_age_days < 1:
            raise ValueError("Backup freshness limits must be positive")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def attachment_extension_set(self) -> set[str]:
        return {
            (x.strip().lower() if x.strip().startswith(".") else "." + x.strip().lower())
            for x in self.attachment_allowed_extensions.split(",")
            if x.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
