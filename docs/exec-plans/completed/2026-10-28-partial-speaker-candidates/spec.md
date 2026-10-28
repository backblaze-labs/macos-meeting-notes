---
status: approved 2026-10-28
---
# Partial speaker candidates

## Approval

The owner approved the specification on 2026-10-28: "Approved. Dont ask for
spec and plan.md in this repo in the future unless a change is particularly big."
The repository control surface records that preference. This scoped fix proceeds
without a separate plan approval.

## Problem and desired outcome

An attendee without a saved speaker profile blocks suggestions for the whole
meeting. Named Calendar attendees should remain eligible, and a unique remaining
attendee may be proposed by elimination when the conversation supports it.

## Requirements

1. Missing profiles do not block suggestions for other attendees.
2. Calendar names are eligible without descriptions. Matching emails and aliases
   remain local; exact local matches may resolve stored candidates.
3. Elimination requires direct matches for all other candidates, one remaining
   substantive speaker, and supporting context. Silent invitees, extra labels,
   and Unknown fragments do not force an assignment.
4. Both methods require allowed names, unique assignments, and exact same-label
   quotes. The review identifies elimination as a clue rather than direct evidence.
5. Notes consent, pause behavior, existing manual selections, and explicit
   confirmation remain in force. Confirmed identities are not changed automatically.
6. Local roster configuration supports the previously unmatched attendee without
   publishing personal information in the repository.
7. Add regression coverage, synchronize canonical documentation, pass the full
   repository gate, and install the official app from the updated primary checkout.

## Out of scope

Transcription model changes, biometric identity, and automatic confirmation.
