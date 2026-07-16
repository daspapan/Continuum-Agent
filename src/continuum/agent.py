"""
Claude-backed research agent.

Thin wrapper around the Anthropic Messages API doing the four LLM-backed
steps of the pipeline (plan / synthesize / draft / cite-check). Deliberately
NOT using a heavier agent framework here - each of these is a single-shot
"here's context, give me structured output" call, not a multi-turn tool-use
loop, so a framework would add indirection without buying anything. If a
later phase needs the agent to autonomously call tools mid-reasoning (e.g. a
real web-search tool the model decides when to invoke), that's the point
where reaching for the Claude Agent SDK's tool-use loop actually pays for
itself - v1 doesn't need it because GATHER/READ are deterministic tool calls
the orchestrator makes directly, not agent-directed ones.
"""
from __future__ import annotations

import json
import os

import anthropic

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")


class ClaudeResearchAgent:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = DEFAULT_MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def plan(self, topic: str, prior_context: list[str]) -> dict:
        context_block = "\n".join(f"- {c}" for c in prior_context) or "(no relevant prior research found)"
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"You're planning a research report on: {topic}\n\n"
                        f"Relevant prior research on related topics:\n{context_block}\n\n"
                        "Return a short JSON object with keys `angle` (the specific angle "
                        "this report should take) and `subtopics` (a list of 3-5 subtopics "
                        "to cover). Return ONLY the JSON object, no other text."
                    ),
                }
            ],
        )
        text = _first_text_block(msg)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"angle": topic, "subtopics": []}

    def synthesize(self, topic: str, source_texts: list[str]) -> str:
        sources_block = "\n\n---\n\n".join(source_texts)
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Synthesize the following sources into a structured set of findings "
                        f"about '{topic}'. Note agreements, disagreements, and gaps.\n\n{sources_block}"
                    ),
                }
            ],
        )
        return _first_text_block(msg)

    def draft(self, topic: str, synthesis: str) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1536,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Write a clear, well-organized report on '{topic}' in markdown, "
                        f"based on this synthesis of findings:\n\n{synthesis}"
                    ),
                }
            ],
        )
        return _first_text_block(msg)

    def cite_check(self, draft: str, source_texts: list[str]) -> str:
        sources_block = "\n\n---\n\n".join(source_texts)
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1536,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Review this draft report against the source material below. Flag any "
                        "claim that isn't supported by a source, then return the corrected "
                        "final report in markdown.\n\n"
                        f"DRAFT:\n{draft}\n\nSOURCES:\n{sources_block}"
                    ),
                }
            ],
        )
        return _first_text_block(msg)


def _first_text_block(message: anthropic.types.Message) -> str:
    for block in message.content:
        if block.type == "text":
            return block.text
    return ""
