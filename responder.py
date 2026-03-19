import anthropic
import os
from dotenv import load_dotenv
from templates import TEMPLATES

# Initialize the Anthropic client once so individual calls stay lightweight.
load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def generate_response(message: str, classification: dict) -> str:
    """Draft a natural, templated reply that matches the classification category."""
    # Fall back to the generic template if we ever see an unknown category.
    template = TEMPLATES.get(classification["category"], TEMPLATES["other"])

    # The model is asked to follow the template style but to personalize {specific_detail}
    # based on the original message, keeping the final answer short and human‑sounding.
    prompt = f'''You are a professional communications assistant.
    Using the template below as a guide, write a warm and specific response
    to the message. Fill in the {{specific_detail}} placeholder with something
    directly relevant to the original message. Keep it concise and human.
    Original message: {message}
    Template: {template}
    Return only the final response text, nothing else.'''

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    # We treat the first content block as the final reply and strip any stray whitespace.
    return response.content[0].text.strip()
