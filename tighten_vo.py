#!/usr/bin/env python3
"""
Tighten an ElevenLabs VO: cap the silence between words, then nudge tempo.

Most eleven_v3 presets read this format at ~2.2 words/sec. It wants ~2.8 w/s to land in
the 60-70s pocket. Re-rolling the VO does not fix it, the model paces the same way every
time, so the fix is in post: cut the dead air, then a light tempo bump.

Rewrites <slug>.wav and <slug>.words.json in place (originals kept as *_raw.*), so
`kinetic_vsl.py --render` picks up the tightened timings with no other change.

    python3 tighten_vo.py <vo_dir> <slug> [--max-gap 0.35] [--keep 0.22] [--tempo 1.05]
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path


def probe(p):
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(p)]).decode().strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vo_dir"); ap.add_argument("slug")
    ap.add_argument("--max-gap", type=float, default=0.35)
    ap.add_argument("--keep",    type=float, default=0.22)
    ap.add_argument("--tempo",   type=float, default=1.05)
    ap.add_argument("--head",    type=float, default=0.15, help="silence left before word 1")
    ap.add_argument("--tail",    type=float, default=0.45, help="silence left after the last word")
    a = ap.parse_args()

    vo = Path(a.vo_dir)
    wav, wj = vo / f"{a.slug}.wav", vo / f"{a.slug}.words.json"
    raw_wav, raw_wj = vo / f"{a.slug}_raw.wav", vo / f"{a.slug}_raw.words.json"
    if not raw_wav.exists():                      # first run, preserve the originals
        shutil.copy2(wav, raw_wav); shutil.copy2(wj, raw_wj)

    words = json.loads(raw_wj.read_text())
    dur = probe(raw_wav)
    if not words:
        sys.exit("no words")

    # Keep-segments: every word, plus a capped slice of the silence that follows it.
    keeps, new_words, t = [], [], 0.0
    head = min(words[0]["start"], a.head)
    keeps.append((words[0]["start"] - head, words[0]["start"]))
    t += head
    for i, w in enumerate(words):
        nxt = words[i + 1]["start"] if i + 1 < len(words) else min(w["end"] + a.tail, dur)
        gap = nxt - w["end"]
        seg_end = w["end"] + (a.keep if gap > a.max_gap else gap)
        keeps.append((w["start"], seg_end))
        new_words.append({"text": w["text"],
                          "start": round(t / a.tempo, 3),
                          "end":   round((t + (w["end"] - w["start"])) / a.tempo, 3)})
        t += seg_end - w["start"]

    # Merge touching segments so ffmpeg gets as few trims as possible.
    merged = []
    for s, e in keeps:
        if merged and s - merged[-1][1] < 1e-4:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    parts = "".join(
        f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{i}];"
        for i, (s, e) in enumerate(merged))
    fc = (parts + "".join(f"[a{i}]" for i in range(len(merged)))
          + f"concat=n={len(merged)}:v=0:a=1[cat];[cat]atempo={a.tempo}[out]")

    out = vo / f"{a.slug}_tight.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(raw_wav), "-filter_complex", fc, "-map", "[out]",
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)], check=True)

    shutil.move(str(out), str(wav))
    wj.write_text(json.dumps(new_words, indent=2))
    new = probe(wav)
    print(f"{a.slug}: {dur:.1f}s -> {new:.1f}s   "
          f"{len(words)/dur:.2f} w/s -> {len(words)/new:.2f} w/s   "
          f"({len(merged)} segs, tempo {a.tempo})")


if __name__ == "__main__":
    main()
