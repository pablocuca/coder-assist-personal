"""Carregamento e validação da configuração (seção 6 + seção 23).

Defaults do projeto: config/settings.yaml (versionado no repo).
Overrides locais:   ~/.coder-assist-personal/config/settings.yaml (não versionado).
Validação por pydantic na inicialização — erro claro se inválido.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from core.errors import ConfigError

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = Path.home() / ".coder-assist-personal"
PROMPTS_DIR = PACKAGE_ROOT / "prompts"


class OllamaSettings(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "gpt-oss:20b"
    timeout_seconds: int = 120
    max_retries: int = 2
    context_window_tokens: int = 8192  # janela útil do modelo local (política de escalada)


class ClaudePricing(BaseModel):
    """Tabela de preços usada APENAS para a estimativa exibida antes de escalar.

    O custo real vem do campo total_cost_usd do output JSON do Claude Code.
    """

    input_usd_per_mtok: float = 3.00
    output_usd_per_mtok: float = 15.00
    # Overhead do próprio Claude Code: ~23k tokens de sistema em toda chamada,
    # gravados em cache (1h) a 2x o preço de input na primeira chamada.
    overhead_tokens: int = 23_000


class ClaudeSettings(BaseModel):
    binary: str = "claude"
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = 300
    max_turns: int = 1
    max_budget_usd: float = 0.50
    pricing: ClaudePricing = Field(default_factory=ClaudePricing)


class ProvidersSettings(BaseModel):
    default: str = "ollama"
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)


class RouterSettings(BaseModel):
    confidence_threshold: float = 0.60
    auto_escalate: bool = False
    confirm_cost_before_claude: bool = True


class EmbeddingsSettings(BaseModel):
    model: str = "nomic-embed-text"
    chunk_max_lines: int = 80
    chunk_overlap_lines: int = 10


class EditingSettings(BaseModel):
    require_approval: bool = True
    backup_retention: int = 20
    max_file_size_kb: int = 512

    @field_validator("require_approval")
    @classmethod
    def _approval_mandatory(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "editing.require_approval não pode ser desativado (MVP/V1 — princípio 1)"
            )
        return v


class IndexingSettings(BaseModel):
    include: list[str] = Field(
        default_factory=lambda: ["*.dart", "*.py", "*.ts", "*.js", "*.md", "*.yaml", "*.json"]
    )
    respect_gitignore: bool = True
    extra_ignores: list[str] = Field(
        default_factory=lambda: [
            ".git/", "build/", "node_modules/", ".dart_tool/", "venv/", ".venv/",
            "dist/", "target/", "db/", "backups/", "indexes/", "logs/",
        ]
    )
    max_indexed_file_kb: int = 256


class LoggingSettings(BaseModel):
    level: str = "INFO"
    format: str = "json"
    redact_secrets: bool = True


class GitSettings(BaseModel):
    auto_commit: bool = False


class Settings(BaseModel):
    providers: ProvidersSettings = Field(default_factory=ProvidersSettings)
    router: RouterSettings = Field(default_factory=RouterSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    editing: EditingSettings = Field(default_factory=EditingSettings)
    indexing: IndexingSettings = Field(default_factory=IndexingSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    git: GitSettings = Field(default_factory=GitSettings)
    state_dir: Path = DEFAULT_STATE_DIR


def user_config_path(state_dir: Path | None = None) -> Path:
    return (state_dir or DEFAULT_STATE_DIR) / "config" / "settings.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(state_dir: Path | None = None) -> Settings:
    defaults_file = PACKAGE_ROOT / "config" / "settings.yaml"
    data: dict = {}
    if defaults_file.exists():
        try:
            data = yaml.safe_load(defaults_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"config/settings.yaml não é YAML válido: {e}") from e

    sd = state_dir or Path(data.get("state_dir", DEFAULT_STATE_DIR)).expanduser()
    override_file = user_config_path(sd)
    if override_file.exists():
        try:
            override = yaml.safe_load(override_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"{override_file} não é YAML válido: {e}") from e
        data = _deep_merge(data, override)

    data["state_dir"] = str(sd)
    try:
        return Settings.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"Configuração inválida em settings.yaml:\n{e}") from e


def load_prompt(name: str) -> str:
    """Carrega um template de system prompt versionado de prompts/."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise ConfigError(f"Template de prompt não encontrado: {path}")
    return path.read_text(encoding="utf-8")
