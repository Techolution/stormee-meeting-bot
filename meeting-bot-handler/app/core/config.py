"""Application settings.

Environment is the only configuration source: the handler runs as a Deployment
on GKE, where settings arrive through a ConfigMap and secrets through a Secret.

The bot pods are addressed *individually*. A meeting lives on one specific pod —
only that pod can stop its recording or report its status — so the handler
discovers pods through the Kubernetes API and then talks to a pod IP directly
for the lifetime of the session. ``bot_service_url`` short-circuits that for
local development, where there is no cluster.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "meeting-bot-handler"
    environment: str = "development"

    host: str = "0.0.0.0"
    port: int = 8000

    log_level: str = "INFO"
    log_format: str = "text"

    redis_url: str = "redis://localhost:6379/0"

    # --- Bot pod discovery ----------------------------------------------------
    # Namespace the bot pods run in. KUBERNETES_NAMESPACE is accepted as the
    # older name for the same setting.
    bot_namespace: str = Field(
        default="default",
        validation_alias=AliasChoices("BOT_NAMESPACE", "KUBERNETES_NAMESPACE"),
    )
    # Must match the labels on the bot Deployment's pod template.
    bot_label_selector: str = "app.kubernetes.io/name=meeting-bot"
    bot_pod_port: int = 5000
    bot_api_prefix: str = "/api/meet"

    kubernetes_enabled: bool = True
    # Path to a kubeconfig for out-of-cluster runs. Unset means: in-cluster
    # service account first, then the ambient kubeconfig.
    kubeconfig: str | None = None

    # Non-cluster fallback. When set, every session is dispatched here instead
    # of to a discovered pod.
    bot_service_url: str | None = None

    # --- Timeouts -------------------------------------------------------------
    bot_request_timeout_seconds: float = 30.0
    # Readiness probes fan out across every pod, so keep this short.
    bot_probe_timeout_seconds: float = 3.0
    # Admission depends on a human host: the join watcher polls this long.
    join_poll_interval_seconds: float = 5.0
    join_poll_timeout_seconds: float = 600.0

    bot_image: str = "meeting-bot:latest"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def kubernetes_namespace(self) -> str:
        """Deprecated alias for :attr:`bot_namespace`."""
        return self.bot_namespace


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
