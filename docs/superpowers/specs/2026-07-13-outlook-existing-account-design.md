# Outlook Existing Account Integration Design

## Goal

Add an `outlook` email provider to the existing Grok registration tool. The provider uses Outlook or Hotmail accounts already owned by the user, retrieves xAI/Grok verification messages through Microsoft Graph, and then hands the verification code to the existing browser registration flow.

The feature must not create Microsoft accounts, bypass Microsoft verification, or automate Microsoft anti-abuse challenges.

## Existing Context

The project is a Python application with Tkinter GUI and CLI modes. Email-provider behavior is currently selected through `email_provider`, and the main registration flow expects two provider-level operations:

1. Obtain an email address and a provider credential/token.
2. Poll the mailbox and return the registration verification code.

The Outlook integration will follow these existing boundaries and avoid unrelated changes to the browser registration, Grok token export, or other email providers.

## Account Input

The primary import format is one account per line:

```text
email----password----client_id----refresh_token
```

The password field is accepted for compatibility and account inventory purposes but is not used for automated password login. Empty optional fields remain valid, for example:

```text
user@outlook.com----password----client-id----refresh-token
```

CSV input may also be supported when the file has the columns `email`, `password`, `client_id`, and `refresh_token`. The parser will normalize whitespace, ignore blank lines, reject malformed entries with a line-specific error, and never print secrets in logs.

Accounts without both `client_id` and `refresh_token` are imported but marked `needs_authorization`; they are not selected for automated registration.

## Architecture

### Account Model and Pool

Introduce a focused Outlook account model containing:

- email address
- optional password
- OAuth client ID
- OAuth refresh token
- runtime status
- last error

The pool selects the next usable account and prevents the same account from being assigned to concurrent registration attempts. Runtime status values are:

- `available`
- `in_use`
- `success`
- `needs_authorization`
- `token_invalid`
- `mail_timeout`
- `failed`

Status persistence will follow the project's existing configuration and output conventions. Source credential files will not be rewritten unless the user explicitly invokes a save/export action.

### Microsoft OAuth Client

Use the OAuth 2.0 refresh-token grant against Microsoft's consumer-compatible token endpoint. The client exchanges `client_id` and `refresh_token` for a short-lived access token.

The request uses the scopes already represented by the refresh token. The implementation does not request or store a new password-based session. OAuth errors are classified into actionable states, especially invalid or revoked refresh tokens and consent-related failures.

Access tokens are held in memory only. Passwords, refresh tokens, and access tokens are redacted from exceptions and application logs.

### Microsoft Graph Mail Reader

Use Microsoft Graph to query recent inbox messages. Polling will:

1. Record the registration attempt start time.
2. Query a bounded number of recent messages.
3. Prefer messages received after the attempt began.
4. Match likely xAI/Grok sender, subject, and content signals.
5. Extract a six-digit verification code from the subject, preview, or message body.
6. Ignore codes already observed during the current attempt.
7. Stop on success, cancellation, terminal OAuth failure, or timeout.

The reader uses bounded retries with short polling intervals and respects the application's existing cancellation callback.

### Provider Adapter

Add `outlook` to the existing provider selector in GUI and CLI configuration.

For `get_email_and_token`, the adapter returns the selected Outlook email plus an opaque in-memory account reference suitable for the current registration attempt. For verification-code retrieval, the adapter resolves that reference and invokes the Graph mail reader.

Other providers retain their current behavior.

## GUI and Configuration

The GUI will add Outlook-specific controls consistent with the current Tkinter layout:

- Outlook credentials file path
- browse/import action
- imported account count
- usable account count
- concise status or validation message

The configuration example will document the provider and credentials-file setting. Real credentials are not added to `config.example.json`, logs, tests, or documentation.

CLI mode reads the same configuration and reports account-file validation errors before starting browser automation.

## Error Handling

Errors are separated into categories that determine whether the account can be retried:

- malformed input: reject the affected line and report its line number
- missing OAuth data: mark `needs_authorization`
- invalid or revoked refresh token: mark `token_invalid`
- transient token or Graph failure: retry with a bounded backoff
- throttling: honor `Retry-After` when present
- no matching email before timeout: mark `mail_timeout`
- cancellation: release the account without marking it permanently failed

User-facing messages remain concise, while debug logs provide HTTP status and safe error codes without secret-bearing payloads.

## Security and Privacy

- Do not automate Outlook account creation.
- Do not use the stored password for web-login automation.
- Do not bypass MFA, CAPTCHA, consent, or account recovery prompts.
- Redact OAuth tokens and passwords from logs and exceptions.
- Keep access tokens in memory only.
- Avoid committing real credential files through ignore rules and documentation warnings.
- Apply conservative polling and retry limits to reduce Graph throttling and mailbox load.

## Testing

Add unit tests for:

- TXT and CSV account parsing
- malformed-line reporting
- secret redaction
- refresh-token success and failure classification
- Graph pagination or bounded message selection
- sender, time, subject, and body verification-code matching
- throttling and timeout behavior
- pool selection, release, and terminal status transitions

HTTP calls will be mocked. Existing provider tests must continue to pass. A syntax/import check and the full available test suite will be run before delivery.

## Acceptance Criteria

- `outlook` appears as a selectable provider in GUI and works in CLI configuration.
- Existing accounts with valid `client_id` and `refresh_token` can be imported.
- The application can exchange a refresh token and retrieve a matching xAI/Grok verification code through Microsoft Graph.
- The code is passed into the existing registration flow without changing other provider behavior.
- Invalid accounts receive an actionable status and do not block the remaining account pool.
- Secrets never appear in normal or debug logs.
- Existing tests pass and new Outlook-specific tests cover parsing, OAuth, mail matching, and pool behavior.

## Out of Scope

- Creating Outlook or Hotmail accounts
- Browser-based password login to Outlook
- CAPTCHA, MFA, consent, or recovery automation
- Obtaining OAuth app registrations or refresh tokens on the user's behalf
- Changing the existing Grok registration workflow beyond the provider adapter required for Outlook
