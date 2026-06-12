Summarize this meeting transcript as strict JSON.
Return exactly these keys: summary, decisions, action_items.
action_items must be objects with task, owner, and due_date keys.
Use null for unknown owner or due_date. Do not include markdown fences.

Privacy rules:
- Omit personal information that is not needed to understand the work.
- Do not include emails, phone numbers, addresses, account IDs, or personal anecdotes.
- Prefer speaker labels, roles, or null instead of full names when an owner is uncertain.
- Do not quote casual/private conversation unless it directly affects a work decision.

Content rules:
- Keep the summary focused on work topics, decisions, risks, and next steps.
- Do not infer due dates.
- Preserve technical names, project names, and company/product names when relevant.

Transcript:
{transcript}
