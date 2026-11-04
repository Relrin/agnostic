# Accessibility

Agnostic targets **WCAG 2.2 level AA**. The UI ships with one theme (dark) and in English only, so there is one set
of colour pairs and one set of strings to check; everything below applies to that theme. This page covers what is
checked automatically, the manual screen-reader pass to run before a release, and the scope for an external audit.

## What is checked automatically

| Check | Where | Run | Catches |
|---|---|---|---|
| Lint | `eslint-plugin-jsx-a11y` (recommended rules), every `.tsx` | `yarn lint` | missing labels and alt text, invalid ARIA, non-interactive handlers |
| Contrast | `packages/ui/src/lib/tokens.test.ts` | `yarn test` | every text/background token pair the design uses, against its ratio |
| Storybook a11y | every story, rendered in Chromium and checked with axe | `yarn workspace @agnostic/ui storybook:test` | violations in primitives and patterns, in isolation; both densities (`Foundations/Density`) |
| Page a11y | `frontend/apps/web/e2e/a11y.spec.ts`: every route, plus compact density and an open tour step | `yarn e2e` | violations on whole pages (landmarks, headings, duplicate ids, contrast in context) |
| Keyboard flows | `frontend/apps/web/e2e/keyboard.spec.ts` | `yarn e2e` | chat and approve a paused tool call, decide an approval, publish an agent, edit a role, without a mouse |

The page check renders each route against the shared e2e stubs, so many pages are scanned in their error state;
the other e2e suites reach the populated states. axe finds roughly a third of WCAG failures: focus order, reading
order, whether a label makes sense, and what a screen reader announces during streaming all need a person.

## Manual screen-reader checklist

Run it before each release, and after any change to the shell, a primitive in `packages/ui/src/primitives`, or the
run view. Pair **NVDA** (latest) with Firefox or Chrome on Windows, and **VoiceOver** with Safari on macOS. Use the
compose stack with the reference runtimes and `just seed`, signed in as an Owner and, for the access checks, as a
Member.

### Shell and navigation

- [ ] The page title and the `h1` name the page; landmarks list the sidebar navigation ("Primary"), the main area
      and any aside (NVDA: <kbd>D</kbd>; VoiceOver rotor: Landmarks).
- [ ] The heading outline makes sense with no level skipped (NVDA: <kbd>H</kbd> / <kbd>1</kbd>–<kbd>6</kbd>;
      VoiceOver rotor: Headings).
- [ ] The current page is announced in the sidebar ("current page").
- [ ] The instance switcher announces the instance and its environment; switching keeps you on the same page.
- [ ] ⌘K / Ctrl+K opens the command palette with focus in the search box; results are read as you arrow through
      them; Escape closes it and focus returns to where it was.
- [ ] The health status in the header and the notification bell's unread count are read.

### Forms and dialogs

- [ ] Every field reads its label, hint and error (sign in, connect an instance, profile, a schedule).
- [ ] A submit that fails moves you to, or announces, the error.
- [ ] Opening a dialog or sheet (Publish, Delete, Invite people) moves focus into it and reads its title; Tab stays
      inside; Escape closes it and focus returns to the button that opened it.
- [ ] Switches, checkboxes and radio cards read their state (Account › Preferences: API hints, Density).
- [ ] Toasts ("Published v4") are announced without moving focus.

### Tables and lists

- [ ] Data tables read their name and column headers when moving by cell (NVDA: <kbd>Ctrl+Alt+arrows</kbd>;
      VoiceOver: <kbd>VO+arrows</kbd>).
- [ ] Selected rows (sessions, approvals, roles) are announced as selected.
- [ ] Tabs that filter a table (Approvals: Pending, Approved, …) read the count with the label.
- [ ] The role matrix reads "Operator: knowledge write, checkbox, not checked", and the save bar announces the
      number of unsaved changes.
- [ ] The trace waterfall and span tree read each span's name, kind, duration and status; Enter selects a span.

### Runs, chat and approvals

- [ ] In Chat, the composer reads its label ("Message support-triage"); Enter sends and Shift+Enter adds a line.
- [ ] A streaming run announces "Run in progress" and then its final status, without reading every token.
- [ ] Tool calls are reachable and read their name and status.
- [ ] A paused run's approval card is a named region; Edit args, Approve and Reject are reachable, and the decision
      is announced.
- [ ] In the Approvals inbox, the note field reads that a note is required to reject.

### Onboarding

- [ ] Home's "Get started" card reads each step with "(done)" or "(to do)"; Dismiss removes it.
- [ ] "Show me" opens the page with its tour: focus moves to the step, which reads "Step 1 of 3", its title and
      text; Next, Back, Skip tour and Done are reachable; Escape ends the tour and focus returns.
- [ ] The highlighted target is visible at 200% zoom and the step popover stays on screen.

### Display

- [ ] At 200% browser zoom and at 320 CSS px wide (WCAG 1.4.10), no content or control is cut off; the sidebar and
      asides collapse or scroll.
- [ ] With text spacing overridden (WCAG 1.4.12), nothing overlaps.
- [ ] Every focusable control shows the lime focus ring, and nothing focusable is covered by a sticky header or the
      save bar (WCAG 2.4.11).
- [ ] With "reduce motion" on, panels and spinners don't animate.
- [ ] Compact density (Account › Preferences) keeps targets at least 24 × 24 px (WCAG 2.5.8).

Record the date, the screen reader and browser versions, and every failure as an issue labelled `a11y`.

## Scope for an external audit

Ask the auditor for a **WCAG 2.2 AA** conformance evaluation (WCAG-EM) of the web UI, with NVDA + Chrome, JAWS +
Chrome, VoiceOver + Safari (macOS) and keyboard-only testing, ending in a report and a VPAT/ACR (EU EN 301 549 and
US Section 508 editions).

**In scope**: the signed-in shell (sidebar, header, instance switcher, command palette, notifications); sign in,
invitation and password reset; Home with Get started and its tours; Chat, including a streaming run, a paused tool
call and team members; Sessions and Traces (waterfall, tree, attributes); the Approvals inbox and decision panel;
Studio: agent editor, validation, publish with gate overrides, and the workflow builder canvas; Scheduler; People
& groups, Roles & permissions, Service accounts, Audit log; Organization settings and instance settings; Account,
including density and notification preferences. Both densities.

**Sample**: every page above in its empty, populated and error states, plus every dialog and sheet they open.

**Out of scope**: AgentOS itself and anything it renders (agent output is shown as Markdown in our viewer, which is
in scope); the generated API reference; the CLI; email and Slack notification templates; other themes and
languages, which the UI doesn't offer.

**Known limits to tell the auditor**: the workflow builder canvas is a pointer-first editor. The audit should list
any canvas action without a keyboard path (through the inspector, the palette or the code view). Virtualized lists
(trace waterfall) render only the rows in view, and announce the total with `aria-rowcount`.
