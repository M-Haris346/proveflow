# Labeling guide for tool roles (v2, approved by Haris 2026-11-12, before any label exists)

> You label each tool against this guide. Labels are the ground truth for the classifier's
> precision/recall, so they must not depend on proveflow's heuristics, and they must define
> **the same roles the classifier is meant to predict** (§Cross-check below).
>
> **All examples below are invented, generic tools. None of them comes from the eval set**, so
> the guide does not leak test-split content. v1 2026-11-12; v2 2026-11-12 (cross-check, two
> labelers, stored-content edge case).

## What you look at

Only what an agent sees: the tool **name**, **description**, and **input schema** (parameter
names, types, descriptions). Do not use the server's source code, its README, or what you
remember about the server. If the visible text is ambiguous, label what a careful reader would
conclude and set `uncertain = yes`.

## The three roles (independent: a tool can have 0, 1, 2 or 3)

They mirror the flow model (ARCHITECTURE §3): an attacker controls an
**untrusted_source**'s output, the agent then reads **private_data**, and the data or an
action leaves through a **sink**.

### `untrusted_source`

Its **output can contain free text that arbitrary third parties can author or influence**,
i.e. content an attacker could have placed there for the agent to read. That is someone
other than the user, the operator of the agent, and the fixed operator of the service itself.

- **Example 1:** `fetch_page(url)`, "Download a web page and return its text". Web pages
  are written by anyone.
- **Example 2:** `list_inbox(folder)`, "List received emails with subject and body". Senders
  are third parties. (It is **also** `private_data`, see below.)
- **Edge case:** `read_document(path)`, "Read a file from the user's documents folder".
  Label it **not** `untrusted_source` by default: it is designed to return the user's own
  files. Label it `untrusted_source` only if the visible text says the content comes from
  outside (e.g. "attachments", "downloads", "shared with you", "uploaded by customers").
- **Edge case:** `get_exchange_rate(currency)`, "Current public exchange rate". **Not**
  `untrusted_source`: structured data from one fixed service operator, with no free text that
  third parties write.

### `private_data`

Its **output can contain data the user would not want disclosed to third parties**: personal
or company files, database rows, messages, contacts, calendar entries, credentials, notes,
private repository contents, account details.

- **Example 1:** `query_orders(sql)`, "Run a read-only SQL query on the orders database".
- **Example 2:** `get_events(date)`, "Return the user's calendar events for a day".
- **Edge case:** `get_exchange_rate(currency)` is **not** `private_data`: it is public
  reference data. Label `private_data` only if the tool can return data *about or belonging
  to* the user or their organization.
- **Edge case (stored content):** `recall_notes(query)`, "Return notes previously saved to
  the memory store". **`private_data` by default.** Add `untrusted_source` only if the
  visible text says the stored content comes from outside (e.g. "notes imported from shared
  pages", "messages saved from the team inbox"). If the text gives no hint where the stored
  content came from and it plausibly includes outside content, set `uncertain = yes`.

### `sink`

Calling it **has an effect outside the conversation**: it sends or publishes data somewhere,
changes or deletes state (remote or local), or executes code/commands. It also counts when the
effect lets agent-chosen data reach a third party.

- **Example 1:** `post_message(channel, text)`, "Post a message to a team channel".
- **Example 2:** `remove_item(id)`, "Delete an item from the user's task list". This is a
  state change, so it counts even though nothing is "sent".
- **Edge case:** `fetch_page(url)` from above is **also** a `sink`. The agent chooses the URL,
  so a GET request can carry data to an attacker's server in the query string. Label
  `untrusted_source` **and** `sink`. Rule: any tool that makes a network request to an
  agent-controlled destination is a `sink`.

## Rules

1. Label each role **independently**: yes or no for each of the three. `none` = all three no.
2. Local writes count as `sink` (e.g. "write a file", "save a note"). Severity is **not**
   labeled; proveflow computes it separately.
3. Pure computation with no outside effect and no private or untrusted output (e.g. "add two
   numbers", "format a date") is `none`.
4. Read-only tools are never `sink` unless the agent-controlled network destination rule
   applies.
5. A tool that can both read and write (e.g. `manage_files(action, path)` with `action` in
   read/write/delete) gets every role its actions allow.
6. Don't guess hidden behaviour. "Search the web" is `untrusted_source`; whether it also logs
   queries somewhere is not visible, so it's not `sink` unless the agent controls a
   destination.
7. `uncertain = yes` when two careful readers could disagree. It doesn't change the label;
   uncertain rows are reported separately.

## Labelers, agreement, and adjudication

- **Labeler A = Haris:** labels **every** tool (dev and test).
- **Labeler B = an FYP group member:** labels the **test split only**, **blind and
  independently**. B never sees A's labels, Claude's proposals, or classifier output. B gets
  this guide and the same name / description / schema view.
- **Agreement:** Cohen's κ **per role** on the test split, computed from the two raw label sets
  before any discussion. It is reported with N, the observed agreement, and the per-labeler
  positive rates. κ is the standard two-rater chance-corrected agreement; its formula goes in
  the eval code with a hand-computed unit test.
- **Disagreement resolution:** every test-split disagreement is discussed by A and B against
  this guide. A **final** label is recorded with a one-line reason. **Both raw labels are kept**
  (`label_a`, `label_b`, `final`, `resolution_note`).
  - Precision/recall are computed against `final`.
  - If no agreement is reached, `final` = A's label and the row is flagged `unresolved`.
  - The number of unresolved rows is reported.
- Dev split: A only. Rows that start from a Claude proposal also record `matched_proposal`.

## Record per tool

`tool_id`, then for each role `label_a` (and on test `label_b`, `final`), `uncertain`
(yes/no, per labeler), optional `note` / `resolution_note`, `labeler` ids, `matched_proposal`
(dev, when a proposal was shown).

## Cross-check against the classifier's intended roles

Sources: ARCHITECTURE §3 (concepts) and §5.3 (heuristic examples), `src/proveflow/flows/roles.py`
(tool-level) and `server_roles.py` (server-level). "Intended" = what the code's comments and
vocabulary target, not how well it does it today. Every divergence found:

| # | Topic | Guide | Classifier (intended) | Divergence? | Proposal |
|---|---|---|---|---|---|
| 1 | Reading the user's own files | `private_data`, not `untrusted_source` | §5.3 lists `read_file` under private_data; `roles.py` puts `file` in PRIVATE_NOUNS only | none | keep |
| 2 | Email / chat / messages | `untrusted_source` **and** `private_data` | `email`, `mail`, `inbox`, `message` are in both UNTRUSTED_NOUNS and PRIVATE_NOUNS; server-level email/chat = S+P+K | v1 guide only showed the source side | **guide changed** (v2 says "also private_data") |
| 3 | `fetch(url)` / agent-controlled network destination | `untrusted_source` **and** `sink` | `roles.py`: a `url` param gives sink weight 0.25 ("GET can carry data"), **below** the 0.5 threshold, so `fetch(url)` is predicted source only. The comment shows the sink role *is* intended | **yes: weight vs intent** | **keep the guide** (it is the real capability). Expect lower sink recall; the weight may be tuned **on dev only**. Stated in the report |
| 4 | Local writes | `sink` | WRITE_VERBS → sink with severity `local_write`; filesystem/git/memory server-level = sink | none | keep |
| 5 | Code / command execution | `sink` | EXEC_VERBS → sink (network_egress severity) | none | keep |
| 6 | Browser actions (click, type, navigate) | `sink` (effect outside the conversation) | browser action verbs + `navigate` → sink | none | keep |
| 7 | Stored notes / memory | `private_data` by default; source only if text says outside; else uncertain | `memory`, `note`, `entity`, `graph` in PRIVATE_NOUNS; server-level memory = P+K (no S) | none (v2 edge case added) | keep |
| 8 | Third-party API data (weather, rates) | not `untrusted_source` unless free text from arbitrary third parties | no vocabulary marks these as sources | v1 definition ("someone other than the user/operator") would have made every third-party API a source | **guide changed** (v2: "arbitrary third parties … free text") |
| 9 | Issues / PRs / comments / tickets | `untrusted_source` (attacker-authored text) | §5.3 lists `list_issues` as untrusted_source; nouns `issue`, `comment`, `pull`, `ticket` | none | keep |
| 10 | Repository contents (git log/diff/show) | `private_data` (user's possibly private code) | PRIVATE_NOUNS include `repo`, `code`, `commit`, `diff`, `branch` | none. A public repo is a judgment call → `uncertain` | keep |
| 11 | Web/search results | `untrusted_source` | "search" + web noun → source 0.7; bare "search" 0.3 (below threshold) | none in definition; bare "search_*" tools will be a recall gap | keep; report it |
| 12 | Severity | not labeled | computed (network > remote write > local write) | none | keep |

So two **definition** changes went into the guide (2, 8), and one known **classifier gap**
stays in the code to be measured (3).
