"""Edit the demo film: recorded segments + narration lines anchored to on-screen moments + sound + subtitles.

Run after record.mjs:  python build.py
Outputs: out/TanyaCCTV-demo.mp4, out/voiceover.wav (narration only), out/script.txt (lines with times).
"""
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FF = (HERE / "ffmpeg-path").read_text().strip()
SEG, OUT, VO = HERE / "segments", HERE / "out", HERE / "vo"
FPS = 30
VOICE, RATE = "Daniel", "168"
OUT.mkdir(exist_ok=True)

# Film order. Each entry: segment name and the narration group it belongs to.
ORDER = ["card-intro", "card-elmina", "fall", "lobby",
         "history", "card-mission",
         "card-bukitraja", "parking1", "parking2", "parking3",
         "card-morning", "search", "hoodie",
         "card-map", "map", "bag",
         "evidence", "card-evidence",
         "card-outcome", "card-pillars", "card-logo"]

# Narration lines, each anchored to (segment, seconds into it) or (segment, "cue:<sound>", offset).
LINES = [
    ("card-elmina", 1.6, "City of Elmina. Seven forty-two in the evening."),
    ("fall", 1.0, "Uncle Lim takes his usual walk through the mall lobby... [[slnc 600]] and collapses."),
    ("fall", 8.9, "The lobby camera sees it all. But nobody is watching."),
    ("lobby", ("cue", "warning", -0.6), "Four seconds later, TanyaCCTV raises an alert. Someone has stopped moving, and may need help."),
    ("lobby", 10.0, "Officer Hafiz is already on his way."),
    ("history", 0.6, "In two thousand and nine, Sime Darby Property helped pioneer the Safe City Initiative in Ara Damansara. Twenty-two cameras, linked to the police."),
    ("history", 9.5, "Today, a township spans thousands of acres, with hundreds of cameras, recording more footage than any team could ever watch. So most of it is only seen after something has gone wrong."),
    ("card-mission", 0.5, "We built TanyaCCTV to change that. To turn a township's cameras, from recorders, into responders."),
    ("card-bukitraja", 0.9, "Bandar Bukit Raja. Three thirty in the morning."),
    ("parking1", 0.3, "This is TanyaCCTV's Live Monitor. The guard drew one zone, and marked one motorbike to protect."),
    ("parking1", ("cue", "notice", 0.1), "Movement in the parking bay."),
    ("parking1", ("cue", "warning", 0.0), "Then, a warning. Someone is at the motorbike, almost forty seconds before it is taken. Enough time to send a patrol."),
    ("parking2", ("cue", "alarm", -1.6), "And the moment the motorbike moves, the alarm."),
    ("parking3", 0.6, "One click opens the clip, and TanyaCCTV follows it, frame by frame."),
    ("card-morning", 0.9, "The next morning, another resident reports a stolen motorbike."),
    ("search", 0.4, "No more scrubbing through hours of footage. Officer Hafiz simply describes what he is looking for."),
    ("search", 6.2, "In seconds, the garage, at three minutes past four. A man, loading a motorbike onto a truck."),
    ("hoodie", 0.5, "When he walks out of view, TanyaCCTV knows, and picks him up again the moment he returns."),
    ("hoodie", 7.5, "Hours of footage, reduced to the moments that matter."),
    ("card-map", 0.4, "Every camera in the township lives on one map, so the team sees where things happen, not just what."),
    ("map", 3.0, "When someone needs to be found, TanyaCCTV follows them from camera to camera, and draws their route."),
    ("bag", 0.4, "And it watches over belongings too. At the transit hub, a bag left alone is flagged, before anyone reports it missing."),
    ("evidence", 0.5, "Every moment can become evidence. Clips are gathered into an investigation, and laid out on one timeline, across cameras."),
    ("evidence", 9.0, "Every clip is fingerprinted, so the report handed to the auxiliary police can be trusted."),
    ("card-evidence", 0.4, "And a person confirms every alert. TanyaCCTV says what it sees. Never who someone is, or what they intend."),
    ("card-outcome", 0.6, "Back at the mall, Uncle Lim is sitting up, talking to the paramedics. He was reached in minutes, because this time, someone was watching."),
    ("card-pillars", 0.8, "TanyaCCTV works with the cameras a township already has, runs on a single computer, and keeps every recording on site."),
    ("card-pillars", 7.6, "It finds any moment in seconds, and warns you before it happens."),
    ("card-logo", 2.0, "TanyaCCTV. Your township's cameras, now listening."),
]
SFX_VOLUME = {"heartbeat": 0.9, "impact": 0.8, "whoosh": 0.5, "key": 0.35, "notice": 0.5, "warning": 0.55, "alarm": 0.6}


def run(*args):
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def duration(path):
    out = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = out.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def encode(name):
    """Recorded frames (variable timing) -> constant 30 fps 1920x1080 video."""
    meta = json.loads((SEG / name / "meta.json").read_text())
    frames, end = meta["frames"], meta["end"]
    target = SEG / name / "video.mp4"
    lst = SEG / name / "frames.txt"
    fresh = target.exists() and target.stat().st_mtime > (SEG / name / "meta.json").stat().st_mtime
    with lst.open("w") as f:
        for i, (file, t) in enumerate(frames):
            nxt = frames[i + 1][1] if i + 1 < len(frames) else end
            f.write(f"file '{file}'\nduration {max(0.001, nxt - t):.4f}\n")
        f.write(f"file '{frames[-1][0]}'\n")
    if not fresh:
        run("-f", "concat", "-safe", "0", "-i", lst, "-vf", f"scale=1920:1080:flags=lanczos,fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", target)
    t0 = frames[0][1]
    cues, last = [], {}
    for sound, t in meta["cues"]:   # the alert list can report the same alert twice
        if sound == "key" or t - last.get(sound, -9) > 0.8:
            cues.append((sound, t - t0)); last[sound] = t
    return {"video": target, "length": end - t0, "cues": cues}


def say(i, text):
    path = VO / f"line{i:02d}.aiff"
    subprocess.run(["say", "-v", VOICE, "-r", RATE, "-o", str(path), text], check=True)
    return path, duration(path)


def ass_time(t):
    h, rem = divmod(max(0, t), 3600); m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def main():
    VO.mkdir(exist_ok=True)
    segs = {name: encode(name) for name in ORDER}
    lines = [(seg, anchor, text, *say(i, text)) for i, (seg, anchor, text) in enumerate(LINES)]

    # Place segments and lines; hold a segment's last frame when its narration runs past its end.
    start, holds, placed, clock, prev_end = {}, {}, [], 0.0, 0.0
    for name in ORDER:
        start[name] = clock
        length = segs[name]["length"]
        for seg, anchor, text, path, dur in [l for l in lines if l[0] == name]:
            if isinstance(anchor, tuple):
                _, sound, offset = anchor
                at = next((t for s, t in segs[name]["cues"] if s == sound), 0.0) + offset
            else:
                at = anchor
            t = max(clock + at, prev_end + 0.35)
            placed.append((t, dur, path, text)); prev_end = t + dur
        hold = max(0.0, prev_end + 0.4 - (clock + length))   # let narration started here finish on this shot
        holds[name] = hold
        clock += length + hold
    total = clock + 1.5
    print(f"film length {total:.1f} s; held: " + ", ".join(f"{n} +{h:.1f}s" for n, h in holds.items() if h > 0.05))

    # Video: segments in order, each padded with its hold; short fade at the very start and end.
    parts = []
    for name in ORDER:
        part = SEG / name / f"held-{holds[name]:.3f}.mp4"
        if not part.exists() or part.stat().st_mtime < segs[name]["video"].stat().st_mtime:
            run("-i", segs[name]["video"], "-vf", f"tpad=stop_mode=clone:stop_duration={holds[name]:.3f}", "-c:v", "libx264",
                "-preset", "medium", "-crf", "18", "-r", FPS, part)
        parts.append(part)
    concat = OUT / "parts.txt"; concat.write_text("".join(f"file '{p}'\n" for p in parts))
    run("-f", "concat", "-safe", "0", "-i", concat, "-c", "copy", OUT / "video-only.mp4")

    # Sound: narration, effects at their cues, a quiet drone bed, a heartbeat under the opening.
    inputs, filters, labels = [], [], []
    def add(path, at, vol=1.0):
        at = max(0.0, at)
        inputs.extend(["-i", str(path)]); k = len(inputs) // 2 - 1
        filters.append(f"[{k}:a]aresample=48000,volume={vol},adelay={int(at * 1000)}|{int(at * 1000)}[a{k}]"); labels.append(f"[a{k}]")
    for t, dur, path, text in placed:
        add(path, t, 1.0)
    for name in ORDER:
        for sound, t in segs[name]["cues"]:
            if sound == "heartbeat":
                for b in range(10):
                    add(HERE / "sfx/heartbeat.wav", start[name] + b * 0.95, SFX_VOLUME["heartbeat"] * (1 - b * 0.07))
            else:
                add(HERE / f"sfx/{sound}.wav", start[name] + t, SFX_VOLUME.get(sound, 0.5))
    add(HERE / "sfx/drone.wav", 0, 0.55)
    graph = ";".join(filters) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,atrim=0:{total:.2f},afade=t=out:st={total - 2.5:.2f}:d=2.5,alimiter=limit=0.95[aout]"
    script = OUT / "audio.txt"; script.write_text(graph)
    run(*inputs, "-filter_complex_script", script, "-map", "[aout]", "-c:a", "pcm_s16le", OUT / "audio.wav")
    # Narration only (to replace with a recorded human voice later).
    vin, vf, vl = [], [], []
    for i, (t, dur, path, text) in enumerate(placed):
        vin.extend(["-i", str(path)]); vf.append(f"[{i}:a]aresample=48000,adelay={int(t * 1000)}|{int(t * 1000)}[v{i}]"); vl.append(f"[v{i}]")
    (OUT / "vo.txt").write_text(";".join(vf) + ";" + "".join(vl) + f"amix=inputs={len(vl)}:normalize=0,atrim=0:{total:.2f}[vo]")
    run(*vin, "-filter_complex_script", OUT / "vo.txt", "-map", "[vo]", "-c:a", "pcm_s16le", OUT / "voiceover.wav")

    # Subtitles.
    clean = lambda s: __import__("re").sub(r"\[\[[^\]]*\]\]\s*", "", s)
    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
           "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV",
           "Style: Sub,Helvetica Neue,38,&H00F4F4F4,&H8C0A0806,&H8C0A0806,0,0,3,14,0,2,300,300,118", "",
           "[Events]", "Format: Layer, Start, End, Style, Text"]
    logo_at = start["card-logo"]
    for t, dur, path, text in placed:
        if t >= logo_at:
            continue   # the closing logo card speaks for itself
        ass.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + dur + 0.25)},Sub,{{\\fad(150,150)}}{clean(text)}")
    (OUT / "subs.ass").write_text("\n".join(ass))
    (OUT / "script.txt").write_text("\n".join(f"{int(t // 60)}:{t % 60:05.2f}  {clean(text)}" for t, dur, path, text in placed))

    run("-i", OUT / "video-only.mp4", "-i", OUT / "audio.wav",
        "-vf", f"subtitles={OUT / 'subs.ass'}:fontsdir=/System/Library/Fonts,fade=t=in:st=0:d=0.8,fade=t=out:st={total - 2:.2f}:d=2,tpad=stop_mode=clone:stop_duration=2",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", OUT / "TanyaCCTV-demo.mp4")
    print("done:", OUT / "TanyaCCTV-demo.mp4", f"{duration(OUT / 'TanyaCCTV-demo.mp4'):.1f} s")


if __name__ == "__main__":
    main()
