# Putting TanyaCCTV online with Render

The repository includes everything Render needs: a `Dockerfile`, a `render.yaml` Blueprint and a small
start-up file (`backend/scripts/render_app.py`). By default it publishes the **offline demo**: the
generated demo footage with its preset event index. Search, results, the player, the map,
investigations, the incident timeline and report export all work. No API key is used and nothing is
sent to Google.

## Deploy (about 10 minutes, mostly waiting)

1. Sign in at https://dashboard.render.com with GitHub.
2. **New → Blueprint**, then choose the `TanyaCCTV` repository (grant Render access to it if asked) and
   the `main` branch.
3. Render reads `render.yaml` and shows one web service, `tanyacctv`, on the free plan. Press **Apply**.
4. Wait for the first build (5–8 minutes: it installs Python packages and builds the demo footage once).
   When the service shows **Live**, open its address, e.g. `https://tanyacctv.onrender.com`.

After that, every push to `main` redeploys automatically.

**Optional password.** In the service's **Environment** tab, add `TANYA_SITE_PASSWORD` with a password of
your choice and save. The browser then asks for it (any user name). Remove it to open the site again.

## What to expect on the free plan

- **It sleeps when idle.** After about 15 minutes without visitors, the first visit takes about a minute
  to wake it. Open the site a few minutes before a presentation.
- **It resets.** Each restart or redeploy goes back to the freshly built demo: investigations, notes,
  camera names and map positions made on the site are not kept. That suits a public demo.
- **No uploads.** `TANYA_DISABLE_UPLOADS=1` hides "Add footage" and "Check folder for new videos", so
  visitors cannot fill the server with video. Remove it to allow uploads (they are still lost on reset).

## Settings

| Variable | What it does |
| --- | --- |
| `TANYA_MODE` | `demo` (default): the prepared offline demo. `full`: the normal website on your own folders. |
| `TANYA_DISABLE_UPLOADS` | `1` turns off uploading and folder indexing. |
| `TANYA_SITE_PASSWORD` | If set, every page asks for this password (HTTP Basic). |
| `TANYA_ALLOWED_HOSTS` | Extra web addresses to accept, comma-separated, e.g. a custom domain. Render's own address is accepted automatically. |
| `TANYA_VIDEO_DIR`, `TANYA_FRAMES_DIR`, `TANYA_DB_PATH` | Full mode only: where videos, frames and the database live. |

Locally none of these are set, so `run_web.py` and `run_offline_demo.py` behave as before: localhost only,
no password, uploads on. `/healthz` answers "ok" for the host's health check and returns no data.

## The full website (your own footage)

`TANYA_MODE=full` serves the normal website. Its videos, frames and database must survive restarts, so it
needs a **persistent disk**, which Render only offers on paid plans:

1. Change the plan to Starter or higher and add a disk (e.g. mount path `/var/data`, 10 GB).
2. Set `TANYA_MODE=full`, `TANYA_VIDEO_DIR=/var/data/videos`, `TANYA_FRAMES_DIR=/var/data/frames`,
   `TANYA_DB_PATH=/var/data/tanya.db`, and remove `TANYA_DISABLE_UPLOADS`.
3. Set `TANYA_SITE_PASSWORD`. The website has no user accounts, so anyone with the address could otherwise
   see and change your footage and investigations.

AI search additionally needs the SentrySearch environment and a Gemini key, which this image does not
install. Without them, the full website still uploads, indexes, plays and organises footage.

## Running the same image elsewhere

```bash
docker build -t tanyacctv .
docker run -p 10000:10000 -e TANYA_ALLOWED_HOSTS=localhost:10000 tanyacctv
```

Then open http://localhost:10000/. The image runs one gunicorn worker with several threads, because
uploads, scans and the session secret live in that one process.
