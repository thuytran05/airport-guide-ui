import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = Field(default="development", description="development | production")
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # Security
    SECRET_KEY: str = Field(
        default="dev-insecure-secret-key-must-change-in-production-1234567890",
        description="Key used for JWT token signing"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # Robot Adapter Mode
    ROBOT_ADAPTER_MODE: str = Field(default="mock", description="mock | ros")

    # ROS 2 Settings (used when ROBOT_ADAPTER_MODE=ros)
    ROS_DOMAIN_ID: int = 0
    ROS_NODE_NAME: str = "airport_guide_backend"
    ROS_MAP_FRAME: str = "map"
    ROS_BASE_FRAME: str = "base_link"
    ROS_ODOM_FRAME: str = "odom"

    # CORS
    CORS_ORIGINS: str = "*"

    @property
    def cors_origins_list(self) -> List[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()
