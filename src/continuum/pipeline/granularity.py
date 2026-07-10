"""EXPERIMENTAL: per-tool-call checkpointing toggle.

Idea: checkpoint after every tool call within a phase, not just at phase
boundaries, on the theory that more frequent saves are strictly safer.
"""
CHECKPOINT_EVERY_TOOL_CALL = True
