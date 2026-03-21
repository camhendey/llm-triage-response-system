## LLM Triage Response System

This repo is a **translation of an operational workflow into code**. The original system was **not code-based**—it was a decision-making process used in a high-volume restaurant environment to triage and respond to incoming guest reservation requests. This project is the **first structured implementation** of that process in Python.

The implementation keeps things split cleanly: **classify and triage** the message, **pick a response template** by category, then **draft a reply** that still sounds like a person wrote it.

You can run that flow from a **small Streamlit page** (`app.py`) or from the **command line** (`main.py`). Same pipeline; pick whatever fits how you’re working.

### One-line mental model

**A real-world decision system that used to live in someone’s head, now encoded so a machine can run it.**

---

## Why this exists

Incoming guest requests were often:

- inconsistent in format
- incomplete or ambiguous
- time-sensitive

Without a system, responses could drift and training new people took longer. The workflow was meant to add repeatability, consistency, and less mental overhead.

This repo is one way to show that kind of operational logic **formalized and routed** through software—not slide deck theory.

---

## What the system does (current state)

Given a message string (a guest request), the pipeline does:

1. **Interpretation**  
   No brittle parsing layer yet—the model reads the message and infers intent.

2. **Classification**  
   One category from:

   - `inquiry`
   - `complaint`
   - `urgent_request`
   - `confirmation`
   - `cancellation`
   - `other`

   You also get `confidence` (`high` / `medium` / `low`), a one-line `reasoning`, and a `priority` bucket from `PRIORITY_MAP`.

3. **Response**  
   `templates.py` picks the template for that category. Claude drafts the actual text using that template and the original message (including filling `{specific_detail}`).

That’s still an **early translation layer**: clarity and traceability matter more than clever abstraction right now. Tighter rules and validation can come later.

---

## Key code components

- `app.py` — Streamlit UI: paste a message, hit one button, see category, priority, reasoning, and suggested reply.
- `classifier.py` — Calls Claude for structured JSON classification; attaches `priority` via `PRIORITY_MAP`.
- `responder.py` — Chooses a template from `TEMPLATES`, asks Claude to write the final reply.
- `templates.py` — Category templates and `PRIORITY_MAP` (category → `high` / `medium` / `low`).
- `main.py` — CLI: one message as a string, or a batch from a CSV.

---

## Repository intent (what this is / isn’t)

This is not a toy demo, a tutorial walkthrough, or a paper architecture exercise.

It **is** a real workflow turned into code: systems thinking, process formalization, and a working sketch of something you could actually run in front of someone.

It’s not pretending to be a finished product. The structure is meant to stay readable while the internals evolve.

---

## Getting started

### 1. Install dependencies

From the project directory:

```powershell
python -m pip install -r requirements.txt
```

### 2. Configure Anthropic credentials

Create or edit a `.env` in the project root:

```text
ANTHROPIC_API_KEY=your_key_here
```

---

## Usage

### Web UI (Streamlit)

```powershell
streamlit run app.py
```

Streamlit should print a local URL (usually `http://localhost:8501`). If your browser doesn’t open on its own, paste that URL in manually.

On the page: paste an incoming message, click **Process Message**, and you’ll see category, priority (with a simple visual cue), the model’s reasoning, and the suggested response.

### Single message (CLI)

```powershell
python main.py "Hi I need to cancel my booking for Friday"
```

Output includes `category`, `priority`, `confidence`, `reasoning`, and `suggested_response`.

### Batch from CSV

```powershell
python main.py --batch sample_messages.csv
```

The CSV needs a `message` column. Results go to `output.csv`.

---

## Example input

`sample_messages.csv` has a mix of intents—inquiries, complaints, urgent requests, confirmations, cancellations, and so on—if you want something to batch through without writing strings by hand.

---

## Planned evolution

Rough direction from here:

- clearer modular boundaries as the logic grows
- more explicit, config- or rule-driven routing (not only prompt constraints)
- stronger validation and handling of messy inputs
- tests on the weird edge cases
- integrations (API, webhooks, whatever fits the next use case)

Longer term, the same triage shape could apply outside reservations—support queues, intake forms, anything where messy text shows up and you need consistent routing.

---

## Why employers should care

Rough signal for:

- pulling structure out of messy real-world input
- making implicit decision rules explicit and repeatable
- building something that reduces one-off judgment calls without pretending the hard parts disappear
