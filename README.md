# Time Tracker

Personal work-time tracking & analysis. CLI-first, designed so a web/phone
front-end can be added later over the same core.

Meetings (from Google Calendar) are the fixed scaffold; the tool helps you
track and understand **the gaps between them**.

- **Using it day to day:** [`docs/guide.html`](docs/guide.html)
- **Design & rationale:** [`docs/design.html`](docs/design.html)

`tt` works from any terminal in any folder (a launcher is installed at
`~/.local/bin/tt`) — no `conda activate` needed for normal use. Data lives in
`~/.time_tracker/`.

## Development

```bash
conda activate time_tracker
pip install -e ".[dev]"
pytest
```

## Status

- [x] Phase 1 — Core & storage (SQLite, models, config)
- [x] Phase 2 — Capture (timer / check-in / backfill)
- [x] Phase 3 — Calendar sync
- [x] Phase 4 — Workday & reminders
- [x] Phase 5 — CLI front-end
- [x] Phase 6 — Analysis
