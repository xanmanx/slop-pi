"""Configuration for MCP server."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """MCP server configuration."""

    pi_url: str
    api_key: str
    supabase_url: str
    supabase_key: str
    default_user_id: str

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.

        Supports multiple env var names for flexibility:
        - API key: SLOP_API_KEY or PI_API_KEY
        - Supabase key: SUPABASE_KEY or SUPABASE_SERVICE_ROLE_KEY
        """
        return cls(
            pi_url=os.environ.get("SLOP_PI_URL", "https://api.slxp.app"),
            api_key=os.environ.get("SLOP_API_KEY") or os.environ.get("PI_API_KEY", ""),
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            supabase_key=os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            default_user_id=os.environ.get("SLOP_DEFAULT_USER_ID", ""),
        )

    def reload(self):
        """Reload configuration from environment variables."""
        new_config = Config.from_env()
        self.pi_url = new_config.pi_url
        self.api_key = new_config.api_key
        self.supabase_url = new_config.supabase_url
        self.supabase_key = new_config.supabase_key
        self.default_user_id = new_config.default_user_id


config = Config.from_env()
