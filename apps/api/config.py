from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///.data/kontroferta.db")
    file_storage: Path = Path(os.getenv("FILE_STORAGE_PATH", ".data/files")).resolve()
    base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8080").rstrip("/")
    oidc_issuer: str = os.getenv("OIDC_ISSUER", "").rstrip("/")
    oidc_client_id: str = os.getenv("OIDC_CLIENT_ID", "kontroferta-local")
    oidc_client_secret: str = os.getenv("OIDC_CLIENT_SECRET", "")
    session_secret: str = os.getenv("KONTROFERTA_SESSION_SECRET", "")
    session_hours: int = int(os.getenv("SESSION_HOURS", "12"))
    guest_enabled: bool = os.getenv("PUBLIC_DEMO_ENABLED", "false").lower() == "true"
    guest_max_cases: int = int(os.getenv("PUBLIC_DEMO_MAX_CASES", "2"))
    guest_max_sessions: int = int(os.getenv("PUBLIC_DEMO_MAX_SESSIONS", "200"))
    materials_path: Path = Path(os.getenv("MATERIALS_PATH", ".runtime/public-materials")).resolve()
    ai_model: str = os.getenv("AI_MODEL", "gemini-3.8-flash")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
    max_pages: int = int(os.getenv("MAX_DOCUMENT_PAGES", "100"))
    case_budget: float = float(os.getenv("CASE_BUDGET_USD", "1"))
    daily_budget: float = float(os.getenv("DAILY_BUDGET_USD", "20"))
    account_budget: float = float(os.getenv("ACCOUNT_DAILY_BUDGET_USD", "5"))
    input_price: float = float(os.getenv("AI_INPUT_USD_PER_MILLION", "0.75"))
    output_price: float = float(os.getenv("AI_OUTPUT_USD_PER_MILLION", "3.75"))
    max_tokens: int = int(os.getenv("AI_MAX_INPUT_TOKENS_PER_CASE", "100000"))
    max_output_tokens: int = int(os.getenv("AI_MAX_OUTPUT_TOKENS", "16384"))
    retention_days: int = int(os.getenv("CASE_RETENTION_DAYS", "90"))
    demo_retention_hours: int = int(os.getenv("DEMO_RETENTION_HOURS", "24"))
    backup_retention_days: int = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))
    backup_path: Path = Path(os.getenv("BACKUP_PATH", ".data/backups")).resolve()
    maintenance_interval_seconds: int = int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "3600"))
    max_scenarios: int = int(os.getenv("MAX_SCENARIOS", "100000"))

    @property
    def secure(self):
        return self.base_url.startswith("https://")


settings = Settings()
