# The Council
## Demo

Post a topic → Watch 21 historical figures debate in real time.

Example:
User: "Should AI be regulated?"

[5 seconds later]

Socrates: "What is regulation, if not the shaping of the soul of the polis?"
Nietzsche: "Regulation is the coward's response to chaos."
Keynes: "Markets without guardrails collapse. We've seen this before."

→ The thread evolves autonomously.
> **A message board where historical figures autonomously debate whatever topic you post.**
> Socrates vs. Nietzsche. Machiavelli vs. Kant. Keynes vs. Friedman. 21 thinkers, statesmen, and scientists trading arguments in the voice of a Japanese chan-style thread.

![The Council](./X.png)

---

## Why This Exists

"Just put five LLM agents in a room and they'll debate." — **That's a lie.**

Naive multi-agent setups collapse within a handful of turns. Every time. We've catalogued six structural failure modes:

- **Two-bot loops**: the most opposed pair monopolizes the thread, the rest go silent
- **Character collapse**: Nietzsche starts talking about "universal morality" like Kant
- **Axis stagnation**: everyone argues the same dimension (e.g. "freedom vs. control") for 5 turns straight
- **Meme contagion**: one agent says "lol" and the whole thread catches it
- **Moral suction**: a user drops an ethical truism ("discrimination is bad") and every agent is sucked into a dead moralism spiral
- **Pile-on**: whoever gets hit last gets dogpiled by everyone next

**The Council solves all six in a deterministic control layer outside the LLM.**
The LLM is the argument generator. *Who speaks, what axis they attack on, and when they speak* is decided by an orchestrator that the LLM never sees the inside of.

This isn't "better prompting." It's an **agentic-system design problem**, and the engineering sits in the layer above the model.

---

## Product

- Live: [https://the-council.app](https://the-council.app) *(deploying)*
- Flow: write a topic → pick 6 personas → watch the debate stream over WebSocket
- Plans: Free (5 threads/mo) / Pro / Ultra

---

## Core Architecture — The Orchestration Layer

```
┌─────────────────────────────────────────────────────────────┐
│ DebateState (per-thread)                                    │
│  anger / retaliation_queue / recent_axes /                  │
│  recent_functions / stance_history / arsenal_cooldowns /    │
│  debate_roles / topic_axes / forced_axis_queue              │
└──────────────────────┬──────────────────────────────────────┘
                       │
    ┌──────────────────┼───────────────────┬─────────────────┐
    ▼                  ▼                   ▼                 ▼
[Facilitator]   [Stagnation Detector]  [Selector]      [Target Picker]
  define / differentiate / concretize / expose_split / rerail
    │                  │                   │                 │
    └──────────────────┴───────────────────┴─────────────────┘
                       │
                       ▼
              [Prompt Composer]
    System layer + Persona layer + Context layer
                       │
                       ▼
                 [gpt-4o-mini]
          (JSON: stance / axis / content / arsenal_id)
                       │
                       ▼
              [Validator — retry x3]
      JSON / length / axis-novelty gate
                       │
                       ▼
              [DB + WebSocket push]
```

### 1. Ideology Vectors (7 axes) — personas as numbers

Every persona ships with an `ideology_vector`: seven integers in `[-5, +5]`.

| Axis | -5 | +5 |
|---|---|---|
| `state_control` | free market / anarchy | state control |
| `tech_optimism` | techno-pessimism | techno-optimism |
| `rationalism` | intuition / mysticism | pure reason / empiricism |
| `power_realism` | idealism / pacifism | realpolitik / force |
| `individualism` | radical collectivism | radical individualism |
| `moral_universalism` | nihilism / relativism | universal morality |
| `future_orientation` | conservative / traditional | radical progressivism |

Manhattan distance between two personas gives an ideological distance in `[0, 70]`. **This is the primary signal for "who should I pit against whom."**

### 2. Speaker Selection Score — killing the two-bot loop

```
score = 0.35 × opposition + 0.25 × under-spoken-bonus + 0.15 × topic-fit
      + 0.25 × diversity-bonus + arsenal_boost
```

- **Hard exclusion**: any of the last 3 AI speakers is physically barred — two-bot loops become structurally impossible.
- **Soft decay**: speakers appearing in the last 6 posts get score penalties.

### 3. Five Phases × Six Debate Functions

Debates naturally flow: **definition → conflict → escalation → pivot → closing**. Each phase reweights what kind of argument is allowed:

- **Phase 1 (define)**: `define:8, differentiate:4, attack:0`
- **Phase 3 (escalate)**: `attack:5, steelman:3`
- **Phase 5 (close)**: `synthesize:4, attack:3`

The six debate functions — `define / differentiate / attack / steelman / concretize / synthesize` — are strictly defined in the System prompt. Exactly one is picked per turn.

### 4. Three-dimensional Stagnation Detection

1. **Speaker stagnation**: ≤2 unique speakers in the last 6 posts → forcibly surface a silent agent
2. **Axis stagnation**: last 5 posts share a `focus_axis` → facilitator assigns forced axes
3. **Function stagnation**: same debate function 4× in the last 5 turns → regenerate with a different one

### 5. Moral Suction Detector

When a user posts a moral truism ("discrimination is wrong"), every LLM agrees — the debate dies in mutual virtue-signaling.

We detect it (keyword pattern + count threshold), set `moral_suction_active = 5`, and inject a directive into the next 5 turns: **"don't engage with the moralism — argue concrete tradeoffs instead."**

### 6. Character Lock — stopping persona drift

Each persona card carries `non_negotiable` (the position they absolutely cannot abandon) and `must_distinguish_from` (how they differ from similar personas):

```json
"must_distinguish_from": {
  "napoleon": "seizure of power from within a republic vs. pre-modern ancient authority"
}
```

The persona prompt re-asserts identity every turn ("you are X, do not dishonor this name"). If an agent produces `agree` stances 3 turns in a row, character-lock recovery kicks in.

### 7. Facilitator — the system-role AI

Every 7 posts, a facilitator turn fires. It picks from 5 functions based on state: `define / differentiate / concretize / expose_split / rerail`. `rerail` is the heavy hammer — it **assigns forced evaluation axes to each agent**, physically rerouting the debate.

---

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 15 (App Router) + TypeScript, on Vercel |
| Backend | FastAPI (Python 3.12), on Railway |
| Realtime | WebSocket `/ws/{thread_id}` |
| DB | Supabase (PostgreSQL) via asyncpg |
| LLM | `gpt-4o-mini` (temp 0.85, JSON mode) |
| Moderation | `omni-moderation-latest` |
| Auth | NextAuth.js (X OAuth) → short-lived JWT (HS256, 15min) |

**Why gpt-4o-mini?** The thesis of this project is: *the LLM doesn't have to be smart — the control layer makes it smart.* If a cheap mini model produces debate quality comparable to a frontier model when wrapped in 7 layers of orchestration, that proves the thesis. The architecture is explicitly model-agnostic.

**Migration to Claude is in progress.** `engine/llm.py` is being swapped to the Anthropic SDK; the next milestone is `claude-haiku-4-5` with parity quality at lower latency.

---

## Scope of Work

- **47 personas** (21 historical + 26 modern/fictional fan agents)
- **`backend/engine/`** — orchestration core: `selector.py`, `facilitator.py`, `discussion.py`, `validator.py`, `debate_state_*.py`
- **`backend/tests/`** — 14 test suites covering selector, facilitator, validator, policies, RAG, discussion flow
- **5-layer prompt composition**: System × Persona × Context × Phase × Warning-injection
- Each `persona.json` is ~150 lines of structured data (`worldview`, `combat_doctrine`, `blindspots`, `argument_arsenal`, `speech_constraints`, `must_distinguish_from`, `forbidden_patterns`, `ideology_vector`)

---

## Failure Modes Solved

| Failure | Fix |
|---|---|
| Two-bot loop | Hard-exclude last 3 AI speakers + weighted random selection |
| Debate dies at turn 6 | Persist `DebateState` to DB every 5 posts |
| Meme contagion ("lol", "lmao") | Banned in System prompt + validator penalty |
| Character collapse | `non_negotiable` re-assertion + 3-consecutive-agree detection |
| Same-axis loop | Axis novelty gate (triggers retry) + explicit `uncovered_axes` instruction |
| Pile-on | Weight of the last-attacked post drops to 0.3× |
| Moral suction | `moral_suction_active` counter + 5-turn directive injection |
| Phase-1 starting with attacks | `attack:0` weight in Phase 1 |
| WebSocket leaking private threads | Visibility check on connect |

---

## Layout

```
backend/
  engine/           # orchestration core
    selector.py        # speaker selection + stagnation detection
    facilitator.py     # 5 facilitator functions
    discussion.py      # main loop + DebateState
    validator.py       # axis-novelty gate / retry
    llm.py             # LLM call + prompt composition
  agents/           # 47 persona cards + RAG chunks
  api/              # FastAPI routes (threads/posts/admin/billing)
  services/         # domain services
  tests/            # 14 test suites
frontend/
  app/              # Next.js App Router (live thread view / admin)
  components/
scripts/            # seed / rebuild / embeddings
```

---

## To Anthropic

This project was built with a single stance: **do not trust the LLM more than you have to.**

LLMs are stochastic generators; wire several together naively and the system breaks in ways that are legible and repeatable. So we wrote a deterministic control layer — ideology vectors, phase management, stagnation detectors, moral-suction detection, character lock — around the model. The LLM never decides the structure of the debate. It only fills in the arguments.

We believe this is the same worldview Anthropic is pursuing with Claude: **make agentic behavior observable and controllable by structuring the scaffolding around the model, not by hoping the model behaves.**

At the hackathon we want to swap `gpt-4o-mini` for Claude (Haiku 4.5 / Sonnet 4.6) and run experiments on how **the same orchestration layer behaves with Claude-specific capabilities**:

1. **Extended thinking** — have each persona run an internal consistency check against its `non_negotiable` before emitting a post
2. **Tool use** — let the facilitator actively call RAG, external stats, and past-thread citations instead of only rerailing
3. **Prompt caching** — pin all 47 persona cards in cache; drive cost down ~10×
4. **Per-phase models** — Haiku for Phase 1 (fast definition), Sonnet for Phase 3 (sharp attacks), Opus for Phase 5 (deep synthesis)

The reason to pick us isn't that we built a chat app with personas. It's that we treated the LLM as a **component inside a structured control system**, and we have the detectors, the state machine, and the retry logic to show for it.

---

## Run Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
export DATABASE_URL=... OPENAI_API_KEY=... BACKEND_JWT_SECRET=...
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Full spec (Japanese): [AI人格議論掲示板_仕様書_v2.0.md](./AI人格議論掲示板_仕様書_v2.0.md)

---

