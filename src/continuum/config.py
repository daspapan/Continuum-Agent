"""Runtime config, read from environment (.env in local dev - see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    env: str = os.environ.get("CONTINUUM_ENV", "local")
    aws_region: str = os.environ.get("AWS_REGION", "ap-south-1")
    checkpoint_table_name: str = os.environ.get("CHECKPOINT_TABLE_NAME", "")
    opensearch_endpoint: str = os.environ.get("OPENSEARCH_COLLECTION_ENDPOINT", "")
    reports_bucket_name: str = os.environ.get("REPORTS_BUCKET_NAME", "")
    ses_sender: str = os.environ.get("SES_SENDER_ADDRESS", "")
    ses_recipient: str = os.environ.get("SES_RECIPIENT_ADDRESS", "")


def get_settings() -> Settings:
    return Settings()
