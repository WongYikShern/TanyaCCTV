"""Pitch cut (v2): pitch order, zoom-ins on key moments, music ducked under narration, subtitles.

python build2.py [--voice mac|eleven]   (eleven needs ELEVENLABS_API_KEY in ../.env and VOICE_ID below)
Outputs out/TanyaCCTV-pitch.mp4 and out/pitch-script.txt.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from build import FF, FPS, SEG, OUT, encode, run, duration, ass_time

HERE = Path(__file__).resolve().parent
VO2 = HERE / "vo2"
MUSIC = HERE / "music/606.mp3"          # "Drawing the Sky", Eugenio Mininni (Mixkit free licence)
MUSIC_RISE = 17.0                       # where the track's quiet intro ends
ELEVEN_VOICE = os.environ.get("ELEVEN_VOICE_ID", "")

# Shots: (segment, trim in, trim out, zoom (centre x, centre y, final zoom) or None)
SHOTS = [
    ("card-elmina", 0, None, None),
    ("fall", 0, None, None),
    ("card-problem", 0, None, None),
    ("card-solution", 0, None, None),
    ("card-sec-prevent", 0, None, None),
    ("parking1", 4.0, 19.5, (0.45, 0.52, 1.3)),
    ("parking2", 0, None, (0.47, 0.50, 1.55)),
    ("card-stat40", 0, None, None),
    ("parking3", 0, 7.5, (0.43, 0.48, 1.45)),
    ("card-sec-find", 0, None, None),
    ("search", 0.8, 12.0, (0.55, 0.55, 1.25)),
    ("hoodie", 0.3, 9.0, (0.43, 0.48, 1.45)),
    ("card-stathours", 0, None, None),
    ("card-sec-people", 0, None, None),
    ("lobby", 1.5, 12.5, (0.45, 0.55, 1.4)),
    ("bag", 0, None, (0.45, 0.55, 1.4)),
    ("card-sec-township", 0, None, None),
    ("map", 1.0, 12.5, (0.45, 0.50, 1.2)),
    ("evidence", 0.5, 11.0, (0.62, 0.42, 1.2)),
    ("card-why", 0, None, None),
    ("card-whynow", 0, None, None),
    ("card-ask", 0, None, None),
    ("card-outcome", 0, None, None),
    ("card-final", 0, None, None),
]
# Narration: (segment, seconds into the trimmed shot, or ("cue", sound, offset)), text
LINES = [
    ("card-elmina", 0.9, "Seven forty-two pm. City of Elmina."),
    ("fall", 1.2, "Uncle Lim is on his evening walk through the mall."),
    ("fall", 7.0, "He collapses."),
    ("fall", 9.2, "A camera sees it all. Nobody's watching."),
    ("card-problem", 0.4, "Our townships have never had more cameras. But almost all of that footage is never watched. CCTV only ever looks back."),
    ("card-solution", 1.4, "So we built TanyaCCTV. Cameras that don't just record. They respond."),
    ("parking1", 0.3, "Three thirty am. One zone, one motorbike. That's the whole setup."),
    ("parking1", ("cue", "warning", 0.0), "Someone's at the bike. A warning, almost forty seconds before it's taken."),
    ("parking2", ("cue", "alarm", -1.0), "Then, the alarm."),
    ("parking3", 0.4, "One click, and it follows the bike, frame by frame."),
    ("search", 0.2, "Next morning. No more scrubbing through hours of footage. Just ask."),
    ("search", 5.4, "In seconds, there he is."),
    ("hoodie", 0.4, "And it follows him, even when he walks out of view."),
    ("lobby", ("cue", "warning", -0.6), "And it's not just property. Someone collapses? Flagged in four seconds."),
    ("bag", ("cue", "warning", -2.6), "A bag left behind? Flagged before anyone reports it missing."),
    ("map", 0.6, "Every camera, on one map."),
    ("evidence", 0.4, "Every alert becomes evidence you can trust. And a person always makes the final call."),
    ("card-why", 0.4, "It works with the cameras you already have. It runs on one computer. And every recording stays on site."),
    ("card-whynow", 0.4, "In two thousand and nine, Sime Darby Property pioneered Safe City, with twenty-two cameras. The Township of Tomorrow needs cameras that think."),
    ("card-ask", 0.5, "Give us one precinct, for thirty days. We'll show you the moments that matter, before they happen."),
    ("card-outcome", 0.5, "Uncle Lim? Help reached him in minutes. Because this time, someone was watching."),
    ("card-final", 2.0, "TanyaCCTV. Your township's cameras, now listening."),
]
SFX_VOLUME = {"heartbeat": 0.9, "impact": 0.7, "whoosh": 0.45, "key": 0.3, "notice": 0.45, "warning": 0.5, "alarm": 0.6}


def eleven_key():
    for line in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ELEVENLABS_API_KEY is not set in .env")


def voice_line(i, text, engine):
    VO2.mkdir(exist_ok=True)
    if engine == "eleven":
        path = VO2 / f"e{i:02d}.mp3"
        if not path.exists():
            body = json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                               "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}}).encode()
            req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE}", data=body,
                                         headers={"xi-api-key": eleven_key(), "Content-Type": "application/json", "Accept": "audio/mpeg"})
            path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    else:
        path = VO2 / f"m{i:02d}.aiff"
        if not path.exists():
            subprocess.run(["say", "-v", "Daniel", "-r", "172", "-o", str(path), text], check=True)
    return path, duration(path)


def shot_video(name, a, b, zoom, length):
    """Trim, then optionally push in slowly towards (cx, cy) up to the final zoom, eased."""
    src = SEG / name / "video.mp4"
    out = SEG / name / f"shot-{a:.2f}-{length:.2f}-{zoom}.mp4".replace(" ", "")
    if out.exists() and out.stat().st_mtime > src.stat().st_mtime:
        return out
    vf = [f"trim=start={a:.3f}:duration={length:.3f}", "setpts=PTS-STARTPTS"]
    if zoom:
        cx, cy, z = zoom
        # Per-frame scale-up then a 1920x1080 crop that drifts towards (cx, cy): far faster than zoompan.
        e = f"((1-cos(PI*min(t/{length:.3f},1)))/2)"   # ease in-out 0..1 over the shot
        zz = f"(1+{z - 1}*{e})"
        vf += [f"scale=w='2*trunc(960*{zz})':h='2*trunc(540*{zz})':eval=frame:flags=bicubic",
               f"crop=1920:1080:x='max(0,min(iw-1920,(0.5+({cx}-0.5)*{e})*iw-960))':y='max(0,min(ih-1080,(0.5+({cy}-0.5)*{e})*ih-540))'"]
    vf += [f"fps={FPS}", "format=yuv420p"]
    run("-i", src, "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", out)
    return out


def main():
    engine = "eleven" if "--voice" in sys.argv and sys.argv[sys.argv.index("--voice") + 1] == "eleven" else "mac"
    segs = {name: encode(name) for name, *_ in SHOTS}
    lines = [(seg, anchor, text, *voice_line(i, text, engine)) for i, (seg, anchor, text) in enumerate(LINES)]

    clock, prev_end, placed, cues, parts, starts = 0.0, 0.0, [], [], [], {}
    for name, a, b, zoom in SHOTS:
        seg = segs[name]
        b = seg["length"] if b is None else min(b, seg["length"])
        length = b - a
        starts[name] = clock
        shot_cues = [(s, t - a) for s, t in seg["cues"] if a - 0.3 <= t <= b]
        for _, anchor, text, path, dur in [l for l in lines if l[0] == name]:
            at = (next((t for s, t in shot_cues if s == anchor[1]), 0.0) + anchor[2]) if isinstance(anchor, tuple) else anchor
            t = max(clock + at, prev_end + 0.3)
            placed.append((t, dur, path, text)); prev_end = t + dur
        # Hold the last frame only if narration that started here runs past the shot.
        hold = max(0.0, prev_end + 0.35 - (clock + length))
        cues += [(s, clock + max(0.0, t)) for s, t in shot_cues]
        parts.append((name, a, length, zoom, hold))
        clock += length + hold
    total = clock + 0.5
    print(f"film {total:.1f} s; holds: " + ", ".join(f"{n} +{h:.1f}" for n, a, l, z, h in parts if h > 0.05))

    files = []
    for name, a, length, zoom, hold in parts:
        v = shot_video(name, a, None, zoom, length)
        if hold > 0.05:
            held = v.with_name(v.stem + f"-hold{hold:.2f}.mp4")
            if not held.exists():
                run("-i", v, "-vf", f"tpad=stop_mode=clone:stop_duration={hold:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "17", held)
            v = held
        files.append(v)
    (OUT / "parts2.txt").write_text("".join(f"file '{f}'\n" for f in files))
    run("-f", "concat", "-safe", "0", "-i", OUT / "parts2.txt", "-c", "copy", OUT / "video2.mp4")

    # Audio buses: narration, effects, music (ducked by the narration), opening heartbeat and drone.
    music_start = max(0.0, starts["card-solution"] - MUSIC_RISE + 0.6)
    inputs, f = [], []
    def inp(path):
        inputs.extend(["-i", str(path)]); return len(inputs) // 2 - 1
    vo = [f"[{inp(p)}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(t*1000)}:all=1[v{i}]" for i, (t, d, p, x) in enumerate(placed)]
    f += vo
    f.append("".join(f"[v{i}]" for i in range(len(placed))) + f"amix=inputs={len(placed)}:normalize=0,volume=1.6,asplit=2[vo][voside]")
    fx = []
    for s, t in cues:
        if s == "heartbeat":
            for k in range(9):
                fx.append((HERE / "sfx/heartbeat.wav", t + k * 0.95, SFX_VOLUME[s] * (1 - k * 0.08)))
        else:
            fx.append((HERE / f"sfx/{s}.wav", t, SFX_VOLUME.get(s, 0.5)))
    fx.append((HERE / "sfx/drone.wav", 0, 0.45))
    for i, (p, t, vol) in enumerate(fx):
        f.append(f"[{inp(p)}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},adelay={int(max(0, t)*1000)}:all=1[x{i}]")
    f.append("".join(f"[x{i}]" for i in range(len(fx))) + f"amix=inputs={len(fx)}:normalize=0[fx]")
    m = inp(MUSIC)
    f.append(f"[{m}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.55,afade=t=in:d=3,adelay={int(music_start*1000)}:all=1[mus]")
    f.append("[mus][voside]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=450:makeup=1[musd]")
    f.append(f"[vo][fx][musd]amix=inputs=3:normalize=0,atrim=0:{total:.2f},afade=t=out:st={total-4:.2f}:d=4,alimiter=limit=0.93[aout]")
    (OUT / "audio2.txt").write_text(";".join(f))
    run(*inputs, "-filter_complex_script", OUT / "audio2.txt", "-map", "[aout]", "-c:a", "pcm_s16le", OUT / "audio2.wav")

    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
           "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
           "Style: Sub,Helvetica Neue,36,&H00F4F4F4,&H8C0A0806,&H8C0A0806,0,0,3,12,0,2,320,320,70", "",
           "[Events]", "Format: Layer, Start, End, Style, Text"]
    final_at = starts["card-final"]
    for t, d, p, text in placed:
        if t < final_at:
            ass.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + d + 0.2)},Sub,{{\\fad(120,120)}}{text}")
    (OUT / "subs2.ass").write_text("\n".join(ass))
    (OUT / "pitch-script.txt").write_text("\n".join(f"{int(t // 60)}:{t % 60:05.2f}  {text}" for t, d, p, text in placed))

    run("-i", OUT / "video2.mp4", "-i", OUT / "audio2.wav",
        "-vf", f"subtitles={OUT / 'subs2.ass'}:fontsdir=/System/Library/Fonts,fade=t=in:st=0:d=1,fade=t=out:st={total - 1.8:.2f}:d=1.8",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "256k",
        "-shortest", "-movflags", "+faststart", OUT / "TanyaCCTV-pitch.mp4")
    print("done:", OUT / "TanyaCCTV-pitch.mp4", f"{duration(OUT / 'TanyaCCTV-pitch.mp4'):.1f} s")


if __name__ == "__main__":
    main()
