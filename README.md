## LLM Triage Response System

This repo is a **translation of an operational workflow into code**. The original system was **not code-based**—it was a decision-making process used in a high-volume restaurant environment to triage and respond to incoming guest reservation requests. This project is the **first structured implementation** of that process in Python.

The current implementation focuses on a clear separation of concerns: **classification and triage** followed by **routing into a response template**, then drafting a human-sounding reply.

### One-line mental model

**A real-world decision system, previously executed mentally, now encoded into a programmable triage engine.**

---

## Why this exists

Incoming guest requests were often:

- inconsistent in format
- incomplete or ambiguous
- time-sensitive

Without a system, responses could become inconsistent and onboarding new staff was harder. The workflow introduced:

- repeatability
- consistency
- reduced cognitive load

This repository demonstrates how that kind of operational logic can be **formalized and routed** through software.

---

## What the system does (current state)

Given a message string (a guest request), the pipeline performs:

1. **Input interpretation**
   - The system does not rely on rigid parsing yet; it uses an LLM to interpret the message intent.

2. **Classification**
   - The message is classified into exactly one category:
     - `inquiry`
     - `complaint`
     - `urgent_request`
     - `confirmation`
     - `cancellation`
     - `other`
   - The classifier also returns:
     - `confidence` (`high` / `medium` / `low`)
     - `reasoning` (one sentence)
     - `priority` derived from `PRIORITY_MAP`

3. **Routing / response templating**
   - A response template is selected based on the category (in `templates.py`).
   - Claude drafts a warm reply using the chosen template as a guide and filling in the `{specific_detail}` placeholder based on the original message.

Important note: this is an **early stage translation layer**. The repo is designed to preserve clarity and traceability over abstraction right now, and additional rule-based constraint evaluation and more structured routing are planned next.

---

## Key code components

- `classifier.py`
  - Calls Claude to produce structured JSON classification.
  - Parses the JSON and attaches `priority` via `PRIORITY_MAP`.
- `responder.py`
  - Selects a template from `TEMPLATES` based on the category.
  - Prompts Claude to draft the final reply text.
- `templates.py`
  - Contains category-specific reply templates.
  - Contains the `PRIORITY_MAP` (category → `high`/`medium`/`low`).
- `main.py`
  - CLI entry point to run a triage pass for a single message or a batch of messages in a CSV.

---

## Repository intent (what this is / isn’t)

This is not:

- a toy project
- a tutorial exercise
- purely theoretical systems design

This is a **real operational system translated into code**: a working example of systems thinking, process formalization, and early system design that aims for **consistency and repeatability**.

The repo is intentionally not a fully polished product yet. It preserves original logic structure where useful and is evolving toward a cleaner modular triage engine.

---

## Getting started

### 1. Install dependencies

From the project directory:

```powershell
python -m pip install -r requirements.txt
```

### 2. Configure Anthropic credentials

Create (or edit) a `.env` file in the project root with:

```text
ANTHROPIC_API_KEY=your_key_here
```

---

## Usage

### Single message

```powershell
python main.py "Hi I need to cancel my booking for Friday"
```

You’ll get output that includes:

- `category`
- `priority`
- `confidence`
- `reasoning`
- `suggested_response` (the drafted reply)

### Batch from CSV

Run:

```powershell
python main.py --batch sample_messages.csv
```

Requirements for the CSV:

- It must contain a `message` column.

The script writes enriched results to `output.csv`.

---

## Example input

This repository includes `sample_messages.csv` with messages representing different intents (inquiry, complaint, urgent request, confirmation, cancellation, etc.).

---

## Planned evolution

The next steps are to move from prompt-constrained classification + templated drafting toward a more explicit, rule-based triage engine, including:

- modular architecture (separating concerns more cleanly)
- rule-based / config-driven routing logic
- clearer classification layers
- improved input handling and validation
- test coverage for edge cases
- optional API/UI layer for integration

Long-term direction: generalize this triage engine beyond a single domain (e.g., support tickets or other intake systems) while preserving the core “translation of operational workflow into code” approach.

---

## Why employers should care

You can think of this as signal for:

- extracting structure from messy real-world inputs
- formalizing previously implicit decision logic
- building a repeatable routing engine that reduces cognitive load and improves consistency

