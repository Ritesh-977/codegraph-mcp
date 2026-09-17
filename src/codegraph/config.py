"""Application settings via pydantic-settings (env + defaults)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from env / .env.

    All Neo4j connection details, the repos working directory, and ingestion
    tuning knobs live here. Defaults match the bundled ``.env.example``.
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme123"
    neo4j_db: str = "neo4j"
    repos_dir: Path = Path("./repos")
    ingest_batch_size: int = 200
    # Git clone depth. 0 = full history, which is what makes per-file
    # last_author/last_commit_at meaningful — a depth-1 clone has a single
    # commit, so every file reports the same author and date.
    ingest_depth: int = 0
    # Per-category cap on find_file_dependencies results (imported_by, imports,
    # callers, calls). Raise for big repos where 500 truncates a real answer;
    # lower it to keep tool output small in the LLM's context.
    max_dependency_results: int = 500
    # Optional token for private repos in headless/CI use. SSH keys and OS
    # credential helpers need no token at all — git inherits this environment.
    # SecretStr so an accidental log/print of Settings shows ********** instead.
    git_token: SecretStr | None = None
    # Restrict the token to one host. Without this a token is sent to whatever
    # https host is cloned — a real risk when a company runs GitHub alongside
    # an internal GitLab.
    git_token_host: str = ""
    # Userinfo username paired with the token. Hosts differ: GitHub takes a bare
    # token, Bitbucket needs "x-token-auth" (or your username with an app
    # password), GitLab "oauth2". Sensible defaults are applied per host; set
    # this for a self-hosted instance or a Bitbucket app password.
    git_token_username: str = ""
    log_level: str = "INFO"
    # Local web UI (`codegraph viz`). Host/port bound by uvicorn. Defaults to
    # loopback: this serves a whole repo's source, so it is not for 0.0.0.0
    # unless you mean it.
    viz_host: str = "127.0.0.1"
    viz_port: int = 8787
