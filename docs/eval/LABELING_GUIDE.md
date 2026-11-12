# Labeling guide for tool roles (DRAFT, for Haris's approval before any label exists)

> You label each tool against this guide. Labels are the ground truth for the classifier's
> precision/recall, so they must not depend on proveflow's heuristics.
>
> **All examples below are invented, generic tools. None of them comes from the eval set**, so
> the guide does not leak test-split content. Written 2026-11-12, before any tool was
> collected for the eval.

## What you look at

Only what an agent sees: the tool **name**, **description**, and **input schema** (parameter
names, types, descriptions). Do not use the server's source code, its README, or what you
remember about the server. If the visible text is ambiguous, label what a careful reader would
conclude and set `uncertain = yes`.

## The three roles (independent: a tool can have 0, 1, 2 or 3)

### `untrusted_source`

Its **output can contain text written by someone other than the user and the operator of the
agent**, i.e. content an attacker could have placed there for the agent to read.

- **Example 1:** `fetch_page(url)`, "Download a web page and return its text". Web pages
  are written by anyone.
- **Example 2:** `list_inbox(folder)`, "List received emails with subject and body". Senders
  are third parties.
- **Edge case:** `read_document(path)`, "Read a file from the user's documents folder".
  Label it **not** `untrusted_source` by default: it is designed to return the user's own
  files. Label it `untrusted_source` only if the visible text says the content comes from
  outside (e.g. "attachments", "downloads", "shared with you", "uploaded by customers").

### `private_data`

Its **output can contain data the user would not want disclosed to third parties**: personal
or company files, database rows, messages, contacts, calendar entries, credentials, notes,
private repository contents, account details.

- **Example 1:** `query_orders(sql)`, "Run a read-only SQL query on the orders database".
- **Example 2:** `get_events(date)`, "Return the user's calendar events for a day".
- **Edge case:** `get_exchange_rate(currency)`, "Current public exchange rate". **Not**
  `private_data`: public reference data, even though it comes from a service. In general,
  label `private_data` only if the tool can return data *about or belonging to* the user or
  their organization.

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
4. Read-only tools are never `sink` unless rule "agent-controlled network destination"
   applies.
5. A tool that can both read and write (e.g. `manage_files(action, path)` with `action` in
   read/write/delete) gets every role its actions allow.
6. Don't guess hidden behaviour. "Search the web" is `untrusted_source`; whether it also logs
   queries somewhere is not visible, so it's not `sink` unless the agent controls a
   destination.
7. `uncertain = yes` when two careful readers could disagree. It doesn't change the label;
   uncertain rows are reported separately.

## Record per tool

`tool_id`, `untrusted_source` (yes/no), `private_data` (yes/no), `sink` (yes/no),
`uncertain` (yes/no), optional one-line `note`, and `labeler` (`haris`). Dev-split rows that
start from a proposal by Claude also record `matched_proposal` (yes/no). Test-split rows are
labeled blind: no proposal and no classifier output is shown.
