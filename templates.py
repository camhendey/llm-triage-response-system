TEMPLATES = {
    # Short, friendly replies for each high‑level category. The model is responsible
    # for filling in {specific_detail} with something grounded in the original message.
    "inquiry": "Thanks for reaching out. {specific_detail}. Let me know if you have any other questions.",
    "complaint": "I'm sorry to hear about your experience. {specific_detail}. We'll make sure to address this right away.",
    "urgent_request": "Got it, treating this as a priority. {specific_detail}. We'll be in touch shortly.",
    "confirmation": "Confirmed. {specific_detail}. Looking forward to it.",
    "cancellation": "Understood, we've noted your cancellation. {specific_detail}. Let us know if anything changes.",
    "other": "Thanks for your message. {specific_detail}. We'll get back to you soon.",
}

PRIORITY_MAP = {
    # Business‑level mapping from category to a coarse priority tier that callers can use
    # for routing, queue ordering, or display without re‑encoding this logic.
    "urgent_request": "high",
    "complaint": "high",
    "inquiry": "medium",
    "cancellation": "medium",
    "confirmation": "low",
    "other": "low",
}