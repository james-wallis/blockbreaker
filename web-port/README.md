# Block Breaker — Web build

A browser-playable version of the original first-year Python game, running the
**actual Python code** in the browser via [Pyodide](https://pyodide.org)
(CPython compiled to WebAssembly). No rewrite — the game logic is the same.

## What's here

| File | Purpose |
|------|---------|
| `index.html` | Host page: loads Pyodide, wires up the canvas + paint loop, starts the game. |
| `graphics.py` | A small drop-in replacement for John Zelle's `graphics.py` that renders to an HTML5 `<canvas>` and reads mouse clicks, instead of using tkinter (which can't run in a browser). |
| `blockbreaker.py` | The game. Identical logic to the repo-root original; the only changes are: the game loop is `async` (so the browser stays responsive), and high scores go to a shared online leaderboard (with a `localStorage` fallback) instead of `highScores.txt`. |
| `api/scores.js` | Serverless function for the shared leaderboard (top 10 read / submit), backed by a Turso database. |

The originals in the repo root are **unchanged**.

## Run locally

Pyodide loads from a CDN (needs internet), and the page fetches the `.py`
files, so it must be served over HTTP — opening `index.html` via `file://`
won't work.

```sh
cd web-port
python3 -m http.server 8000
# then open http://localhost:8000
```

## Embed on a website

Host the three files (`index.html`, `graphics.py`, `blockbreaker.py`) anywhere
static — e.g. Vercel, Netlify, GitHub Pages, or a subfolder of your site. Then
drop an iframe wherever you want the game:

```html
<iframe src="https://your-site.com/blockbreaker/"
        width="900" height="600"
        style="border:0;max-width:100%;aspect-ratio:3/2"
        title="Block Breaker"></iframe>
```

The canvas scales to the iframe width, so set the iframe size to taste.

## Notes / tunables

- **Game speed**: `FRAME_DELAY` in `blockbreaker.py` (seconds per frame). Lower = faster.
- **Controls**: click the left/right half of the play area to nudge the bat (as in the original).
- **High scores** are a global leaderboard shared by all visitors, stored in Turso and served via `/api/scores`. If the API is unreachable (e.g. running locally with `python3 -m http.server`, which has no backend), the game silently falls back to a per-browser `localStorage` cache. "Close and reset High Scores" only clears that local cache, never the shared leaderboard. Requires env vars `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` on the deployment.
- First load pulls down the Pyodide runtime (~a few MB, cached afterwards), hence the brief loading screen.
