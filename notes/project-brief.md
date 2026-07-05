# Continuum — project brief (rough, v0)

Goal: a research agent I can interrupt (laptop closes, Lambda times out, whatever)
and it picks back up without redoing finished work or double-sending anything.

Loosely modeled on a pattern I kept running into on client work: agents that
lose track of "what already happened" across a restart. Instead of building
that for a client's proprietary pipeline again, building a clean standalone
version here as a learning project + portfolio piece.

Scope for v1:
- single-user "research assistant" that takes a topic, runs a multi-phase
  deep-research pipeline (plan -> gather -> read -> synthesize -> draft ->
  cite-check -> publish), and emails the final report.
- semantic recall over past reports/notes (so "what did we find about X last
  month" works without an exact doc ID)
- safe to interrupt at any phase boundary
- never double-sends the final email if the process dies right after sending

Non-goals for v1: multi-user auth, multi-tenant isolation, real web search
(mock it behind a tool interface so this doesn't depend on a paid search API
to run/demo).

Local-first: whole thing should run on a laptop with just an Anthropic API
key before touching AWS at all. AWS is the "how you'd actually run this for
real" layer, not a requirement to try it.
