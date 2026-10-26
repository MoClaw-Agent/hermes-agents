# Authoring & Verifying a Hermes Plugin

A plugin is a directory `~/.hermes/plugins/<name>/` containing `plugin.yaml`
and an `__init__.py` that exposes `register(ctx)`. It never modifies Hermes
core.

## The trap: a plugin can load, log success, and be completely inert

`register(ctx)` runs inside a `try/except` in most shim designs. If the code
that does the real work raises, the shim catches it and registers a no-op
fallback so the plugin still "loads" — the log shows the plugin registering a
hook, and nothing is actually wired. **A plugin that loads is not a plugin that
works.** After every install or edit, verify the two log lines that prove work
happened, not the one that proves loading happened:

```bash
grep -a -n "register() called\|shim unavailable\|registered .* tools under toolset\|registered pre_llm_call" \
  ~/.hermes/logs/agent.log | tail -20
```

`register() called` alone means nothing. You want the tool-registration line and
the absence of a `shim unavailable` / fallback warning. Treat any fallback
message as a hard failure to fix, not a graceful degradation to accept.

Rules that follow:

- **Make the fallback loud and specific.** Log the exact path or symbol that was
  missing (`log.warning("shim missing at %s", path)`). A bare "unavailable"
  costs a full debugging session.
- **Never swallow the real error.** Catch narrowly around the optional part; let
  a genuine import/registration failure surface.
- **Re-check the log after every install.** Registration failures are silent to
  the user — no error, no tool, just a memory feature that never activates.

## Path resolution: the plugin dir is not the project dir

A shim that loads project code via a path relative to `__file__` resolves
against the **plugin directory**, not the project. From
`~/.hermes/plugins/<name>/`, `.parent.parent` is `~/.hermes` — not the repo, and
not `$HERMES_HOME` either when a profile is active.

- Resolve the project location from explicit config (`ctx.get_config(...)`), an
  env var, or a recorded absolute path written at install time. Never derive it
  from the plugin directory's depth.
- Print the resolved path in the failure message so the mismatch is visible.
- When a plugin wraps a checkout that moves, prefer an install step that records
  the path over one that guesses it.

**Resolving the path is only half the job — the checkout must also be
importable.** The plugin loader does not add the project directory to
`sys.path`. A project module that imports its own package (`from core.config
import MemoryConfig`) therefore still dies with `ModuleNotFoundError` once the
path is correct, and the shim's `except` turns that into the same silent
fallback. Prepend the resolved root to `sys.path` *before* executing the project
module:

```python
root = str(repo_root)
if root not in sys.path:
    sys.path.insert(0, root)
spec = importlib.util.spec_from_file_location("my_plugin_integration", module_path)
```

Both halves must be fixed together; fixing one leaves the plugin inert with a
different log line.

## Registration surfaces

```python
ctx.register_tool(name=..., toolset=..., schema=..., handler=..., description=...)
ctx.register_hook(hook_name, callback)          # hook_name must be in VALID_HOOKS
ctx.register_cli_command(name, help, setup_fn, handler_fn)
ctx.get_config(key, default) / ctx.set_config(key, value)
```

- **Gate:** a standalone user plugin with no `kind` is only loaded when its key
  appears in `plugins.enabled` in `config.yaml`. Enabling is a separate step
  from installing the directory.
- **Tool handlers** take `(args: dict, **kw) -> str` and must return a JSON
  string. Return errors as `{"error": "..."}`; do not raise.
- **Validate arguments in the handler.** `int(args.get("id"))` on a missing key
  raises `TypeError`, which the handler's own `except` converts into an
  unhelpful error string the model cannot act on. Use small `_required_int` /
  `_optional_int` helpers that raise a clear message (`"id is required"`,
  `"limit must be an integer, got 'x'"`) so a bad call returns an actionable
  tool error instead of a stack-trace fragment.
- **`schema["name"]` must match the registered `name`.** The host passes the
  name as a separate argument, so a schema carrying a blank or stale name can
  pass registration and still break anything downstream that reads it. Derive
  the schema name from the same value you register with — one helper that stamps
  it, called by every registration, rather than a literal repeated per tool.
- **`provides_tools` / `provides_hooks` in `plugin.yaml` must list exactly what
  the code registers.** The manifest is validated against the real registrations,
  so a manifest advertising a tool the plugin deliberately never registers (or
  omitting one it does) is a validation failure, not a harmless over-declaration.
  Keep one module-level tuple of tool names as the single source of truth and let
  tests assert the manifest matches it.
- Use a dedicated `toolset` name to avoid collisions with bundled plugins.

## `ctx.llm` — run a completion on the user's ACTIVE model

`ctx.llm` is a `PluginLlm` bound to the plugin's identity. It runs against
whatever model and provider the user is already using, so a plugin needing an
LLM (classification, extraction, summarisation) needs no second model to
configure, pull, or keep warm:

```python
result = ctx.llm.complete_structured(
    instructions="Extract durable facts from this turn. Return JSON.",
    input=[{"type": "text", "text": turn}],
    json_schema=SCHEMA, json_mode=True, schema_name="my_task",
    temperature=0, purpose="myplugin extraction",
)
result.parsed    # dict when JSON was parsed; None if the provider ignored the schema
result.text      # raw assistant text
result.model, result.provider, result.usage
```

- **Trust gates apply only to OVERRIDES.** Passing `provider=`, `model=`,
  `agent_id=`, `profile=`, or a built-in `task=` raises `PluginLlmTrustError`
  unless the operator sets the matching
  `plugins.entries.<id>.llm.allow_*_override` (plus an `allowed_*` allowlist).
  Calling with **no overrides needs no config at all** — it just uses the active
  model. Only request an override when a specific one is genuinely required.
- **Catch `PluginLlmTrustError` (a `PermissionError`) and degrade.** An
  LLM-backed feature must never break a turn because of a config gate: log the
  exception class and return the empty result.
- **`result.parsed` is `None` when the provider ignored `response_format`.** Fall
  back to `json.loads(result.text)` before giving up, or a schema-blind provider
  silently yields nothing.
- Async siblings exist: `acomplete` / `acomplete_structured`.
- **Pass the `llm` handle as a constructor parameter.** `ctx.llm` is an
  `PluginLlm` instance, not a module-level function. Thread it from the hook
  into the orchestrator: `Orchestrator(llm=ctx.llm)` → `Backend(llm=...)`.
  A backend that tries to `import agent.plugin_llm` and probe for functions
  will silently find nothing.

## Privacy gates belong INSIDE the writing function

A call-site guard is a convention, not an enforcement. If the function that
writes user text checks the flag itself, a future caller cannot bypass it by
forgetting to check at the call site:

```python
def _write_if_enabled(store, ctx, session_key, messages):
    if not _privacy_enabled(ctx):   # <-- gate is HERE, not at the call site
        return 0
    ...
```

Rules:

- **The function that writes data owns the gate.** Never rely on every caller
  to remember the check.
- **Read the gate at call time**, not at import time, so a config edit takes
  effect without a reload.
- **Bound the input tail.** The host passes the entire transcript (observed at
  848 entries). Only examine the last N entries.
- **Filter roles by trust.** Only `user` and `assistant` are conversation;
  `system` prompts and `tool` output are never persisted.
- **Redact secrets before the write**, honouring the redaction flag.
- **Deduplicate on write** so a replayed turn is a no-op.

## When testing orchestrator wiring, PIN the backend

`refresh_backend()` rebuilds the backend from config/env, discarding any
double injected after construction. If you need to observe whether a method
was called:

```python
orch._backend = _FakeBackend()
orch._backend_pinned = True   # <-- prevents refresh from discarding the fake
orch.propose_from_turn(...)
assert called == 1
```

Without the pin, the fake is silently replaced and the test fails with a
confusing `assert 0 == 1`.
- **Pass the `llm` handle as a constructor parameter.** `ctx.llm` is an
  `PluginLlm` instance, not a module-level function. Thread it from the hook
  into the orchestrator: `Orchestrator(llm=ctx.llm)` → `Backend(llm=...)`.
  A backend that tries to `import agent.plugin_llm` and probe for functions
  will silently find nothing.

## Privacy gates belong INSIDE the writing function

A call-site guard is a convention, not an enforcement. If the function that
writes user text checks the flag itself, a future caller cannot bypass it by
forgetting to check at the call site:

```python
def _write_if_enabled(store, ctx, session_key, messages):
    if not _privacy_enabled(ctx):   # <-- gate is HERE, not at the call site
        return 0
    ...
```

Rules:

- **The function that writes data owns the gate.** Never rely on every caller
  to remember the check.
- **Read the gate at call time**, not at import time, so a config edit takes
  effect without a reload.
- **Bound the input tail.** The host passes the entire transcript (observed at
  848 entries). Only examine the last N entries.
- **Filter roles by trust.** Only `user` and `assistant` are conversation;
  `system` prompts and `tool` output are never persisted.
- **Redact secrets before the write**, honouring the redaction flag.
- **Deduplicate on write** so a replayed turn is a no-op.

## When testing orchestrator wiring, PIN the backend

`refresh_backend()` rebuilds the backend from config/env, discarding any
double injected after construction. If you need to observe whether a method
was called:

```python
orch._backend = _FakeBackend()
orch._backend_pinned = True   # <-- prevents refresh from discarding the fake
orch.propose_from_turn(...)
assert called == 1
```

Without the pin, the fake is silently replaced and the test fails with a
confusing `assert 0 == 1`.

## Never guess a host API surface — read the host's source

A plugin that calls a host API by an assumed name fails silently under a broad
`except`, which reads as "the feature does nothing" rather than "that symbol does
not exist". Measured: an extraction backend probed `agent.plugin_llm` for
module-level `llm_call` / `call` / `complete` / `generate` — none of which exist;
that module's surface is the `PluginLlm` **object** on `ctx.llm`. The backend had
shipped through a whole phase without ever being able to produce one result, and
nothing errored.

- **Read the host module before writing the call.** For a `ctx.*` surface the
  contract is on `PluginContext` in the plugin manager plus the class it returns;
  `grep -n "^class \|    def <method>" <host module>` settles the real names in
  one step.
- **Do not probe for a name at runtime.** A loop over candidate names
  (`for n in ("call", "complete", ...)`) hides the mismatch instead of surfacing
  it — it silently finds nothing and the feature degrades to a no-op.
- **Take the handle as a parameter; do not import it.** `ctx.llm` is an instance,
  not a module-level function, so the object must be threaded from the hook into
  whatever needs it (`Backend(llm=ctx.llm)` / `Orchestrator(..., llm=...)`). A
  backend that tries to import the surface cannot work at all.

## Driving Hermes internals from a standalone probe

To exercise a host API (e.g. `ctx.llm`) outside a live turn, run the script under
the **same interpreter Hermes uses** and import `hermes_bootstrap` FIRST:

```python
import sys
sys.path.insert(0, "/path/to/hermes-agent")
import hermes_bootstrap          # puts Hermes's dependency tree on sys.path
from agent.plugin_llm import PluginLlm
llm = PluginLlm(plugin_id="myplugin")   # same trust policy the plugin sees
```

- **Get the interpreter from `hermes --print-runtime-command`** (a JSON argv
  list; element 0 is the python). The runtime interpreter is *not* the workspace
  venv and the two carry different dependency trees, so a probe that works in one
  and not the other is testing a different environment, not a different code path.
- **`hermes_bootstrap` is what makes host imports resolve.** Without it a host
  module that lazily imports a Hermes dependency fails with
  `ModuleNotFoundError` deep inside the call — which looks like a bug in the API
  being probed rather than a missing path setup. Import it before any `agent.*`
  or `hermes_cli.*` import.
- **Confirm the probe ran the real thing**: assert a non-empty result (a real
  completion, a real candidate list) rather than "no exception", since every
  failure path in this class is designed to degrade quietly.

## `pre_llm_call` — actual kwargs

Hermes calls the hook with **keyword** arguments:

```
session_id, task_id, turn_id, user_message, conversation_history,
is_first_turn, model, platform, parent_session_id, sender_id,
telemetry_schema_version
```

- **There is no `recent_turns` parameter.** A callback declaring one receives
  `None` forever, and because most callbacks also declare `**kwargs` the real
  `conversation_history` is swallowed silently — the query-window logic never
  runs. Read `conversation_history` (a list of `{"role", "content",
  "timestamp"}` dicts). Verify a hook's declared parameters against this list
  before trusting any behaviour that depends on them.
- **Return contract:** `{"context": "..."}` or a non-empty `str` to inject;
  `None` to inject nothing. The context is appended to the **user message**,
  never the system prompt.
- **Fail open:** a hook that raises is reported and skipped. Return `None` on
  failure instead of propagating.
- **The host already bounds the hook** — `plugins.hook_callback_timeout`
  (default 30s) wraps bounded hooks including `pre_llm_call`. A plugin-side
  timeout setting is decorative unless the plugin itself enforces it; do not
  claim a timeout budget the code does not implement.

## `on_session_end` — fires per TURN, and carries no transcript

```
session_id, task_id, turn_id, completed, failed, interrupted,
turn_exit_reason, model, platform
```

Despite the name, this plugin hook fires at the **end of every turn**, not at a
real session boundary (`agent/turn_finalizer.py`), and it carries **no messages
or transcript**. Do not write an extraction/summarisation hook that reads
`messages` from it — that parameter is only on the *memory-provider* method of
the same name, which is a different surface. Read the fire site before relying
on a hook's name to imply its payload.

When the work needs the transcript and the end-of-turn trigger, split it across
two hooks:

- `pre_llm_call` **buffers** the turn; it is the hook that actually receives the
  transcript.
- `on_session_end` **drains** the buffer and does the work.

**Buffer the turn's own text, not `conversation_history`.** The host passes the
**entire transcript** on every call — measured at 848 entries in a live session —
so appending `(user_message, conversation_history)` per turn grows the buffer
without bound in a long session. It also silently multiplies the work: any
consumer that iterates the history re-extracts every prior turn on each turn,
which showed up as candidates scraped out of the assistant's own earlier prose.
Append `user_message` alone, dedupe identical text, cap the list, and hand the
consumer a synthetic single-turn history:

```python
buf = _turn_buffers.setdefault(session_key, [])
if user_message not in buf:
    buf.append(user_message)
del buf[: max(0, len(buf) - 50)]
```

Clear the buffer in a `finally` so a failure cannot leak it into the next turn,
and log the count at drain time (`buffered_turns=%d`) — a zero there is the
fastest way to tell "fired but buffered nothing" from "never fired".

## Register every declared hook unconditionally

Register the hook at `register()` time and check the enable-switch **inside** the
callback, rather than wrapping `register_hook` in an `if`. Two reasons:

- `hermes plugins validate` checks `provides_hooks` against what `register()`
  actually registered. A hook registered only when a setting is on produces a
  `declares X but register() did not register them` warning on every run with the
  setting off.
- Toggling the setting then needs no plugin reload, and the callback returns
  immediately when disabled so the turn path pays nothing.

## One switch, one source of truth — DERIVE, do not overlay

A plugin commonly reads a switch from `ctx.get_config(...)` while the core it
calls reads the same switch from a config file. When those two disagree the
plugin decides the feature is on, registers its hook, and then the core checks
its own copy, sees it off, and does nothing — the feature is wired and inert with
no error anywhere.

**For an installed plugin, `ctx.get_config` returns the default for every key.**
Plugin settings live in `plugins.entries.<id>.settings.*` and are empty unless
the operator set them, so a gate that reads *only* `ctx.get_config` sees nothing
and silently resolves to off. There are typically **three** sources for one
switch: plugin settings, the checkout's config file, and an env override.

**Overlaying at each call site is the approach that fails.** Patching one
direction leaves the other broken, and the defect recurs in mirror image: the
plugin reads plugin-settings while the core reads the config file (feature on in
one, off in the other); then the plugin reads *only* plugin-settings so it cannot
see `enabled: true` in the config file at all. Measured: three successive fixes
in one session, each correct for one direction and each leaving the other.

Make **one** function resolve the switch and have every other consumer derive
from it, so disagreement is impossible by construction rather than by discipline:

```python
def _feature_config(ctx) -> Config:
    """The ONLY place the switch is resolved. Precedence: env > plugin settings > config file."""
    cfg = Config()
    for key in ("enabled", "verify_evidence", ...):
        v = ctx.get_config(f"feature.{key}", None)
        if v is not None:
            cfg.set(f"feature.{key}", v)
    raw = env_str("MYPLUGIN_FEATURE_ENABLED", "").strip().lower()
    if raw:
        cfg.set("feature.enabled", raw in ("1", "true", "yes", "on"))
    return cfg

def _feature_enabled(ctx) -> bool:
    return bool(_feature_config(ctx).get("feature.enabled", False))   # derived, never re-read
```

Pin it with an invariant test over **all** combinations of the three sources,
asserting the gate and the config the core reads always agree — a single-case
test passes for each broken variant:

```python
for settings in ({}, {"feature.enabled": False}, {"feature.enabled": True}):
    for env_value in (None, "true", "false"):
        ...
        assert _feature_enabled(ctx) == bool(_feature_config(ctx).get("feature.enabled"))
```

State the precedence in a comment, and route every construction of the config
object through the one helper — a second construction path (a CLI command
building its own config, a hook rebuilding it per turn) reintroduces the
disagreement for that path only, so the feature works from the tool surface and
not from the hook, or vice versa.

Related: a `.env` loader that resolves its file with `Path.cwd()` finds nothing
when the plugin runs under Hermes, whose cwd is not the checkout. Resolve `.env`
from `__file__` (or an explicit configured path) as well as cwd.

Also related: `env_str` reads `os.environ` **before** the `.env` file, so a
variable exported in the shell overrides an edited `.env`. Editing `.env` to
flip a switch then appears to do nothing.

**`os.environ` cannot witness whether a value was exported — the loader put it
there.** A `.env` loader injects file values *into* `os.environ`, so by the time
you inspect a key it is indistinguishable from a genuine export. Measured: an
agent read its own injected value back, concluded an external variable was
shadowing the file, and told the user so; nothing was exported at all. Reading
`os.environ` (or `echo "${VAR:-unset}"` in the shell the plugin runs in) tests
your own mechanism, not the shell's.

Check a layer the loader does not touch before claiming an external override:
`grep -rn VAR ~/.bashrc ~/.profile ~/.zshrc ~/.config/environment.d/`, systemd
units, and `env -i HOME="$HOME" bash -lc 'echo "${VAR:-unset}"'` for a fresh
login shell. If all are empty, the value came from the file and the file is
already governing — there is nothing to unset. If a real export does exist, see
it with `env -u VAR`.

When you *do* want the file authoritative, do not simply flip the comparison:
provide a precedence switch (`MYPLUGIN_ENV_PRECEDENCE=process`) so the old
behaviour stays reachable, read that switch straight from `os.environ` and pop
it from the parsed file so the file cannot flip the rule that decides whether
the file wins, and keep a test for each direction.

## Validate the plugin, don't just grep the log

Hermes ships a validator that runs the plugin's `register()` in isolation and
checks the manifest against what was actually registered:

```bash
hermes plugins validate ~/.hermes/plugins/<name>
```

It reports per-check results, including `declared tools — matches
registrations`, `declared hooks — matches registrations`, built-in tool
collisions, and a security scan. This catches manifest/code drift and
registration failures that the log-based check below cannot see. Run it after
every install or edit; it is faster and stronger than reading the log.

A green validator does not prove the plugin is *doing* anything at runtime —
combine it with the log check that the work actually happened.

## Prove a hook FIRED with a marker; never infer it from your own output

A hook whose success path logs nothing cannot be diagnosed. Worse, the evidence
you reach for will be your own: an agent probing the hook by printing its result
has that output captured into the session transcript, and a later `grep` of
`agent.log` finds the marker string and reads it as proof of injection. It is
not — it is the probe's own output round-tripping through the transcript.

**Measured:** a `grep -a "BEGIN injected memory context" agent.log` returned a
hit, which was reported as "the hook fired". It came from this agent's own tool
result being persisted into the conversation. No hook had run.

Rules:

- **Log a content-free fire marker at the top of every hook**, before any early
  return: `log.info("%s fired (session=%s, msg_chars=%d, history=%d)", ...)`.
  Counts and ids only — never the message or the injected content. Without it,
  "did the host dispatch this?" is unanswerable from the log.
- **Put the marker before the guards**, so a hook that fires and returns early
  is distinguishable from one that never fired.
- **Prefer a durable side effect as the primary evidence.** A row written to a
  store table on each run (an `extraction_runs`-style ledger) is proof that
  survives log rotation and cannot be confused with your own output. Absence of
  such a row after a real turn means the hook did not run.
- **Before citing a log hit as evidence, ask whether your own session wrote it.**
  `grep` cannot tell you. Check the surrounding line for the probe's shape, or
  prefer a marker only the plugin itself can emit.
- **An offline probe run through the installed shim proves the code, not the
  wiring.** Drive the shim directly with realistic settings — an installed
  plugin's `ctx.get_config` returns defaults for everything, so a probe that
  passes custom settings is testing a configuration no user has. Both matter:
  the shim probe proves the code path, the fire marker proves the host calls it.
  Report them as two separate claims.

## The running process holds the OLD plugin — a missing log line means stale code

Editing the plugin files does not reload them. A long-lived Hermes process (the
gateway, the desktop app, an open CLI session) called `register()` once at
startup and keeps executing that version for its whole life, so a change can be
fully correct, fully validated, and simply not running.

The tell is a **missing** line rather than an error: after adding a hook or a
tool, its registration line never appears in `agent.log`, while the older lines
from the previous version are present from the process's start time.

```bash
grep -a "register() called\|registered .* tools\|registered .* hook" ~/.hermes/logs/agent.log | tail
```

Rules:

- **Before claiming a plugin change is live, check whether the process predates
  it.** Compare the newest registration line's timestamp against the process
  start time (`ps -o lstart= -p <pid>`) — a process started before your edit is
  running the old code no matter what the files on disk say.
- **A registration line that is absent is stale code, not a broken hook.** Do not
  debug the hook; it was never loaded. Absence of the new line across *every*
  boot in the log means no process has ever loaded that version.
- **Report the distinction explicitly.** "Verified offline and through the
  installed shim; not yet running in the live process." An offline probe must
  never read as a live success — the user is testing against the live process.
- Reloading means restarting the process. Do not restart a user's running
  session to pick up a plugin change without asking first.

## Developing an extractor pollutes its own queue — use a scratch store

A text/LLM extractor that reads the session's turns will capture **your own
explanatory prose as data**. Working on an extraction pipeline means writing
sentences that contain the extractor's trigger phrases as *examples* — "a line
like `remember this: X` becomes a candidate" — and the running plugin, watching
the same conversation, files each example as a real candidate. Measured: a
heuristic extractor's queue filled with fragments of the agent's own explanation
of the heuristic (including its own regex bounds quoted back), which then had to
be reviewed and rejected by hand.

This is distinct from the transcript-buffer over-read below (which multiplies
prior turns): here each turn is extracted once, correctly, and the *content* is
the problem.

Rules:

- **When exercising an extractor, point it at a scratch store** (a temp DB path,
  a distinct namespace) rather than the live one, so development chatter never
  reaches the real queue. Clean up afterwards rather than auditing it.
- **Do not test an extractor by talking to it in the same session it observes.**
  Drive it through its own CLI or a direct call with fixture text.
- Expect a noisy queue after any session spent discussing the extractor's
  patterns, and clean it with the provenance grouping the cleanup rule
  prescribes (`coding-workflow` principle 26) — the user's genuine statements sit
  in the same queue as the machine-written fragments.
- Prefer a backend with comprehension over a phrase matcher for real use: a
  regex extractor cannot distinguish an example of a trigger phrase from an
  instruction to remember something, so it will always capture discussion about
  itself.

## Injection hygiene

- **Build the empty case explicitly.** A renderer that appends a header and
  footer and then tests `text.strip()` is never empty, so the `return None`
  guard is unreachable and an empty store injects an empty block on every
  session. Test the *content* lists, not the assembled string.
- Label injected memory as untrusted reference data and instruct that it must
  never override system/developer instructions. Retrieved content is data, not
  commands.
- Deduplicate per session when the host re-fires the hook every turn.
- Keep failure logs content-free — never log memory content or the user message.

## CLI companions

When a plugin ships a standalone CLI, verify the real entry point dispatches.
A `main()` that calls `parser.parse_args([])` with a hardcoded empty list never
reads `sys.argv`: it returns a namespace with no handler, falls off the end, and
exits 0 having printed nothing. Tests that monkeypatch `parse_args` to return a
fake namespace pass while the CLI is dead — see the `coding-workflow` skill's
rule on tests that fake the entry point.

**Guard every subcommand, not just the one you changed.** A handler that reads an
argument its subparser never defines raises `AttributeError` on *every*
invocation, and nothing catches it because no test runs that command. Add one
test that walks the subparser choices, parses each with placeholder values, and
asserts every `args.X` the handler's source references exists on the namespace:

```python
sub = next(a for a in parser._actions if hasattr(a, "choices") and a.choices)
for name in sub.choices:
    ns = parser.parse_args([name, *PLACEHOLDERS[name]])
    assert hasattr(ns, "handler"), f"{name}: no handler"
    for ref in set(re.findall(r"args\.(\w+)", inspect.getsource(ns.handler))):
        assert hasattr(ns, ref), f"{name}: reads args.{ref}, parser never defines it"
```

This is a structural guard: it covers the subcommands nobody thought to test,
which is exactly where an undefined-argument bug hides. Placeholder values must
satisfy each positional's type — an `int` argument needs `"1"`, not `"id"`.

**A live/refresh view polls the store; it does not watch the file.** When the
writer is a different process (the plugin host, a gateway), there is no
in-process signal to subscribe to, so poll on an interval. Two guards matter:
refuse to run when `sys.stdout.isatty()` is false (a piped invocation would spin
emitting escape codes into a log), and catch `KeyboardInterrupt` to exit 0 after
clearing the screen. Redraw in place (`\x1b[H` + frame + `\x1b[0J`) rather than
reprinting, so a terminal pane stays readable. Verify it by driving it in a real
pty: render a frame, mutate the store from a **separate** process, and assert the
next frame shows the change — cross-process refresh is the feature, and an
in-process test cannot prove it.
