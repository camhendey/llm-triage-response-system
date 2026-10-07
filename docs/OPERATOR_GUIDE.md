# Operator guide

Sole developer: Cameron Hendey. Original workflow developed at JOEY in 2024; refined in 2025.

The app records decisions for a simulated restaurant. Email sending and external reservation updates happen outside this app. Start with a scenario on the overview or an inquiry in the sidebar. Environment & settings contains the fixed demo clock, database switch, CSV import and demo reset.

## Complete one inquiry

1. **Understand the request.** Read the conversation and the next action. Adding a guest reply runs offline interpretation automatically. In live mode use **Interpret new reply** explicitly. Unknown information stays unknown.
2. **Review details.** Use **Edit guest details** for typed dates, times, party size and policy values. Save related changes together with a source/reason. Resolve ambiguous statements in **Sources and conflicts**. Occasion is optional. Empty form values do not erase existing records.
3. **Choose seating.** **Select suggested arrangement** is the shortcut. **Compare seating and times** shows feasible options, a table schematic, comparison rows and rejected-option reasons. Selecting an alternative is an offer, not evidence the guest accepted it. Update/confirm the requested time from the guest's reply before finalizing.
4. **Record the decision.** After selection, **Create hold**, **Confirm booking**, or **Review and commit change** performs human approval and an atomic availability recheck. In the demo these update only the local simulated booking. Short-notice holds ask for an expiry deadline.
5. **Prepare the reply.** **Prepare reply** uses the selected arrangement and actual action status. Edit the single reply field, **Save reply**, then **Mark reviewed**. Draft edits survive navigation within the current browser session; save to persist across restarts. Changed facts or seating invalidate earlier drafts and approvals.
6. **Hand off.** Export the reply and booking notes. Once you have sent a reply elsewhere, **I sent this reply elsewhere** adds the exact reviewed text to the conversation as an operator assertion. It does not send or verify delivery.
7. **Prepare service.** In **Service view**, choose a date, inspect occupancy and export the daily service handoff with access, allergens, billing, occasion and outstanding items. Expired or cancelled bookings are excluded.

## Exceptions and review

| Situation | Action |
|---|---|
| Facts change after selection | Resolve conflicts, select again and prepare a fresh reply. The earlier proposal cannot be committed. |
| Short acceptance such as “That time works” | The offline interpreter can connect it to a single preceding offer. Date/time remain **needs review** until confirmed. Ambiguous multi-option acceptances need manual clarification. |
| Above the public party-size limit | Flag for private-events review. Only **Record referral completed elsewhere** permits a draft to claim the referral happened. Neither action establishes private-room availability. |
| Minimum spend | Record the amount and guest agreement. Changing the amount clears the old agreement. |
| Allergy mentioned | Record allergy follow-up review; the reply must not guarantee accommodation. |
| Accessibility conflict | Select suitable step-free seating, resolve conflicting preferences with the guest, then record the agreement. The schematic is not a real floor plan. |
| Cancellation | Booking remains active until **Cancel booking** is committed with a reason. |
| Unavailable modification | Original booking remains intact; explain that the requested change is unavailable. |
| Hold expiry | The fixed demo clock governs demo expiry. Advancing it changes available tables; the session database uses real time. |
| Unsupported interpretation | Review the original text and enter facts manually; do not infer missing information. |

## Recovery

Record-version checks reject stale edits from other tabs. Reload and review the current facts. Duplicate commands are idempotent. Validation errors block draft approval; correct the text or regenerate it. The app is a single-operator prototype with independent connections per browser session, not a multi-user production service.

To use the optional live interpreter, configure `.env` from `.env.example` and restart. Only that provider calls an external API. Availability and booking decisions remain deterministic. Live integration has fake-client tests but no real API verification in this release.
