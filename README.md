# Time Tracker

Work-time tracking & analysis through the CLI.

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
