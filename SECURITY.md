# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.9.x   | :white_check_mark: |
| < 1.9   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public issue.

Instead, email [winter2815651645@users.noreply.github.com](mailto:winter2815651645@users.noreply.github.com) with details.

You can expect a response within 48 hours. After triage, we will send regular updates on the fix progress.

## Scope

Cursor Bridge is a local clipboard tool that runs entirely on your machine. Security concerns primarily involve:

- Clipboard data handling (text stays local, never transmitted)
- Win32 API usage (standard Windows clipboard APIs)
- Python stdlib dependencies (no third-party packages)

If the vulnerability is accepted, we will coordinate a fix and release. You will be credited in the release notes (unless you prefer to remain anonymous).
