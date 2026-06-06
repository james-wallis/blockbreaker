# CLAUDE.md — `web-port/`

Browser-playable port of the original Block Breaker game. It runs the **actual
Python source** in the browser via [Pyodide](https://pyodide.org) (CPython
compiled to WebAssembly) — it is *not* a rewrite in JavaScript.

## Relationship to the repo root

The originals live in the repo root: `../blockbreaker.py` (game) and
`../graphics.py` (John Zelle's tkinter-based library). **Do not modify the
root files** — they are the historical first-year submission and must stay
untouched. All web work happens in this directory on *copies*.

When porting a fix from the root game, keep the logic identical and re-apply
only the web adaptations described below.

## Files

| File | Purpose |
|------|---------|
| `index.html` | Host page. Loads Pyodide from a CDN, writes the two `.py` files into Pyodide's FS, imports them, runs a `requestAnimationFrame` paint loop, then `await blockbreaker.main()`. |
| `graphics.py` | Drop-in replacement for Zelle's `graphics.py`. Renders to an HTML5 `<canvas id="game">` and reads mouse input. Only the subset of the API the game uses is implemented. |
| `blockbreaker.py` | The game. Logic identical to the root original; only the web adaptations below differ. |
| `api/scores.js` | Vercel serverless function (Node, ESM) backing the shared leaderboard. `GET` returns the top 10; `POST {name,score}` validates and inserts. Reads/writes Turso via `@libsql/client`. |
| `package.json` | Declares the `@libsql/client` dependency for the function. `type: module`. No project build (`vercel.json` sets `buildCommand: null`); Vercel still installs deps for the function. |
| `vercel.json` | Static-site config: no build, serve the folder as-is. The `.py` files are static assets; `api/*.js` is auto-detected as a function. |
| `.vercelignore` | Keeps `CLAUDE.md`/`README.md` out of the deployment. |
| `README.md` | User-facing: how to run and embed. |

## How the port differs from the original (the only intended changes)

1. **Async game loop.** Browsers freeze on a blocking `while` loop, so:
   - `time.sleep(x)` → `await asyncio.sleep(x)`
   - `win.getMouse()` → `await win.getMouse()`
   - the main loop `await asyncio.sleep(FRAME_DELAY)` once per iteration to yield.
   - Every function in the call chain that awaits is `async` (`main`, `subMain`,
     `instructions`, `playGame`, `checkBlocks`, `setLevel`, `gameEnded`,
     `addHighScore`, `showHighScore`, `exitButtonPressed`) and its callers `await` it.
2. **Persistence → shared online leaderboard.** No filesystem in the browser,
   and the goal is one global leaderboard for all visitors. So `highScores.txt`
   became a **shared Turso DB** reached via the `/api/scores` serverless
   function. In `blockbreaker.py`:
   - `highScoresLists` (now `async`) `GET`s `/api/scores` via `pyodide.http.pyfetch`;
     `writeToFile` (now `async`) `POST`s the new score. Both callers `await`.
   - `localStorage` (key `blockbreaker_highscores`) remains an **offline
     fallback cache** via `_load_local_raw`/`_local_scores_lists`/`_local_write`,
     so the game still works with no backend (e.g. `python3 -m http.server`,
     where `/api/scores` 404s and the code falls back silently).
   - The "Close and reset High Scores" button resets ONLY the local cache — it
     deliberately does NOT wipe the shared DB (any visitor could otherwise).
3. **Exit.** `sys.exit()` → `raise SystemExit`, caught in `main()`.
4. **Touch / drag bat control.** The original moves the bat one step per click
   (tap left/right half of the play area). On a touchscreen that means tapping
   repeatedly, so the web port also supports **press-and-drag steering**:
   - `graphics.py` tracks a held pointer via Pointer Events (`pointerdown`/
     `pointermove`/`pointerup`/`pointercancel`, which unify touch + mouse + pen),
     exposing `pointerActive()` (true while pressed *within the play area*, x≤100,
     so taps in the stats/stop-button column don't drag the bat) and `pointerX()`.
     The proxies are stored on `self._pointer_proxies` so they aren't GC'd.
   - `index.html` sets `touch-action: none` on the canvas so a swipe steers the
     bat instead of scrolling/zooming the page.
   - `moveBat` in `blockbreaker.py` steers the bat toward `pointerX()` (≤ the bat's
     step speed per frame, easing as it nears so it settles smoothly) when a
     pointer is held; otherwise it falls through to the **unchanged** original
     click-to-nudge logic. A plain desktop tap releases before the next frame, so
     desktop behaviour is preserved. This branch is web-only — the root
     `moveBat` has no `pointerActive`/`pointerX` to call, so keep it guarded here.
5. **Per-level block recolour (re-enabled).** The root game *intended* to recolour
   the remaining blocks each level but had to comment it out (`# TODO debug this
   as it causes the program to freeze`): it recoloured **all** blocks on **every**
   block hit, and under Zelle's tkinter each `setFill`/`setOutline` is a
   synchronous redraw, so it froze. The web port re-enables it correctly:
   - `setLevel` now also returns a `leveledUp` flag (3-tuple:
     `ballSpeedY, level, leveledUp`); `checkBlocks` calls `recolourBlocks` **only
     when `leveledUp`** — once per level-up, not per hit.
   - `recolourBlocks(blockList, level)`: even levels → black fill + the block's
     own coloured outline (so on the dark theme they read as colour-outlined
     "hollow" blocks); level 5 → black fill + white outline; other odd levels →
     restore the block's original colour (fill + outline, stored in `block[1]`).
     The even branch sets the outline explicitly (not just the fill) so the
     white level-5 outline doesn't linger into level 6.
   - Cheap here because the web `graphics.py` is retained-mode (one repaint per
     rAF frame regardless of how many `setFill` calls happen). This divergence
     would NOT be safe to port back to the tkinter root as-is — that's why it
     stays web-only.

### Leaderboard backend (`api/scores.js` + Turso)

- Function needs env vars `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` (set in
  Vercel project settings / `vercel env`). Credentials stay server-side.
- Schema (constraints enforced DB-side so a bypassed client still can't insert junk;
  note SQLite ignores `VARCHAR(n)` length, so `CHECK(length(...))` is the correct way):
  ```sql
  CREATE TABLE scores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL CHECK (length(name) BETWEEN 3 AND 10),
    score      INTEGER NOT NULL CHECK (score >= 0 AND score <= 1000000),
    created_at INTEGER NOT NULL
  );
  ```
  Top query: `SELECT name, score FROM scores ORDER BY score DESC, created_at ASC LIMIT 10`.
- Validation is layered: the API does name 3–10 chars / score 0–1,000,000 for clean
  `400`s; the DB `CHECK` constraints are the hard backstop. A client-side game
  leaderboard is still inherently spoofable — this is sanity-checking, not anti-cheat.

If you touch game logic, change it in a way that would also be correct in the
root version — the two should stay logically in sync.

## Architecture notes for `graphics.py`

- **Retained-mode scene.** `GraphWin.items` is the draw list. Objects mutate
  their own state (`move`, `setText`, …); the JS rAF loop calls
  `window.__bbRender` → `render_active()` → `GraphWin._render()`, which clears
  and repaints the whole scene every frame. Don't paint imperatively on mutation.
- **Single thread / cooperative.** Pyodide and the rAF loop share the one JS
  thread. The paint callback only fires while Python is `await`-ing, so frames
  are always painted from consistent state — no locking needed.
- **Coordinate transform.** `setCoords(0,0,140,100)` maps world→pixels with the
  y-axis flipped (`_sy`). Scaling is non-uniform (900/140 vs 600/100), so a
  `Circle` renders as an ellipse — matches Zelle under `setCoords`.
- **Colors.** `_COLORS` maps Tk/X11 names CSS doesn't know (`red4`, `orange4`,
  …) and the few that differ (`green`) to hex. `color_rgb` returns CSS hex.
- **Entry** is a real HTML `<input>` overlaid on the canvas (positioned inside
  `#overlay`, accounting for CSS scale), since canvas has no text input.
- **Mouse** clicks are converted to world coords in `_on_click` and queued;
  `checkMouse()` is non-blocking, `getMouse()` polls the queue with `asyncio`.
- Proxies passed to JS (`render_active`, `_on_click`) use `create_proxy` and are
  kept referenced so they aren't garbage-collected.

## Running / testing

Must be served over HTTP (the page `fetch`es the `.py` files; `file://` won't work):

```sh
cd web-port && python3 -m http.server 8000   # open http://localhost:8000
```

Headless smoke test (Chrome via DevTools Protocol) used during development:
load the page, wait for `#loading.hidden`, assert the canvas has non-black
pixels, dispatch clicks, check the console for exceptions, screenshot. There is
no automated test in-repo; re-create ad hoc if needed.

## Deployment (live)

- **Hosted on Vercel**, project `blockbreaker` under the **`wallis-dev`** team.
  Public URL: **https://blockbreaker.wallis.dev** (custom domain). The generated
  `*.vercel.app` URLs are gated by Vercel Deployment Protection (401) — that's
  expected; the custom production domain is public.
- **Env vars** (`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`) are set on the Vercel
  project for Production + Preview. The serverless function reads them at runtime.
- **Git-worktree snag:** this Conductor workspace's `.git` is a *file*, which the
  Vercel CLI chokes on (`ENOTDIR ... .git/config`). So **do not deploy from
  `web-port/` directly.** Instead copy the deployable files to a clean dir
  outside the repo and deploy from there:
  ```sh
  rm -rf /tmp/bb-deploy && mkdir -p /tmp/bb-deploy
  cp -R web-port/{index.html,graphics.py,blockbreaker.py,package.json,vercel.json,.vercelignore,api} /tmp/bb-deploy/
  cd /tmp/bb-deploy
  vercel link --yes --project blockbreaker --scope wallis-dev
  vercel deploy --prod --yes
  ```
- **CLI version:** needs Vercel CLI ≥ 47. An old `vercel` (v33) shadowed by a
  yarn-global install caused `This endpoint requires version 47.2.2 or later`.
  The npm-global one (`~/.nvm/.../bin/vercel`) is current — call it by full path
  if `vercel --version` shows an old one.
- **Turso CLI** is NOT authenticated in this workspace; the DB (`blockbreaker`,
  table `scores`) was set up by the user. To seed/clean rows from here, the user
  must `turso auth login` first (it shares `~`, so this shell then sees it).

## Tunables

- `FRAME_DELAY` in `blockbreaker.py` — seconds per frame; lower = faster game.
- Pyodide version is pinned in `index.html` (`v0.26.4`). Bump deliberately and
  re-test; the `pyodide.ffi`/`create_proxy` API has changed across versions.

## Gotchas

- Don't open `index.html` via `file://` — `fetch` of the `.py` files is blocked.
- Pyodide loads from a CDN (needs internet). To go offline, self-host the
  Pyodide assets and update the `<script src>` and `loadPyodide({indexURL})`.
- `__pycache__/` can appear if you run `py_compile` here — it's noise; don't commit it.
