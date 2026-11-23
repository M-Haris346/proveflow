# LLM providers (Phase 5)

**Exercised by hand: one run.** A provider is listed here only after a manual run
(`python -m proveflow.runner.manual … --yes`) whose transcript passed the D7 checks, with the
provider, model and date. One run is a record, not a claim of support.

| Provider | Model | Date | Scenario | Outcome | Evidence |
|---|---|---|---|---|---|
| Groq | `openai/gpt-oss-120b` | 2026-11-21 | `clean_utility` (no attack) | final_answer, utility true, compromised false, 3180 in + 168 out | `evidence/provider-runs/groq-gpt-oss-120b-2026-11-21/` |

Ollama and Gemini: not exercised.

## A documented model id is not a guarantee (first run, 2026-11-21)

Groq's docs name `llama-3.3-70b-versatile`. On the key holder's account it returned HTTP 404,
while `/models` returned 200 with the same key. Auth was fine; the MODEL was absent from that
account. The account listed `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `qwen/qwen3.8-27b`,
`allam-2-7b` and several non-chat models (whisper, orpheus, prompt-guard). Model
availability is PER ACCOUNT and changes over time. So:
- a manual-run brief STARTS by listing the account's own models (`GET <base_url>/models`, run
  by the key holder), and the model is chosen from that list, not from the docs;
- `/models` returning 200 proves auth only. It does not prove that any particular model can
  be called.

## A guessed response shape is not evidence (first run, 2026-11-21)

Before the first run, a probe used a made-up tool-call id (`call_` plus 20 letters and
digits), and the D7 shape scan did not flag it. Real Groq returns `fc_<uuid>`. That is
UUID-shaped, and D7 DID flag it, at five paths:
`llm_response.body.choices[].message.tool_calls[].id` (where the provider mints it),
`tool_call.call_id`, `tool_result.call_id`, `llm_request.body.messages[].tool_calls[].id` and
`llm_request.body.messages[].tool_call_id` (where the runner echoes it). A probe built on a
guessed shape tests the guess, not the provider. This is why the manual run is the test
rather than a formality. By ruling, all five are D7 `STRUCTURAL_PATHS`: a provider-minted
correlation id, the same class as the completion id. The four echo paths hold values
proveflow constructs, so their exclusion holds only together with the echo check: every
value there must equal an id an earlier `llm_response` minted ("request carries a
tool_call_id no response minted" otherwise).

One client covers every OpenAI-compatible chat-completions endpoint (`runner/llm.py`, over
`httpx2`, no LiteLLM). It sends the same request body to every provider: `model`,
`messages`, `temperature`, `max_tokens`, `tools` (when any), and `seed` only when the
provider's config says `send_seed`. It never sends `tool_choice` ("auto" is the documented
default when tools are present, and Ollama lists `tool_choice` as unsupported), `n`,
`logprobs` or `messages[].name`. `http://` is accepted only for a loopback host.

## What the official docs say (fetched 2026-11-19)

| | Groq | Ollama | Gemini |
|---|---|---|---|
| Base URL | `https://api.groq.com/openai/v1` | `http://localhost:11434/v1/` (local) | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| Auth | `Authorization: Bearer $GROQ_API_KEY` | "The client requires an API key value, but Ollama ignores it" (local) | `Authorization: Bearer $GEMINI_API_KEY` |
| `tools` | yes, "A max of 128 functions" | yes | yes ("Function calling") |
| `tool_choice` | yes | **not supported** | not stated |
| `seed` | yes: "best effort … Determinism is not guaranteed" | yes | **not mentioned** → `send_seed = false` |
| `usage` | shown in the example response | not stated | not stated (only via `stream_options.include_usage`) |
| Other | `temperature: 0` "converted to `1e-8`"; 400 for `logprobs`, `logit_bias`, `top_logprobs`, `messages[].name`, `n` ≠ 1 | — | compatibility "still in beta" |

Sources: [Groq OpenAI compatibility](https://console.groq.com/docs/openai),
[Groq tool use](https://console.groq.com/docs/tool-use),
[Groq API reference](https://console.groq.com/docs/api-reference),
[Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility),
[Gemini OpenAI compatibility](https://aistudio.google.com/docs/openai) (redirect target of
ai.google.dev/gemini-api/docs/openai). No page showed a last-updated date.

Function names: "Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum
length of 64" (OpenAI OpenAPI spec, `openai/openai-openapi` `openapi.yaml`,
`FunctionObject.name`). A tool name outside that rule is refused by `runner/routing.py`,
never renamed. Groq's reference states no rule of its own.

## Token counts are provider-reported (F10)

`tokens_in`/`tokens_out` are read from the response's `usage.prompt_tokens` /
`usage.completion_tokens`. The caps and the run budget are enforced on these
provider-reported counts, not on anything proveflow measures. A response without integer
counts ends the trial (`usage_missing`). For Ollama and Gemini the docs do not state that
chat completions return `usage`; if they do not, every trial with them ends `usage_missing`.
That is unverified until someone runs it.

## 429 and Retry-After (Phase 6 step 2; fetched 2026-11-23)

These are HTTP standard facts, not provider-specific ones; no provider's own rate-limit
documentation is relied on, and provider limits are not modelled.

- RFC 6585 s4 "429 Too Many Requests" (https://www.rfc-editor.org/rfc/rfc6585.html): the
  response "MAY include a Retry-After header indicating how long to wait before making a new
  request."
- RFC 9110 s10.2.3 "Retry-After" (https://www.rfc-editor.org/rfc/rfc9110.html):
  `Retry-After = HTTP-date / delay-seconds`, `delay-seconds  = 1*DIGIT`, and "A
  delay-seconds value is a non-negative decimal integer, representing time in seconds."

What proveflow does with it (`runner.campaign.wait_for`, `retry_after_s`):
- A 429 ends the attempt (`rate_limited`); it is never retried inside a trial.
- Only the numeric delay-seconds form is read; the HTTP-date form is ignored (it needs a
  clock comparison proveflow does not make), as are garbage, an absent header, and a value
  above `RETRY_AFTER_MAX_S` (600, a design value).
- The wait is `max(proveflow's own backoff, Retry-After)`: honouring the header can only
  lengthen the wait, never shorten it, which is why no provider-specific documentation is
  needed to act on it.
- The header text (at most 64 printable ASCII characters) and which of the two decided the
  wait are recorded on the attempt in the campaign state file. Retry-After is the ONLY
  response header proveflow ever reads; it is never put in a transcript or an error message.

## Committing a manual run

A real run's transcript is EVIDENCE, committed under `evidence/provider-runs/<provider>-<model>-<date>/`
with its `scenario.json` and a `README.md`, never under the replay fixtures
(`evidence/provider-runs/README.md`). Two independent checks must pass first:
- the exact-key check: the real key, in any of the matcher's 10 encodings, appears in no file
  of the run's output directory (`exact_key_hits`; prints file names only);
- the evidence check: the hash chain plus the D7 shape scan
  (`tests/safety/test_transcript_layers.py`). D7 skips only the exact paths in
  `STRUCTURAL_PATHS`: chain hashes, the provider's completion id `llm_response.body.id`, and
  the five tool-call id paths above, whose four echo paths must pass the echo check. Any
  other field that trips D7 goes to a ruling, never into that set by itself.

`python -m proveflow.runner.manual` refuses an existing `--out-dir` (one line, exit 2), so a
re-run never overwrites or mixes with an earlier run's output.
