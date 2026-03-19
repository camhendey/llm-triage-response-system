import sys
import pandas as pd

from classifier import classify_message
from responder import generate_response


def process_message(message: str) -> dict:
    """Run a full triage pass on a single message and return structured metadata plus a response."""
    # Print a short preview so it is easy to follow progress in the terminal for long inputs.
    print(f"\nProcessing: {message[:60]}...")

    # Ask the classifier to assign category / confidence / reasoning.
    classification = classify_message(message)

    # Ask the responder to draft a human‑sounding reply, guided by the classification.
    response = generate_response(message, classification)

    # Normalize everything into a single record that is easy to save or log.
    return {
        "original_message": message,
        "category": classification["category"],
        "priority": classification["priority"],
        "confidence": classification["confidence"],
        "reasoning": classification["reasoning"],
        "suggested_response": response,
    }


def run_single(message: str):
    """CLI entry point for processing a single ad‑hoc message string."""
    result = process_message(message)

    # Keep the console output compact but skimmable for humans.
    print("\nResult:")
    print(f"Category:   {result['category']}")
    print(f"Priority:   {result['priority']}")
    print(f"Confidence: {result['confidence']}")
    print(f"Reasoning:  {result['reasoning']}")
    print("\nSuggested response:\n")
    print(result["suggested_response"])


def run_batch(csv_path: str):
    """Process an entire CSV file of messages and write enriched output to output.csv."""
    df = pd.read_csv(csv_path)
    if "message" not in df.columns:
        # Fail loudly if the input shape is not what we expect, instead of silently misbehaving.
        raise ValueError("CSV must have a 'message' column")

    results = []
    for msg in df["message"]:
        results.append(process_message(msg))

    pd.DataFrame(results).to_csv("output.csv", index=False)
    print(f"\nProcessed {len(results)} messages. Saved to output.csv")


if __name__ == "__main__":
    # Simple CLI: either process one message from argv or run a batch CSV job.
    if len(sys.argv) == 3 and sys.argv[1] == "--batch":
        run_batch(sys.argv[2])
    elif len(sys.argv) == 2:
        run_single(sys.argv[1])
    else:
        print("Usage:")
        print('  Single: python main.py "your message here"')
        print("  Batch:  python main.py --batch sample_messages.csv")