"""
Application configuration. Reads from environment variables (populated via .env).
"""
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    SECRET_KEY: str = field(
        default_factory=lambda: os.environ.get("SECRET_KEY", "dev-secret-change-me")
    )
    DATABASE_PATH: str = field(
        default_factory=lambda: os.environ.get("DATABASE_PATH", "tasklings.db")
    )
    SESSION_LIFETIME_HOURS: int = field(
        default_factory=lambda: int(os.environ.get("SESSION_LIFETIME_HOURS", "72"))
    )
    HOUSEHOLD_TIMEZONE: str = field(
        default_factory=lambda: os.environ.get("HOUSEHOLD_TIMEZONE", "America/Chicago")
    )
    BCRYPT_ROUNDS: int = field(
        default_factory=lambda: int(os.environ.get("BCRYPT_ROUNDS", "12"))
    )
    TESTING: bool = field(
        default_factory=lambda: os.environ.get("TESTING", "").lower() in ("1", "true")
    )
    # Optional email settings for password reset delivery
    SMTP_HOST: str = field(
        default_factory=lambda: os.environ.get("SMTP_HOST", "")
    )
    SMTP_PORT: int = field(
        default_factory=lambda: int(os.environ.get("SMTP_PORT", "587"))
    )
    SMTP_USERNAME: str = field(
        default_factory=lambda: os.environ.get("SMTP_USERNAME", "")
    )
    SMTP_PASSWORD: str = field(
        default_factory=lambda: os.environ.get("SMTP_PASSWORD", "")
    )
    SMTP_FROM: str = field(
        default_factory=lambda: os.environ.get("SMTP_FROM", "")
    )

    @classmethod
    def from_env(cls) -> "Config":
        """Load config from environment, reading .env file if present."""
        from dotenv import load_dotenv
        load_dotenv()
        return cls()
