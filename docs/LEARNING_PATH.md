# Learning path

This project is set up so you can learn it in layers, running real code at
each step instead of reading a wall of docs first. Aimed at someone
comfortable with Python who hasn't built a production Claude agent before.

## 0. Before you touch AWS

Everything runs locally with just an Anthropic API key. No AWS account
needed for this whole section.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, leave CONTINUUM_ENV=local
python -m continuum.cli research "impact of grid-scale battery storage on renewable adoption"
```

Watch what happens: a `runs/<run_id>/report.md` shows up, and a
`continuum_checkpoints.sqlite3` file appears in your working directory.
Open it (`sqlite3 continuum_checkpoints.sqlite3 "select run_id, phase, status from checkpoints"`)
and you'll see one row per phase - that's the checkpoint history for the run
you just did.

## 1. Read the pipeline in order, not the file tree in order

Read these four files, in this order, ignoring everything else for now:

1. `src/continuum/pipeline/phases.py` - the seven phases, in order. This is
   the whole shape of the pipeline.
2. `src/continuum/pipeline/orchestrator.py` - `_run_phase` is the dispatcher;
   `run()` is the loop that calls it phase by phase and handles resume.
3. `src/continuum/pipeline/checkpoint_store.py` - what actually gets written
   at each phase boundary, and why it's phase-boundary and not per-step (read
   the module docstring).
4. `src/continuum/pipeline/idempotency.py` - why `publish` gets different
   treatment than every other phase.

That's the core mental model. Everything else (memory, tools, agent) plugs
into that loop.

## 2. Break it on purpose

This is the fastest way to actually understand checkpoint/resume: make it
fail and watch it recover.

```bash
# Start a run, then Ctrl+C it partway through (after GATHER logs, before PUBLISH)
python -m continuum.cli research "some topic"
# ^C

# Find the run_id from the log output, then resume it:
python -m continuum.cli resume <run_id>
```

Notice it doesn't redo PLAN or GATHER - check the checkpoint sqlite file
before and after to see why. Then read
`tests/unit/test_orchestrator_resume.py` - it's testing exactly this
scenario, just without needing you to time a Ctrl+C by hand.

Next, try breaking staleness detection on purpose:
`tests/unit/test_orchestrator_resume.py::test_resume_raises_staleness_error_when_source_changed`
shows you how - tamper with a checkpointed source's content and resume, and
you'll get a `StalenessError` instead of a silent continue.

## 3. Run the test suite and read the docstrings, not just the assertions

```bash
pytest -v
```

Every test file in `tests/` opens with a docstring explaining *what failure
mode* it's guarding against, not just what it asserts. Read those before the
test bodies - `TESTING.md` has the same summary in one place if you want it
without opening each file.

## 4. Swap one local piece for its AWS equivalent, one at a time

Don't jump straight to a full `cdk deploy`. Instead:

- Point `CONTINUUM_ENV=aws` at a real DynamoDB table (`aws dynamodb create-table`
  by hand, or just deploy the CDK stack and use its table) and rerun a
  research call. Confirm checkpoints land in DynamoDB instead of sqlite.
- Then swap the vector store, then the publisher.

This is slower than deploying everything at once, but it's the difference
between "I ran `cdk deploy` and it worked" and understanding which AWS
service is doing what.

## 5. Deploy the real thing

Once the above makes sense, follow `docs/DEPLOYMENT_RUNBOOK.md` for an
actual `cdk deploy` to a dev AWS account, and read `docs/ARCHITECTURE.md`
for why each service was chosen over its alternatives - that doc assumes
you've already read the code, so it focuses on trade-offs, not walkthrough.

## 6. What to build next, if you want to extend this

- Swap `tools/web_search.py`'s mock for a real search API - the interface
  (`search(query, num_results) -> list[dict]`) is the only contract to keep.
- Add a DLQ to the state machine (see ARCHITECTURE.md "Cut corners") -
  good first real production-hardening exercise.
- Add auth to the `/research` endpoint (Cognito or an API key) before using
  this for anything beyond your own testing.
