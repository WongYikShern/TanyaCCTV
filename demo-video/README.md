# TanyaCCTV pitch video toolkit

Scripts that record the real app scene by scene and edit them into the pitch film. The story, shot
list, narration and honesty rules are in [BRIEF.md](BRIEF.md).

Generated and third-party media are not in Git (see `.gitignore`): recordings (`segments/`), renders
(`out/`), voice files (`vo/`, `vo2/`), sound effects (`sfx/`) and the music track (`music/`).

## Rebuild the film (macOS)

1. Start the app with the demo cameras, notes and rules set up: `.venv/bin/python backend/scripts/run_web.py`.
2. Point the toolkit at an ffmpeg binary with libx264 and libass (the one bundled with the search
   environment works):
   `.venv/sentry/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" > demo-video/ffmpeg-path`
3. Sound effects: `sh demo-video/make_sfx.sh`.
4. Music: download "Drawing the Sky" by Eugenio Mininni from Mixkit (free licence) to
   `demo-video/music/606.mp3`: `https://assets.mixkit.co/music/606/606.mp3`.
5. Record the scenes (headless Chrome, 1920x1080): `cd demo-video && node record.mjs`
   (or name scenes: `node record.mjs parking1 parking2`).
6. Edit:
   - Pitch cut (about 3:20): `python build2.py` (temporary macOS voice), or
     `ELEVEN_VOICE_ID=<voice id> python build2.py --voice eleven` with `ELEVENLABS_API_KEY` in `.env`
     (the key needs the Text to Speech permission). Output: `out/TanyaCCTV-pitch.mp4`.
   - First cut (about 4:00, narrated tour): `python build.py`. Output: `out/TanyaCCTV-demo.mp4`.

## Files

| File | What it does |
|---|---|
| `record.mjs` | Drives the app in headless Chrome and records each scene as timestamped frames, plus sound cues for alerts |
| `cards.html` | Title cards and pitch cards (open in Chrome with `#problem`, `#solution`, `#stat40`, `#final`, ...) |
| `cctv.html` | Full-screen CCTV look for the opening shot |
| `build2.py` | Pitch cut: shot list, zoom-ins, narration anchored to on-screen moments, music ducked under the voice, subtitles |
| `build.py` | First cut, and shared helpers (frame-to-video encoding) |
| `make_sfx.sh` | Synthesises the sound effects |
| `script.json` | Narration of the first cut |

The recorder bypasses the app's Content Security Policy in its own browser session only, so it can
inject layout tweaks (e.g. one large monitor feed); the app itself is unchanged.
