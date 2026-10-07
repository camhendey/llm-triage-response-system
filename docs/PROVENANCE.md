# Project provenance and authorship

**Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.**

Cameron inherited the default guest-response templates. He created and implemented the additional workflow elements: structured information gathering, prompt workflows, booking-note organization, exception handling, response preparation and coordination with restaurant operations. The inherited templates are source material, not claimed as his original writing.

During employment the workflow used general-purpose LLM chat tools. Cameron manually checked availability and restaurant flow, updated the reservation platform with guest details and allergens, and prepared replies. There were no Python scripts or API integrations in that operational workflow.

This repository translates that workflow into a working software prototype with typed facts, deterministic seating checks, a human review process, versioned decisions, simulated booking mutations and validated drafts. Sole-developer credit identifies Cameron's project ownership, design and implementation responsibility; it is not a claim that coding tools or LLM assistance were never used.

The 2024/2025 dates describe the project's workflow origin and refinement. Current software builds and verification records retain their actual execution dates. The Python application is not represented as software that was deployed at JOEY in those years.

## Historical outcome versus software evidence

Cameron's reported **approximately 45 to 5 minutes** describes his estimate of active handling time for one typical complex inquiry: reading the message, understanding requests, checking availability and service flow, updating guest details and allergens, and preparing the initial reply. It is not a measured benchmark of this software. No timed user study has yet established software time savings.

The software demonstrates concurrency checks, overlap detection, atomic changes and draft consistency on synthetic examples. Those tests do not establish a reduction in real restaurant double bookings.

## Data and affiliation

The restaurant configuration, guest identities, contacts and cases in this repository are synthetic. JOEY is named only as the historical workplace where the original workflow was developed. This independent portfolio application is not endorsed by, deployed at, or integrated with JOEY or any reservation platform.

Original employment documents containing real business contacts are excluded. No historical restaurant thresholds, table plans or operating policies are presented as current production policy.

[Development decisions](DECISIONS.md) · [Claims register](CLAIMS.md) · [Evaluation](EVALUATION.md)
