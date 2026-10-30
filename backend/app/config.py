"""Runtime configuration. Everything comes from environment variables; nothing secret is hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader so `python scripts/...` and uvicorn pick up the same settings. Real env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


_load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    return default if not v else v.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("FINN_DATA_DIR", str(ROOT / "var"))))
    portfolio_file: Path = field(default_factory=lambda: Path(_env("FINN_PORTFOLIO_FILE", str(ROOT / "backend" / "data" / "portfolio.json"))))
    # Offline development mode: serves recorded fixtures instead of calling NSE/BSE/Yahoo/Screener.
    # Every response is tagged so the UI shows a permanent banner. Never enable in production.
    fixture_mode: bool = field(default_factory=lambda: _env_bool("FINN_FIXTURE_MODE"))

    # LLM routing. provider: gemini | openai | anthropic | none
    llm_provider: str = field(default_factory=lambda: _env("FINN_LLM_PROVIDER", "none").lower())
    llm_fast_model: str = field(default_factory=lambda: _env("FINN_LLM_FAST_MODEL"))
    llm_smart_model: str = field(default_factory=lambda: _env("FINN_LLM_SMART_MODEL"))
    llm_base_url: str = field(default_factory=lambda: _env("FINN_LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("FINN_LLM_API_KEY"))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("FINN_LLM_TIMEOUT_S", "60")))
    llm_max_calls_per_research: int = field(default_factory=lambda: int(_env("FINN_LLM_MAX_CALLS_PER_RESEARCH", "8")))

    http_timeout_s: float = field(default_factory=lambda: float(_env("FINN_HTTP_TIMEOUT_S", "20")))
    max_pdf_mb: int = field(default_factory=lambda: int(_env("FINN_MAX_PDF_MB", "40")))
    cors_origins: str = field(default_factory=lambda: _env("FINN_CORS_ORIGINS", "*"))

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider in {"gemini", "openai", "anthropic"} and bool(self.llm_api_key)


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
