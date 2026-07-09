# Contributing to Cursor Bridge

## Setup

```bash
git clone https://github.com/winter2815651645-collab/cursor-bridge.git
cd cursor-bridge
```

Python 3.10+ required. No pip install — stdlib only.

## Project Structure

```
cursor-bridge/
├── cursor_bridge.pyw        # Main application
├── cursor_bridge_pure.py    # Pure-Python module (importable for tests)
├── tests/
│   └── test_cursor_bridge_pure.py
├── .github/workflows/
│   └── test.yml             # CI
└── cursor-bridge-startup.vbs # Auto-start helper
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Coding Conventions

- PEP 8
- English comments preferred for new code
- Pure logic goes in `cursor_bridge_pure.py` (testable without Windows)
- Win32 API code stays in `cursor_bridge.pyw`

## Pull Requests

1. Fork and create a feature branch
2. Add tests for new behavior
3. Run `pytest` before submitting
4. Keep changes focused — one thing per PR

## Reporting Bugs

Use the [bug report template](https://github.com/winter2815651645-collab/cursor-bridge/issues/new?template=bug_report.md). Include:
- Windows version
- Python version
- Steps to reproduce
- Expected vs actual behavior

## Feature Requests

Use the [feature request template](https://github.com/winter2815651645-collab/cursor-bridge/issues/new?template=feature_request.md). Explain the use case first.
