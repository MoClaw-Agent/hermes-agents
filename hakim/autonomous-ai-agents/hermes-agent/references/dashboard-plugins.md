# Adding a Dashboard Tab to a Plugin

`hermes dashboard` (web UI, default port 9119) discovers plugin tabs from a
`dashboard/` subdirectory of any plugin directory. This is a **separate system**
from `plugin.yaml` / `register(ctx)` — a working agent plugin gets no dashboard
presence until you add these files.

## Layout

```
~/.hermes/plugins/<name>/
  plugin.yaml            # agent plugin manifest (tools, hooks)
  __init__.py            # register(ctx)
  dashboard/
    manifest.json        # dashboard discovery + tab declaration
    dist/index.js        # the bundle (IIFE; calls window.__HERMES_PLUGINS__.register)
    dist/style.css       # optional
    plugin_api.py        # optional FastAPI router
```

## `manifest.json`

Discovered by scanning `<plugins root>/*/dashboard/manifest.json` across the
user root (`~/.hermes/plugins`), bundled plugins, and (opt-in) project plugins.
First name wins; user plugins are authoritative over same-named root ones.

```json
{
  "name": "myplugin",
  "label": "My Plugin",
  "description": "Shown in the plugins hub",
  "icon": "Package",
  "version": "1.0.0",
  "tab": { "path": "/myplugin", "position": "after:skills" },
  "entry": "dist/index.js",
  "css": "dist/style.css",
  "api": "plugin_api.py"
}
```

- `tab.position` — `"end"`, `"after:<segment>"`, `"before:<segment>"`.
- `tab.override` — set to a built-in route path to *replace* that page instead
  of adding a tab. This one is load-bearing on the host side: the frontend keeps
  its loading gate closed while any cached manifest declares a `/chat` override,
  so a plugin that sets it changes mount ordering. Don't set it casually.
- `tab.hidden` — register without a sidebar tab (slot-only plugins).
- `integrity` — optional SRI hash (`sha384-…`); the browser refuses to execute a
  bundle whose hash does not match.
- `slots` — declared for discovery only; real slot use is `registerSlot` at
  runtime.

## Trust gates — a plugin can be installed and still not appear

- **`plugins.enabled` is required for user plugins.** The dashboard filters out
  any user plugin not in the allow-list (bundled plugins only need to not be
  explicitly disabled). Same gate as the agent plugin, separate enforcement.
- **Project plugins (`./.hermes/plugins/`) may ship static JS/CSS but their
  Python `api` file is never auto-imported** — the checkout travels with the
  repo and is therefore attacker-controlled. Don't rely on a project plugin's
  backend; install under the user root for that.
- `dashboard.hidden_plugins` in config removes a plugin from the listing.

## Frontend contract (what the host actually does)

The dashboard fetches `GET /api/dashboard/plugins`, then for each manifest:

1. injects `<link rel=stylesheet>` for `css`, and
2. injects `<script src="…/dashboard-plugins/<name>/<entry>">`, then
3. waits for the bundle to call `window.__HERMES_PLUGINS__.register(name, Component)`.

If the script loads but never registers, the host records a `NO_REGISTER` error
and the tab stays empty — a silent failure worth knowing when a tab renders
blank.

Globals available to the bundle (no bundler against Hermes internals; the SDK
exists precisely to avoid coupling to `@/lib/api`):

- `window.__HERMES_PLUGIN_SDK__` — `React`, `hooks` (`useState`, `useEffect`, …,
  `useToast`, `useConfirmDelete`), `components` (shared UI primitives),
  `fetchJSON`, `authedFetch`, `buildWsUrl`, `useI18n`, `utils`.
- `window.__HERMES_PLUGINS__.register(name, Component)` — the tab component.
- `window.__HERMES_PLUGINS__.registerSlot(slot, name, Component)` — into a named
  host slot.

**Use `fetchJSON` / `authedFetch`, never a hand-rolled `fetch`.** They handle
auth in both dashboard modes (loopback session token, gated cookie) and trigger
the global 401 → `/login` redirect. Reading the session token off `window`
yourself breaks the moment the dashboard runs gated.

## The SDK components are NOT shadcn — check the host's own usage first

The `components` map comes from `@nous-research/ui`, and several of its
signatures differ from the shadcn/ui equivalents they resemble. Guessing the
shadcn prop shape throws inside the host's bundle and blanks the whole tab.

Known divergences:

- **`Tabs` is a render-prop component**: `{ children: (active, setActive) =>
  ReactNode, defaultValue }`. It calls `children(active, setActive)`, so passing
  React *elements* as children throws `TypeError: e is not a function` from the
  host's `ui-*.js` and unmounts the tab. There is no `value`/`onValueChange`.
- **`TabsTrigger` takes `active: boolean`** and ignores `value`.
- **`Toast` takes `{ toast }`** (from `useToast()`), which matches shadcn — but
  verify rather than assume.

Before using any SDK component, check whether the host's own pages render it:
`grep -rn "<Tabs" <checkout>/web/src --include=*.tsx`. If the host never uses
it, treat its contract as unverified — and prefer a plain `Button` bar over a
complex component you cannot see an example of. The authoritative signatures are
in `<checkout>/node_modules/@nous-research/ui/src/ui/components/*.tsx`.

## Blank tab: debugging procedure

A tab that renders nothing is almost never the manifest or the API — those
fail loudly. Work this order:

1. **Compare against a bundled plugin tab** (`/kanban`, `/achievements`). If
   those render and yours does not, the fault is in your bundle, not the host.
2. **Capture the real exception.** React swallows a render throw: the page's own
   `console.error` stays empty and the tab simply vanishes, so an empty console
   is NOT evidence of success. Install a trap *before* app code runs
   (`Page.addScriptToEvaluateOnNewDocument` over CDP, or an `error` +
   `unhandledrejection` listener) and read it back after load. A message naming
   the host's `ui-*.js` means a component-contract problem, not your logic.
3. **Only then** read the code. Asserting a root cause from reading your own
   bundle while the runtime can name it directly wastes the whole cycle.

Related silent failure: the bundle loading without ever calling `register()`
shows as `NO_REGISTER` and an empty tab. Confirm registration happened rather
than assuming the script ran.

## Backend contract (`api` in the manifest)

`plugin_api.py` exposes a FastAPI `router`, mounted at `/api/plugins/<name>/`.
It runs in the **plugin host**, not the dashboard server process, and the
mount is gated on `plugins.enabled` (a not-enabled plugin's Python must never
import at dashboard startup).

- Keep handlers thin wrappers over the same core the CLI and agent tools call,
  so the surfaces cannot drift.
- Resolve state paths the way the plugin does. There is **no `ctx`** in this
  module — it is imported by the dashboard, not by `register(ctx)` — so read the
  plugin's settings the way `PluginContext.get_config` does
  (`hermes_cli.plugins_state._plugin_settings_entry(load_config_readonly(), <id>)`)
  with the project config as the fallback.
- Import the plugin's own package explicitly; the checkout is on `sys.path` only
  because the shim put it there, which does not hold in this process. In
  `plugin_api.py`, resolve the repo root (env var → `repo-path.txt` next to the
  plugin dir → well-known locations) and insert it into `sys.path` **before**
  importing the plugin's own modules. Without this, the host raises
  `ModuleNotFoundError` on the first `from core …` import and every route
  returns 502 "could not run in this profile's plugin host".
- Route exceptions to HTTP codes deliberately (`NotFound` → 404, a store
  rejection → 400) rather than letting a 500 carry the detail.

## Two prerequisites that are easy to miss

- **The dashboard frontend must be built.** `hermes dashboard` serves
  `web/dist`; with no build it has nothing to serve. Build it with `npm run
  build` in the Hermes checkout's `web/` (Node 26 / npm 12 present here), or
  pass `--skip-build` to serve an existing `dist`. `hermes dashboard --status`
  will attempt to *start* the server rather than only reporting state — do not
  reach for it as a cheap readiness check.
- **The dashboard and the plugin runtime use different interpreters.** FastAPI
  and uvicorn live in the Hermes workspace venv (`hermes-agent/venv/`), not in
  the runtime Python that loads plugins. Test a `plugin_api.py` with the
  workspace venv (`hermes-agent/venv/bin/python`), and test the shim with the
  runtime Python — they are separate claims.

## Verifying

`hermes plugins validate` checks `plugin.yaml` against `register()`; it says
nothing about `manifest.json`. For the dashboard side:

1. `python -c` the `plugin_api.py` under the workspace venv and assert the
   expected routes are on `router.routes` — import errors and typos surface here.
2. Exercise every route with FastAPI's `TestClient`, including the error paths
   (a missing id should be a 404, a bad body a 422). Patch the module's own
   `_store` (or equivalent accessor) to point at a scratch database; that works
   because handlers resolve it through module globals.
3. Then confirm discovery by rendering the tab in a real browser. An offline
   route test proves the backend; it does not prove the bundle registered or the
   tab appears.
4. **Prove the tab mutates, not just that it paints.** Read the rendered text to
   confirm the panes and data, then drive one action (accept/reject/save) and
   assert the visible state changed against the real store. Rendered text alone
   does not show that the click handlers reach the backend.

**Installing from a source checkout:** the host discovers
`<plugins root>/<name>/dashboard/manifest.json`, so a plugin whose source lives
in a repo is invisible until those files are *copied* into the plugin directory.
Keep the copy in the install script and diff source against the installed copy
afterwards — an edit that never gets copied looks exactly like a code bug.
