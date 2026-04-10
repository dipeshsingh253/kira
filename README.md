# Kira

Kira is a parent-facing guidance system that turns student data into short, conversational answers over text and phone.

At a product level, the idea is simple: a parent asks, "How is my child doing?" and Kira replies in plain language using the student's profile, recent conversation context, and a running summary of the thread.

At an implementation level, this repo is a FastAPI application with:

- a text conversation API
- a voice module with Redis-backed live call session state
- a Retell adapter for inbound phone calls and live websocket turn handling
- an OpenAI-backed agent runtime for answer generation and summary refresh
- fixture-backed parent/student data used as the current source of truth

This README is written as an engineer-to-engineer guide. The goal is to help you understand how the system behaves today, where the boundaries are, and how to run or extend it without reading the whole codebase first.

## Overview

High-level, Kira works like this:

1. A parent identifies themselves by phone number.
2. Kira loads the matching parent profile and the students attached to that profile.
3. For each parent turn, Kira tries to resolve which student the message is about.
4. Kira builds a prompt from:
   - the selected student profile
   - the saved conversation summary, if one exists
   - a reduced recent message window
5. The model generates a parent-facing answer.
6. Both the parent message and the Kira response are stored in the conversation transcript.
7. On longer threads, Kira periodically refreshes a saved summary so future turns do not have to rely on the full transcript.

The same core conversation logic is reused for both:

- text requests through the REST API
- live voice turns coming from Retell

## How The Project Works

### Text flow

The text path is the simplest way to understand the system.

1. A client starts a conversation through `POST /api/v1/conversations/start`.
2. Kira looks up the parent by phone number in the profile repository.
3. Kira creates a conversation row and writes an opening greeting as the first agent message.
4. Each parent message goes through `POST /api/v1/conversations/{conversation_id}/messages`.
5. Kira saves the parent message first.
6. The agent resolves the student for that turn.
7. If the student cannot be resolved, Kira returns a clarification message without making a model call.
8. If the student is resolved, Kira builds the answer prompt and calls the model.
9. Kira stores the agent reply, updates per-message metadata, and refreshes the summary when the configured cadence is reached.

The important design choice here is that persistence happens before and after generation:

- user message is saved
- model runs
- agent message is saved

That keeps the transcript authoritative and easy to inspect.

### Student resolution

Student resolution is intentionally conservative. The current order is:

1. direct student name match
2. family relation match like `son` or `daughter`
3. previous resolved student from recent conversation context
4. clarification required

That means a follow-up like `How is he doing in maths?` works only if a previous turn already resolved the student. We are not doing true pronoun understanding. We are reusing the most recent resolved student when the latest message does not identify one clearly enough.

### Prompt building

The answer prompt currently contains:

- a base system prompt telling Kira how to sound
- a grounding message with:
  - parent name
  - available students
  - selected student
  - school information
  - profile strengths and improvement areas
  - school performance
  - interest signals
  - career signals
  - recent activity
  - saved conversation summary
- recent conversation messages converted into LangChain message objects

The summary is used as prompt context, not as a separate deterministic reasoning layer. In other words, the model sees the summary and can use it, but the code is not making independent decisions from the summary outside the model call.

### Summary refresh

Kira keeps a rolling summary of longer conversations.

Current default behavior:

- first summary is generated after 10 completed parent turns
- after that, it refreshes every 3 parent turns

This summary exists to keep long conversations manageable. Once a summary exists, Kira does not need to send the full transcript on every future turn.

### Voice flow

The voice path is built on top of the same conversation logic, but with a provider-neutral voice service plus a Retell-specific adapter.

Current voice flow:

1. Retell sends an inbound webhook to `/integrations/retell/inbound-call`.
2. Kira verifies the webhook signature.
3. Kira looks up the caller phone number.
4. If the caller is known:
   - create a `voice_call` conversation
   - create a Redis-backed live session record
   - return `override_agent_id` plus metadata including `conversation_id`
5. Retell opens the custom LLM websocket at `/integrations/retell/llm-websocket/{call_id}`.
6. Kira sends the required initial websocket config event.
7. Retell sends `call_details`, and Kira binds the websocket session back to the stored conversation.
8. When Retell sends `response_required`, Kira persists the caller turn, generates or scripts the answer, persists the agent message, and returns a Retell `response` event.
9. When Retell sends `reminder_required`, Kira uses the voice reminder flow:
   - first reminder: `Can I help you with something else?`
   - next reminder after continued silence: silence-specific farewell and end call
10. Retell lifecycle webhooks update the saved conversation status when the call starts or ends.

Unknown callers are handled as a voice-specific special case:

- no conversation row is created
- Retell still routes the call to the voice agent
- the websocket immediately returns a static line telling the caller to use their registered number
- the call ends

## Codebase Tour

The project is organized by module rather than by technical layer alone.

```text
src/
  core/
    config.py              # Settings and environment variables
    events.py              # App lifespan setup
    router.py              # Main router composition and /health
  db/
    session.py             # SQLAlchemy engine/session setup
  middlewares/
    request_id.py          # Request logging with request ids
  modules/
    agent/
      graph.py             # LangGraph runtime wiring
      nodes.py             # Student resolution, answer generation, summary refresh
      models.py            # OpenAI model client construction and feature routing
      prompts.py           # Prompt building for answers and summaries
    conversations/
      router.py            # REST endpoints for text conversation flow
      service.py           # Core conversation orchestration
      repository.py        # Conversation persistence and context-window logic
      metadata.py          # Per-message metadata and usage/cost shaping
      schemas.py           # API request/response models
    profiles/
      repository.py        # Parent lookup and student resolution
      schemas.py           # Parent/student fixture schema normalization
      fixtures/
        parent_profiles.json
    voice/
      service.py           # Provider-neutral voice use cases
      session_store.py     # Redis/in-memory live call session state
      policies.py          # Progress, follow-up, close, and fallback messages
      integrations/
        retell/
          router.py        # Thin Retell HTTP/websocket endpoints
          adapter.py       # Retell webhook handling
          websocket_session.py
          security.py
          protocol.py
```

## Important Boundaries

### `profiles`

This module is the current source of truth for parent and student data.

Right now it is fixture-backed. The rest of the system talks to the `ProfileRepository`, not directly to the JSON file, so the data source can be replaced later without rewriting the conversation or voice code.

### `conversations`

This is the core application flow.

If you want to understand the business behavior of Kira, start here:

- conversation creation
- message persistence
- summary cadence
- API response shaping

### `agent`

This module decides which student the turn is about, builds prompts, calls the LLM, and optionally refreshes the summary.

The agent is intentionally simple:

- deterministic resolution and clarification path
- model call only when we actually need an answer or summary

### `voice`

This module is provider-neutral on purpose.

It owns:

- inbound caller acceptance
- live call session state
- per-turn persistence and dedupe
- scripted follow-up / close behavior

### `voice/integrations/retell`

This is the only place that should know about Retell-specific payloads, websocket event names, signature verification, and response envelopes.

That separation is important because we do not want the rest of the system tightly coupled to one voice vendor.

## Current APIs

### Conversation API

- `POST /api/v1/conversations/start`
- `POST /api/v1/conversations/{conversation_id}/messages`
- `GET /api/v1/conversations/{conversation_id}`

### Voice / Retell integration

- `POST /integrations/retell/inbound-call`
- `WS /integrations/retell/llm-websocket/{call_id}`
- `POST /integrations/retell/webhook`

### Operational endpoints

- `GET /`
- `GET /health`

`/health` currently reports:

- database health
- voice session store health
- in-memory voice metrics snapshot

Those voice metrics are process-local counters. They are useful for quick runtime visibility, but they are not durable metrics storage.

## Models And LLM Configuration

The system uses `langchain-openai` with `ChatOpenAI`, configured to use the OpenAI Responses API.

Current feature routing:

- parent answer generation: `gpt-5-mini`
- conversation summary refresh: `gpt-5-nano`

Current configured LLM parameters:

- `base_url`
- `timeout`
- `reasoning_effort`
- `use_responses_api=True`
- `stream_usage=True`

We are not currently setting things like:

- `temperature`
- `max_output_tokens`
- `top_p`
- penalties
- `seed`

So those are currently using provider/client defaults rather than app-defined values.

## Local Development

### Prerequisites

You need:

- Python 3.12
- Redis
- PostgreSQL if you use the default `DATABASE_URL`
- an OpenAI API key for answer generation
- Retell credentials only if you want to exercise the voice path

### Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you use `uv`, that works fine too, but the repo is currently documented around `requirements.txt`.

### Configure environment

```bash
cp .env-example .env
```

Minimum settings for text flow:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `LLM_PROVIDER`
- `LLM_MODEL`

Minimum extra settings for voice flow:

- `RETELL_API_KEY`
- `RETELL_INBOUND_VOICE_AGENT_ID`
- `RETELL_VERIFY_SIGNATURES`
- Redis connection settings

### Database setup

Important nuance: the app initializes the SQLAlchemy engine on startup, but it does not create or migrate schema automatically for you.

So for a fresh local environment, run migrations explicitly:

```bash
alembic upgrade head
```

If you keep the default config, you also need a Postgres instance available at:

```text
postgresql+asyncpg://kira:kira@localhost:5432/kira
```

### Run the app

```bash
python -m src.main
```

Then open:

- `http://localhost:8000/docs`
- `http://localhost:8000/health`

Swagger docs are enabled only in development mode.

## Docker

There is a `Dockerfile` and a `docker-compose.yml`, but there is one important caveat:

- Docker Compose currently provisions the app container and Redis
- it does not provision Postgres

So Docker Compose is useful, but you still need to point `DATABASE_URL` at a reachable database.

Run:

```bash
docker-compose up --build
```

## Retell Setup Notes

If you want to test the phone flow, configure all three parts:

1. Number-level inbound webhook
   - `/integrations/retell/inbound-call`
2. Custom LLM websocket URL on the Retell agent
   - `wss://<your-host>/integrations/retell/llm-websocket/`
3. Lifecycle webhook
   - `/integrations/retell/webhook`

Important practical notes:

- Use `wss://`, not `ws://`, for the public websocket URL.
- `Run Test` in the Retell agent UI is a `web_call`, not a real inbound phone call.
- The real phone path depends on the number-level inbound webhook because that is where Kira creates the conversation and injects `conversation_id` metadata.

## Testing

Run the full suite:

```bash
pytest
```

Useful focused runs:

```bash
pytest tests/modules/conversations/test_api.py
pytest tests/integrations/retell/test_retell_api.py
pytest tests/integrations/retell/test_security.py
```

The current tests cover:

- conversation start and message flow
- student resolution continuity
- clarification behavior
- summary cadence
- message ordering
- phone normalization
- Retell inbound webhook behavior
- Retell websocket response flow
- Retell reminder and close behavior
- Retell signature verification

## Current Limitations

A few things are intentionally simple right now:

- parent/student data is fixture-backed
- the answer prompt is still a broad grounding block rather than a more selective fact-gathering pipeline
- LLM generation parameters are only partially pinned
- voice metrics are in-memory only
- the voice integration is provider-neutral at the service layer, but Retell is the only implemented adapter

None of those are hidden assumptions. They are just the current stage of the system.

## Suggested Reading Order

If you are new to the repo, this is the order I would recommend:

1. [src/main.py](src/main.py)
2. [src/core/router.py](src/core/router.py)
3. [src/modules/conversations/service.py](src/modules/conversations/service.py)
4. [src/modules/profiles/repository.py](src/modules/profiles/repository.py)
5. [src/modules/agent/nodes.py](src/modules/agent/nodes.py)
6. [src/modules/agent/prompts.py](src/modules/agent/prompts.py)
7. [src/modules/voice/service.py](src/modules/voice/service.py)
8. [src/modules/voice/integrations/retell/websocket_session.py](src/modules/voice/integrations/retell/websocket_session.py)

That path gives you:

- app wiring
- text conversation behavior
- student resolution
- prompt generation
- voice reuse of the same core logic

## Why Kira Exists

This project is not trying to build another dashboard.

The core bet is that a parent often does not want to inspect charts, tables, and feature screens. They want to ask a direct question in natural language and get a direct, grounded answer back. The entire repo is organized around making that interaction reliable, debuggable, and extensible across both text and voice.
