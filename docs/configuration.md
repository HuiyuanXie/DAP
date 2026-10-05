# Configuration and development guide

DAP is a beta prototype. Python 3.9+ is sufficient; all runtime code uses the standard library.

## Local configuration

Copy `.env.example` to `.env` if you do not already have a settings file. `.env` is ignored by Git. Environment variables take precedence over the file, including aliases. A new live society rereads configuration; restart the server after changing Python source.

### OpenAI defaults

```dotenv
OPENAI_API_KEY=your-openai-key
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
API_STYLE=responses
THINKING=default
REASONING_FORMAT=auto
MAX_OUTPUT_TOKENS=1800
```

Use your OpenAI API key. `API_KEY` is also accepted; `OPENAI_MODEL` and `OPENAI_BASE_URL` are legacy aliases. Generic names take precedence if both forms are present at the same source level. The browser's model field or CLI `--model` overrides `MODEL`.

`BASE_URL` can be an HTTPS API root or a complete endpoint. The matching `/responses` or `/chat/completions` suffix is added once. Endpoint/protocol conflicts are reported locally. Credentials, query parameters, and fragments cannot be embedded in the base URL.

The Responses client uses schema-constrained output via `text.format`. Chat Completions requests a JSON object and validates it locally against the agent schema. Model support can differ. See [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

## Thinking controls

`THINKING=on`, `off`, or `default` is shared across providers. `enabled` and `disabled` remain accepted aliases. `default` omits reasoning parameters. There is no model-name inference.

| API / adapter | `REASONING_FORMAT` | On | Off |
|---|---|---|---|
| Responses | `auto` or `reasoning` | `reasoning.effort` = configured effort or `low` | `reasoning.effort=none` |
| OpenAI-style Chat | `auto` or `reasoning_effort` | `reasoning_effort` = configured effort or `low` | `reasoning_effort=none` |

`REASONING_EFFORT` applies while thinking is on. Accepted levels depend on the actual model. Set `THINKING_OFF_SUPPORTED=false` for a model that does not accept fully disabling reasoning; off then fails locally. The client never substitutes positive effort for an off request.

`MAX_OUTPUT_TOKENS` controls the response budget, including reasoning where the API counts it. It defaults to 1,800 and accepts 1–65,536, subject to the provider's own limits. Thinking runs may need a larger budget, such as 8,192. OpenAI-style chat uses `max_completion_tokens`.

See [OpenAI reasoning](https://developers.openai.com/api/docs/guides/reasoning) for model-specific support.

## Commands

Start the dashboard:

```sh
python3 app.py
```

Run an offline comparison or a live run:

```sh
python3 app.py --cli --mode demo --setting bounded --rounds 4
python3 app.py --cli --mode demo --setting constitutional --rounds 4
python3 app.py --cli --mode demo --setting fixed --rounds 4
python3 app.py --cli --mode demo --no-communication
python3 app.py --cli --mode openai --rounds 1
```

The CLI value `--mode openai` selects live API mode. Runs are limited to 1–10 rounds in the engine, HTTP API, CLI, and browser.

A live connectivity check sends one request; the second command also runs one bounded round:

```sh
python3 smoke_test.py
python3 smoke_test.py --round
```

These calls use the configured provider and may incur charges. No live call is part of the offline tests.

## Outcomes, costs, and failures

A round uses three calls when parliament is not consulted, four when it recommends no change, six to eight for an operational proposal, and up to ten for a foundational amendment. Actual usage depends on votes and communication. Traces and generated outputs are ignored by Git.

External harm labels are evaluated from simulator records and are not inserted into agent contexts. Current-law labels are separate. A new operational law takes effect in the next round; a foundational amendment affects subsequent actions. The final round is complete only after its decisions have finished.

HTTP 401 generally indicates a key problem; 429 can indicate rate limits or quota. HTTP 400 can indicate incompatible model, reasoning, JSON, or token-limit parameters. Incomplete responses stop the run. Review the saved partial trace, adjust the configuration, and start a new society. Error messages avoid returning provider bodies that could contain credentials. There are no automatic paid retries or model fallbacks.

## Offline tests and code layout

```sh
python3 -m unittest discover -s tests -v
```

Tests cover authority boundaries, voting, prospective laws, communication, fixed external outcomes, round limits, completion state, configuration, both request protocols, and failure handling. CI runs the same offline suite.

| File | Purpose |
|---|---|
| `app.py` | Local HTTP server and CLI |
| `dap/simulation.py` | Agent roles, scenarios, demo decisions, laws, evaluation, and round limit |
| `dap/config.py` | Configuration, aliases, endpoint and reasoning parameters |
| `dap/provider.py` | Live API client; `APIProvider` with an `OpenAIProvider` compatibility alias |
| `web/index.html` | Browser dashboard without external dependencies |
| `smoke_test.py` | Explicit live connectivity and single-round checks |
| `tests/` | Offline regression tests |

Keep `.env`, credentials, and generated traces out of source control. Before publishing changes, review the staged file list and run the offline suite. Research design and planning documents are maintained separately from this code repository.
