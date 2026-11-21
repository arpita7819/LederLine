from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./ledgerline.db"
    demo_mode: str = "auto"  # auto | on | off
    github_token: str = ""
    github_repo: str = ""
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ledgerline@localhost"
    scheduler_enabled: bool = True
    max_upload_bytes: int = 2_000_000

    @property
    def use_mock_llm(self) -> bool:
        if self.demo_mode == "on":
            return True
        if self.demo_mode == "off":
            return False
        return not self.anthropic_api_key


settings = Settings()
