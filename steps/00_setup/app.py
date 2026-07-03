"""Step 00: configurazione validata, nessuna chiamata al modello."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"


if __name__ == "__main__":
    settings = Settings()  # type: ignore[call-arg]
    print(f"Configurazione valida. Modello: {settings.openai_model}")

