# Modern Light Desktop UI Design

## Goal

Redesign the existing Tkinter GUI as a polished, light enterprise-style desktop workbench while preserving the current registration, browser automation, email-provider, CPA export, token-pool, configuration, and CLI behavior.

The approved direction is **B1: light professional styling with persistent left navigation**. The implementation will use CustomTkinter for modern controls and will avoid a broad rewrite of registration business logic.

## Design Principles

- Present the application as a dependable operational tool rather than a collection of configuration fields.
- Make common actions visible immediately and move low-frequency settings out of the primary workflow.
- Use restrained color, spacing, typography, and status feedback instead of decorative effects.
- Keep existing configuration keys and command-line behavior compatible.
- Preserve the user's current uncommitted functional changes.

## Visual System

### Color

- Application background: soft cool gray
- Surfaces and cards: white
- Primary action: clear medium blue
- Success: restrained green
- Warning: amber
- Error: warm red
- Primary text: near-black blue-gray
- Secondary text: muted slate
- Borders: subtle cool gray

### Shape and Spacing

- Cards and panels use consistent medium-radius corners.
- Buttons and inputs use smaller matching radii.
- Cards rely on borders and very subtle depth rather than heavy shadows.
- Page gutters, section gaps, form rows, and control heights follow a shared spacing scale.
- Dense advanced settings remain readable through grouping and internal whitespace.

### Typography

- Use the system UI font stack available on Windows.
- Page titles, section titles, field labels, helper text, metrics, and logs have distinct hierarchy.
- Avoid oversized headings and all-caps decoration except compact status labels.

## Information Architecture

The application uses a persistent left sidebar with five destinations:

1. **Overview**
2. **Registration**
3. **Email**
4. **CPA & Tokens**
5. **Settings**

The sidebar also contains the product mark and compact application identity. The selected destination uses a tinted blue background and stronger text color.

The main content area has a shared header containing:

- current page title and short description
- current email provider
- application or task status

Only the page content changes during navigation. Active tasks continue running when the user changes pages.

## Pages

### Overview

The overview provides operational awareness without exposing every setting:

- target registration count
- successful registrations
- failed registrations
- usable Outlook-account count when Outlook is selected
- current provider and browser mode
- quick task configuration
- primary start and stop actions
- recent or live log output

Before a task starts, cards show neutral empty-state content. During execution, metrics and status update without blocking the interface. Errors appear as concise inline alerts and remain available in the log.

### Registration

This page contains frequently changed execution controls:

- target count
- concurrency
- proxy
- NSFW option
- minimized browser option
- headless browser option
- task start and stop actions

Outlook mode communicates that concurrency is limited to one to avoid duplicate mailbox assignment.

### Email

The page begins with a provider selector and dynamically displays only the fields relevant to the selected provider.

Provider sections include:

- DuckMail API key
- GPTMail API key
- Cloudflare API base, authentication mode, API key, and paths
- Outlook credentials-file path, import validation, total account count, and usable account count
- YYDS credentials already represented by the current configuration

Changing the provider updates visible fields but does not erase hidden provider settings. Validation messages appear beside the relevant section.

### CPA & Tokens

This page groups output and downstream integrations:

- local grok2api token-pool enablement, path, and pool name
- remote grok2api enablement, base URL, and application key
- CPA export enablement and auth directory
- CPA probe and hot-load options already supported by configuration
- safe status summaries without displaying tokens or passwords

Secret-bearing inputs use password masking with an explicit reveal control only where useful.

### Settings

The settings page contains low-frequency or advanced options that do not belong in the main registration workflow. It also provides a clear save action and confirmation state.

Settings are loaded from and saved to the existing `config.json` structure. No migration is required.

## Component Architecture

Use a gradual UI refactor:

- Keep the current registration and automation functions intact.
- Keep task worker behavior compatible with the existing GUI methods.
- Add a small UI package or focused modules for theme tokens, shared cards, labeled fields, status badges, navigation items, alerts, and scrollable page containers.
- Break page construction into focused builder methods or classes instead of adding another monolithic initializer.
- Maintain Tkinter variable compatibility where it reduces risk, using CustomTkinter variables and widgets where appropriate.

The UI layer reads and writes through the existing global configuration boundary. Business operations remain callable by GUI and CLI code.

## Interaction and State

### Navigation

- Navigation is immediate and does not recreate running worker state.
- The active item and page title update together.
- The last active page may remain in memory for the current session; persistent navigation state is not required.

### Task State

- Start is disabled while a task is active.
- Stop is enabled only while a task is active.
- Status badges distinguish ready, running, stopping, success, warning, and failure.
- Metrics update from the existing success and failure counters.
- Logs remain available from Overview and preserve current output behavior.

### Validation

- Validation occurs before a task begins.
- Invalid fields receive inline messages and visual emphasis.
- Provider-specific requirements are evaluated only for the selected provider.
- Modal dialogs are reserved for destructive or blocking situations; routine feedback stays inline.

### Responsive Desktop Behavior

- The default window remains suitable for standard desktop resolutions.
- At narrower widths, the sidebar becomes compact and secondary labels may hide.
- Page bodies use scrollable frames so no control becomes inaccessible.
- The minimum window size prevents unusable layouts.

## Compatibility

- Preserve `config.json` keys and values.
- Preserve GUI and CLI startup commands.
- Preserve existing output files and registration behavior.
- Add CustomTkinter to `requirements.txt` and PyInstaller collection rules.
- Continue supporting source execution and a rebuilt Windows executable.
- Do not commit real credentials or tokens.

## Error, Loading, and Empty States

- Overview metrics display neutral placeholders before initialization.
- Outlook account validation displays loading, usable, partially usable, empty, and invalid-file states.
- Task errors appear in an alert card with a short explanation and remain in logs.
- Disabled integrations use designed empty states with an activation action rather than blank panels.
- Long operations retain visible status and do not freeze navigation.

## Testing and Verification

Verify:

- application import and GUI startup
- all five pages render and switch correctly
- existing config values populate the correct controls
- saving retains hidden provider values
- start, stop, running, and completion states update correctly
- provider-specific sections show and hide correctly
- Outlook credentials validation and usable-account totals work
- CPA and token settings remain wired to existing configuration
- CLI operation remains unaffected
- current unit tests continue passing
- PyInstaller build completes and the generated executable opens

A real browser registration run is desirable for final validation but depends on the user's external accounts, network, and target-service state.

## Acceptance Criteria

- The GUI visually matches the approved light professional B1 direction.
- Persistent left navigation organizes the application into the five approved pages.
- Common registration actions are available from Overview and Registration.
- Provider-specific email settings no longer compete for space on one large form.
- Existing functionality, configuration, CLI mode, and output behavior remain compatible.
- The GUI has designed ready, running, empty, validation-error, and failure states.
- Source mode and the rebuilt executable start successfully.

## Out of Scope

- Rewriting the registration automation engine
- Replacing Tkinter with a web or Electron application
- Changing remote CPA or NewAPI server behavior
- Adding new email providers or registration capabilities as part of this UI redesign
- Redesigning the CLI interface
