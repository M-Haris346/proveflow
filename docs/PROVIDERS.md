# LLM providers (Phase 5)

**Exercised by hand: none.** No provider below has been run with proveflow. A row moves to
"exercised" only after a manual run (`python -m proveflow.runner.manual … --yes`) whose
transcript passed the D7 checks, with the provider, model and date. Nothing here is a claim
of support.

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
