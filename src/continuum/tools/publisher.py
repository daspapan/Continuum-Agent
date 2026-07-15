"""
The pipeline's one irreversible action: sending the finished report.

Two backends:
  - LocalPublisher: writes the report to ./runs/<run_id>/report.md and prints
    a "sent" confirmation. No external side effect, safe to call repeatedly -
    used for local dev so you're not required to own an SES-verified sender
    identity just to try the pipeline.
  - SESPublisher: production backend, sends via Amazon SES. This one has a
    real external side effect and is exactly why idempotency.py exists -
    orchestrator.py claims the idempotency guard before calling this, so a
    crash between "guard claimed" and "SES call returned" is the only window
    where a human might need to check SES's send log by hand; a straight
    process restart will not re-send.
"""
from __future__ import annotations

import os
from pathlib import Path


class Publisher:
    def publish(self, run_id: str, subject: str, body_markdown: str) -> str:
        """Returns a provider-specific confirmation id/path."""
        raise NotImplementedError


class LocalPublisher(Publisher):
    def __init__(self, output_dir: str = "runs"):
        self.output_dir = output_dir

    def publish(self, run_id: str, subject: str, body_markdown: str) -> str:
        run_dir = Path(self.output_dir) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report_path = run_dir / "report.md"
        report_path.write_text(f"# {subject}\n\n{body_markdown}\n", encoding="utf-8")
        return str(report_path)


class SESPublisher(Publisher):
    def __init__(self, sender: str | None = None, recipient: str | None = None, region: str | None = None):
        self.sender = sender or os.environ["SES_SENDER_ADDRESS"]
        self.recipient = recipient or os.environ["SES_RECIPIENT_ADDRESS"]
        import boto3

        self._client = boto3.client("ses", region_name=region or os.environ.get("AWS_REGION"))

    def publish(self, run_id: str, subject: str, body_markdown: str) -> str:
        resp = self._client.send_email(
            Source=self.sender,
            Destination={"ToAddresses": [self.recipient]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body_markdown}},
            },
        )
        return resp["MessageId"]


def get_publisher(env: str, **kwargs) -> Publisher:
    if env == "aws":
        return SESPublisher(**kwargs)
    return LocalPublisher(**kwargs)
