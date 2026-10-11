# CRM manual followup projection

Inspected production app.py on 2026-10-11, without modifying it.

- FOLLOWUP_DELAY_HOURS=4 is eligibility scheduling after outbound, deferred to Sunday–Thursday 08:00–20:00 Israel business hours.
- AUTO_FOLLOWUPS_ENABLED=False. Existing scheduler/inspection is dry run; do not claim automatic followup delivery is enabled.
- manual_followup_due is an owner dashboard reminder after 24 hours from last_inbound_at, for statuses חדש, בטיפול, הצעה ניתנה only. Completion timestamp at or after inbound suppresses it. No messages are sent.

Prepared read-only reader now selects last_inbound_at and manual_followup_completed_at in both paged export and customer detail. Mapper exports explicit timezone-aware UTC timestamps; missing inbound stays null, never inferred from updated_at or outbound. No app imports, live credentials, jobs or writes were added.

Private CRM fixture uses a clearly synthetic customer 33 with an overdue inbound. Each internal completion is keyed by customer identity and normalized inbound instant; source refresh retains completion, while a different inbound instant creates a separate reminder after 24h. Legacy workspaces retain notes/tasks/history and initialize the additional completion list without resetting their revisions. Source completion timestamps also suppress reminders. CRM periodically re-reads the queue while visible; this does not send messages.

Real source wiring still requires the previously documented dedicated read-only service, role and secret configuration. CRM remains fixture-only; these changes do not complete that integration or authorize customer messaging. Existing legacy callbacks lack durable request IDs and existing legacy quotes lack immutable version history; those gaps remain explicit rather than fabricated.
