import anthropic
import os
import json
from dotenv import load_dotenv
from templates import PRIORITY_MAP

# Load environment variables (in particular ANTHROPIC_API_KEY) once at import time.
load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def classify_message(message: str) -> dict:
    """Call Claude to assign a category, confidence, reasoning, and derived priority to a message."""
    # The system prompt tightly constrains the task to a single label and fixed JSON schema.
    prompt = f'''You are a message triage assistant.
    Classify the following message into exactly one of these categories:
    - inquiry
    - complaint
    - urgent_request
    - confirmation
    - cancellation
    - other

    Message: {message}

    Respond in JSON only with this exact format:
    {{"category": "category_name", "confidence": "high/medium/low",
    "reasoning": "one sentence explanation"}}'''

    # Ask Claude for a short, purely JSON response so we can parse it reliably.
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    # The first content block is assumed to contain the JSON string we requested above.
    result = json.loads(response.content[0].text)

    # Attach a coarse-grained priority based on the chosen category so downstream code
    # does not need to know the mapping details.
    result["priority"] = PRIORITY_MAP.get(result["category"], "low")
    return result