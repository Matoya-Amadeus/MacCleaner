# Protected Browser Session Data

Browser identity/session data is a hard protection boundary.

## Always blocked by default

- Firefox profile cookies, storage, logins, key databases, and sessionstore backups.
- OpenAI/ChatGPT cookies, local storage, session storage, login databases, and browser profile records.
- Keychain material and `.ssh` identity material.
- App support files that clearly contain token/session state.

## Required behavior

- Read-only inspection is allowed when needed to classify risk.
- Cleanup plans must mark these targets as `protected_session` and `protection=blocked`.
- Generic cache cleanup, browser cleanup, profile reset, or app leftover cleanup must not remove these paths.
- Do not offer a normal confirmation bypass for protected browser/OpenAI session data.
