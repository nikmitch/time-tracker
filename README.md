# Time Tracker

Personal work-time tracking & analysis. CLI-first, designed so a web/phone
front-end can be added later over the same core.

Meetings (from Google Calendar) are the fixed scaffold; the tool helps you
track and understand **the gaps between them**.

See [`docs/design.html`](docs/design.html) for the full design.

## Development

```bash
conda activate time_tracker
pip install -e ".[dev]"
pytest
```

## Status

- [x] Phase 1 — Core & storage (SQLite, models, config)
- [ ] Phase 2 — Capture (timer / check-in / backfill)
- [ ] Phase 3 — Calendar sync
- [ ] Phase 4 — Workday & reminders
- [ ] Phase 5 — CLI front-end
- [ ] Phase 6 — Analysis
