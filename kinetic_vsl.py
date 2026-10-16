#!/usr/bin/env python3
"""
Kinetic VSL engine. Typography-only vertical video ads, no footage.

The format:
  - 1080x1920, 30fps, 60 to 70s, voiceover driven
  - No B-roll at any point. The entire frame is type on a navy ground
  - The whole beat's text is laid out at once, dimmed, and each word lights up
    as it is spoken. That progressive illumination is the whole mechanic
  - Colour carries meaning, it is not decoration:
        pain  coral   the cost of staying put
        win   cyan    the mechanism, the identity, the CTA
        money green   money outcomes only
        plain white   everything else
  - Closes on a cyan pill button plus a down arrow

Why render rather than generate: the look is pure type, so a renderer gives exact
colour, exact wrap and exact timing every run, for free. An image model would
approximate all three.

    python3 kinetic_vsl.py script.json            # VO + timings, then stop
    python3 kinetic_vsl.py script.json --render    # full video
"""
import argparse, hashlib, json, math, os, pathlib, re, shutil, string, subprocess, sys
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
# Fonts live next to this script by default. Run setup.sh once to fetch Poppins,
# or point KINETIC_FONT_DIR at a directory holding Poppins-Bold.ttf and
# Poppins-SemiBold.ttf.
FONT_DIR = pathlib.Path(os.environ.get(
    "KINETIC_FONT_DIR", pathlib.Path(__file__).resolve().parent / "fonts"))
EL_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_v3")

# Measured off reference footage rather than guessed.
IN  = (8, 17, 34)        # ground
GLO = (14, 30, 56)       # legacy, kept for the static ground()
PEAK = (32, 70, 128)     # fitted to the reference profile, then lifted once the
                         # supersampled dots changed how much the lattice contributes
DOT_PITCH = 54           # measured: 54px lattice on both axes, autocorr 0.86
DOT_SOFT  = 1.0          # fitted: tighter than this aliases, softer and the dot smears
BULLET_RED   = (254, 97, 102)   # sampled off the reference bullet circles
BULLET_GREEN = (72, 216, 120)   # the affirmative counterpart, same weight
CARD_BORDER  = (47, 212, 219)   # card outline, brand teal
CARD_FILL    = (11, 22, 42)     # sampled: the card sits slightly darker than the ground
DOT_TINT  = (44, 82, 126)# fitted so a dot peaks ~23 over local ground, as the reference does
_CACHE = {}
ROLES = {
    "plain": (240, 240, 248),
    "pain":  (248, 96, 96),
    "win":   (56, 216, 248),
    "money": (72, 216, 120),
}
DIM = 0.30               # unspoken words sit at 30 percent

def el_key():
    """ELEVENLABS_API_KEY from the environment, or a .env beside this script."""
    k = os.environ.get("ELEVENLABS_API_KEY")
    if k:
        return k.strip()
    env = pathlib.Path(__file__).resolve().parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(
        "ELEVENLABS_API_KEY not set. Export it, or copy .env.example to .env "
        "and put your key in it.")

def probe(p):
    return float(subprocess.check_output(["ffprobe","-v","error","-show_entries",
        "format=duration","-of","default=nw=1:nk=1",str(p)]).decode().strip())

def generate_vo(key, voice, text, out_wav):
    import requests
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        headers={"xi-api-key": key, "accept": "audio/mpeg", "Content-Type": "application/json"},
        json={"text": text, "model_id": EL_MODEL,
              "voice_settings": {"stability": .35, "similarity_boost": .75,
                                 "style": .45, "use_speaker_boost": True}}, timeout=180)
    r.raise_for_status()
    mp3 = out_wav.with_suffix(".mp3"); mp3.write_bytes(r.content)
    subprocess.run(["ffmpeg","-y","-v","error","-i",str(mp3),"-ac","1","-ar","16000",
                    "-c:a","pcm_s16le",str(out_wav)], check=True)
    return probe(out_wav)

def transcribe(key, wav):
    import requests
    with open(wav,"rb") as f:
        r = requests.post("https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": key},
            files={"file": (wav.name, f, "audio/wav")},
            data={"model_id":"scribe_v1","tag_audio_events":"false",
                  "language_code":"en","timestamps_granularity":"word"}, timeout=240)
    r.raise_for_status()
    return [{"text":w["text"],"start":w["start"],"end":w["end"]}
            for w in r.json()["words"] if w.get("type")=="word"]

# ---------------------------------------------------------------- background
def split_beat(spans, maxw):
    """Break a long beat into cards of at most maxw words.

    Sentences first, then pack whole sentences into cards. Cutting purely on a word
    count lands breaks mid-clause ("with people who can | actually pay"), which reads
    worse than a slightly short card. Only a single sentence longer than maxw on its
    own gets split, and then on the nearest comma.
    """
    words = [(w, role) for text, role in spans for w in text.split()]
    if len(words) <= maxw:
        return [spans]

    sents, cur = [], []
    for w, role in words:
        cur.append((w, role))
        if w.rstrip('"\'').endswith((".", "!", "?")):
            sents.append(cur); cur = []
    if cur: sents.append(cur)

    # any sentence longer than maxw gets broken at a comma, else at maxw
    flat = []
    for s in sents:
        while len(s) > maxw:
            cut = max((i for i in range(len(s)) if i < maxw and s[i][0].endswith(",")),
                      default=maxw-1)
            flat.append(s[:cut+1]); s = s[cut+1:]
        if s: flat.append(s)

    cards, cur = [], []
    for s in flat:
        if cur and len(cur) + len(s) > maxw:
            cards.append(cur); cur = []
        cur.extend(s)
    if cur: cards.append(cur)

    out = []
    for c in cards:
        runs, last = [], None
        for w, role in c:
            if role == last: runs[-1][0] += " " + w
            else: runs.append([w, role]); last = role
        out.append([tuple(r) for r in runs])
    return out


def align(script_words, heard):
    """Map every script word to a start time from the transcript.

    Scribe hears "three hundred" where the script says "300", so the two lists are
    different lengths. difflib gives the matching blocks, and anything inside a
    replaced run is spread evenly across the time that run occupies.
    """
    import difflib
    nk = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    sm = difflib.SequenceMatcher(None, [nk(w) for w in script_words],
                                 [nk(w["text"]) for w in heard])
    starts = [None]*len(script_words)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2-i1):
                starts[i1+k] = heard[j1+k]["start"]
        else:
            t0 = heard[j1]["start"] if j1 < len(heard) else (heard[-1]["end"] if heard else 0)
            t1 = heard[j2-1]["end"] if j1 < j2 <= len(heard) else t0
            span = max(i2-i1, 1)
            for k in range(i1, i2):
                starts[k] = t0 + (t1-t0)*((k-i1)/span)
    last = 0.0
    for i, v in enumerate(starts):
        if v is None: starts[i] = last
        last = starts[i] = max(starts[i], last)
    return starts


def ground_frame(phase):
    """One frame of the ambient ground.

    Three things make a near-black gradient look clean, and the first two versions of
    this function had none of them.

    1. DITHER. A gradient running 14 to 34 has only 20 integer levels to work with, so
       quantising straight to 8 bit produces flat plateaus. Measured: 14 distinct levels
       across 1500px with runs up to 246px. That stepping is what reads as "pixely".
       Adding sub-level noise before the round dissolves the steps entirely.

    2. GRAIN. The reference is actually MORE banded than ours was, 7 levels with 384px
       runs, but its local 8x8 noise floor is 6.33 against our 1.97. The grain is what
       hides the banding and gives it the filmic quality. Dither alone looks clean but
       flat; grain is what makes it look shot rather than drawn.

    3. SUPERSAMPLED DOTS. Drawing the 54px lattice as single hard pixels and blurring
       by 1.1px aliases. Rendering the lattice at 3x and downsampling gives a properly
       round, properly soft dot.

    Profile and lattice pitch are both fitted to the reference, see git history.
    """
    import math
    import numpy as np
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = xx / W, yy / H

    def blob(cx, cy, rx, ry, amp):
        d = np.sqrt(((nx - cx) / rx) ** 2 + ((ny - cy) / ry) ** 2)
        return amp * np.clip(1.0 - d, 0.0, 1.0) ** 2.0

    g  = blob(0.50 + 0.05 * math.sin(phase * 2 * math.pi),
              0.34 + 0.03 * math.cos(phase * 2 * math.pi * 2), 1.05, 0.58, 1.00)
    g += blob(0.50 - 0.09 * math.sin(phase * 2 * math.pi * 2 + 1.1),
              0.62 + 0.05 * math.sin(phase * 2 * math.pi * 3 + 2.2), 0.62, 0.34, 0.30)

    vig = (1.0 - 0.18 * np.clip((ny - 0.55) / 0.45, 0, 1) ** 1.5)
    vig *= (1.0 - 0.18 * np.clip((np.abs(nx - 0.5) - 0.22) / 0.28, 0, 1) ** 1.6)

    base = np.array(IN, dtype=np.float32)
    peak = np.array(PEAK, dtype=np.float32)
    img = base[None, None, :] + (peak - base)[None, None, :] * g[..., None]
    img *= vig[..., None]

    # --- dots, supersampled ---------------------------------------------------
    key = ("dots", DOT_PITCH, DOT_SOFT)
    if key not in _CACHE:
        ss = 3
        hy, hx = np.mgrid[0:H*ss, 0:W*ss]
        lat = (((hx % (DOT_PITCH*ss)) < ss*3) & ((hy % (DOT_PITCH*ss)) < ss*3)).astype(np.uint8) * 255
        d = Image.fromarray(lat).resize((W, H), Image.LANCZOS)
        d = d.filter(ImageFilter.GaussianBlur(DOT_SOFT))
        arr = np.asarray(d, dtype=np.float32)
        _CACHE[key] = arr / max(arr.max(), 1e-6)
    # Dots stay largely uniform; the reference does not fade them much toward the
    # edges, so the floor is high.
    img += (_CACHE[key] * (0.55 + 0.45 * g))[..., None] * np.array(DOT_TINT, dtype=np.float32)

    # --- grain, then dither, then quantise ------------------------------------
    # Grain cycles with the loop so the seam stays invisible. Luma-only, because
    # per-channel noise on a near-black ground turns into coloured speckle.
    # NO GRAIN. An earlier version added two octaves of it, chasing an 8x8 noise
    # measurement of 6.33 taken off the reference. That measurement was wrong: the 8x8
    # patches were catching the dots, not a grain field. Measuring properly, with a
    # high-pass and a median absolute deviation so the sparse dots cannot skew it, the
    # reference comes back at sigma 0.00. It is perfectly smooth with crisp dots. The
    # grain made it look like static and pushed the file to 178MB. Do not add it back.
    #
    # Dither only, at sub-level amplitude. This is what kills the banding, and it is
    # invisible: it costs about 0.3 sigma against the reference's 0.00.
    img += np.random.default_rng(99).uniform(-0.5, 0.5, img.shape).astype(np.float32)
    return Image.fromarray(np.clip(img + 0.5, 0, 255).astype("uint8"), "RGB")


def ground():
    bg = Image.new("RGB",(W,H),IN)
    d  = ImageDraw.Draw(bg)
    # soft radial lift behind the type, so the card never reads as flat black
    cx, cy, rad = W//2, int(H*.42), int(W*.95)
    for i in range(44, 0, -1):
        t = i/44
        r = int(rad*t)
        c = tuple(int(IN[k] + (GLO[k]-IN[k])*(1-t)**1.7) for k in range(3))
        d.ellipse([cx-r, cy-int(r*.78), cx+r, cy+int(r*.78)], fill=c)
    return bg.filter(ImageFilter.GaussianBlur(70))

# ---------------------------------------------------------------- text layout
def load_font(sz, weight="Bold"):
    return ImageFont.truetype(str(FONT_DIR/f"Poppins-{weight}.ttf"), sz)

def norm(s):
    return re.sub(r"[^a-z0-9]","", s.lower())

def wrap(spans, font, maxw, draw):
    """spans = [(text, role)]. Returns lines of [(word, role)] fitted to maxw."""
    words = []
    for text, role in spans:
        for w in text.split():
            words.append((w, role))
    lines, cur = [], []
    for wd in words:
        trial = cur + [wd]
        s = " ".join(x[0] for x in trial)
        if draw.textlength(s, font=font) > maxw and cur:
            lines.append(cur); cur = [wd]
        else:
            cur = trial
    if cur: lines.append(cur)
    return lines

def render_beat(bg, spans, lit, size, out, headline=None, alpha=False):
    """lit = how many words are spoken so far. Everything past it sits dim."""
    im = Image.new("RGBA", (W, H), (0,0,0,0)) if alpha else bg.copy()
    if headline:
        im = draw_headline(im, headline)
    d = ImageDraw.Draw(im)
    font = load_font(size)
    maxw = int(W*0.80)
    lines = wrap(spans, font, maxw, d)
    lh = int(size*1.26)
    total = lh*len(lines)
    y = int(H*0.42) - total//2
    idx = 0
    for line in lines:
        lw = d.textlength(" ".join(w for w,_ in line), font=font)
        x = (W-lw)//2
        for word, role in line:
            base = ROLES.get(role, ROLES["plain"])
            col = base if idx < lit else tuple(int(IN[k]+(base[k]-IN[k])*DIM) for k in range(3))
            if idx < lit and role in ("win","money","pain"):
                # Bloom under the accent words. It must add light, never subtract it:
                # blending toward a mostly black glow layer darkens the whole frame and
                # compounds per accent word, so a line with three accents came out
                # visibly blacker than its neighbours. On the transparent layer the
                # glow carries its own alpha so it still reads as glow once the moving
                # ground shows through underneath.
                if im.mode == "RGBA":
                    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    ImageDraw.Draw(g).text((x, y), word, font=font, fill=col + (150,))
                    im = Image.alpha_composite(im, g.filter(ImageFilter.GaussianBlur(16)))
                else:
                    g = Image.new("RGB", (W, H), (0, 0, 0))
                    ImageDraw.Draw(g).text((x, y), word, font=font, fill=col)
                    g = g.filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v*0.55))
                    im = ImageChops.screen(im, g)
                d = ImageDraw.Draw(im)
            d.text((x,y), word, font=font, fill=col)
            x += d.textlength(word+" ", font=font)
            idx += 1
        y += lh
    im.save(out)

def draw_headline(im, text, size=46):
    """A pinned headline across the top for the opening seconds. The reference ads
    use one to state the promise before the voice has got there."""
    d = ImageDraw.Draw(im)
    font = load_font(size, "SemiBold")
    maxw = int(W*0.84)
    words, lines, cur = text.split(), [], []
    for w in words:
        if d.textlength(" ".join(cur+[w]), font=font) > maxw and cur:
            lines.append(" ".join(cur)); cur=[w]
        else: cur.append(w)
    if cur: lines.append(" ".join(cur))
    y = int(H*0.115)
    for l in lines:
        d.text(((W-d.textlength(l,font=font))//2, y), l, font=font, fill=ROLES["win"])
        y += int(size*1.24)
    return im


def _icon(d, cx, cy, r, kind, colour):
    """A filled circle with a tick or a cross knocked out of it, as the reference does."""
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=colour)
    w = max(3, int(r*0.30))
    if kind == "cross":
        o = int(r*0.42)
        d.line([(cx-o, cy-o), (cx+o, cy+o)], fill=(255,255,255), width=w)
        d.line([(cx-o, cy+o), (cx+o, cy-o)], fill=(255,255,255), width=w)
    else:
        d.line([(cx-r*0.46, cy+r*0.02), (cx-r*0.10, cy+r*0.40)], fill=(255,255,255), width=w)
        d.line([(cx-r*0.10, cy+r*0.40), (cx+r*0.50, cy-r*0.38)], fill=(255,255,255), width=w)


def render_bullets(bg, title, items, shown, size, out):
    """A short title with iconned list items appearing one at a time.

    Items reveal as whole units rather than word by word. That is what the reference
    does and it reads better: a half drawn bullet looks broken, where a half lit
    sentence reads as being spoken.
    """
    im = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(im)
    tf = load_font(int(size*0.92))
    bf = load_font(int(size*0.64), "SemiBold")
    icon_r = int(size*0.27)
    left = int(W*0.11)
    text_x = left + icon_r*2 + int(size*0.32)
    maxw = W - text_x - int(W*0.09)          # keep clear of the right edge

    # wrap each item, because a long bullet used to run straight off the frame
    wrapped, lh = [], int(size*0.84)
    for kind, text in items:
        words, lines, cur = text.split(), [], []
        for w in words:
            if d.textlength(" ".join(cur+[w]), font=bf) > maxw and cur:
                lines.append(" ".join(cur)); cur=[w]
            else: cur.append(w)
        if cur: lines.append(" ".join(cur))
        wrapped.append((kind, lines))

    # wrap the title too. Items have been wrapped since early on, but the title was
    # drawn as one centred line, so anything wider than the frame clipped off BOTH
    # edges at once and still looked deliberate in motion. Single line titles keep
    # their old spacing exactly: 1.08 + 0.42 is the 1.5 this used to add.
    tlh, tgap = int(size*1.08), int(size*0.42)
    tmaxw = int(W*0.82)
    tlines = []
    if title:
        cur = []
        for w in title.split():
            if d.textlength(" ".join(cur+[w]), font=tf) > tmaxw and cur:
                tlines.append(" ".join(cur)); cur=[w]
            else: cur.append(w)
        if cur: tlines.append(" ".join(cur))

    gap = int(size*0.52)
    total = (len(tlines)*tlh + tgap if tlines else 0) + sum(len(l)*lh + gap for _k, l in wrapped) - gap
    y = int(H*0.42) - total//2
    for ln in tlines:
        d.text(((W - d.textlength(ln, font=tf))//2, y), ln, font=tf, fill=ROLES["plain"])
        y += tlh
    if tlines:
        y += tgap
    for i, (kind, lines) in enumerate(wrapped):
        if i >= shown: break
        col = BULLET_GREEN if kind == "check" else BULLET_RED
        _icon(d, left + icon_r, y + icon_r, icon_r, kind, col)
        ty = y
        for ln in lines:
            d.text((text_x, ty), ln, font=bf, fill=ROLES["plain"])
            ty += lh
        y += len(lines)*lh + gap
    im.save(out)


def render_cards(bg, items, shown, size, out):
    """Numbered outlined cards, stacked, appearing one at a time."""
    im = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(im)
    nf = load_font(int(size*0.44), "SemiBold")
    lf = load_font(int(size*0.96))
    cw, ch, gap = int(W*0.70), int(size*1.62), int(size*0.42)
    total = len(items)*ch + (len(items)-1)*gap
    y = int(H*0.42) - total//2
    x = (W - cw)//2
    for i, label in enumerate(items):
        if i >= shown: break
        d.rounded_rectangle([x, y, x+cw, y+ch], radius=int(ch*0.22),
                            fill=CARD_FILL + (235,), outline=CARD_BORDER + (255,), width=3)
        num = f"{i+1:02d}"
        d.text((x + int(size*0.42), y + (ch - int(size*0.44))//2 - int(size*0.04)),
               num, font=nf, fill=CARD_BORDER)
        d.text((x + int(size*1.28), y + (ch - int(size*0.96))//2 - int(size*0.10)),
               label, font=lf, fill=ROLES["plain"])
        y += ch + gap
    im.save(out)


def render_cta(bg, label, out, size=54, alpha=False):
    im = Image.new("RGBA", (W, H), (0,0,0,0)) if alpha else bg.copy()
    d = ImageDraw.Draw(im)
    font = load_font(size, "SemiBold")
    lines = label.split("\n")
    tw = max(d.textlength(l, font=font) for l in lines)
    pad_x, pad_y = 54, 34
    bw, bh = int(tw+pad_x*2), int(size*1.3*len(lines)+pad_y*2)
    bx, by = (W-bw)//2, int(H*0.42)-bh//2
    cy = ROLES["win"]
    glow = Image.new("RGBA",(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.rounded_rectangle([bx,by,bx+bw,by+bh], radius=22, fill=cy+(110,))
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    if alpha:
        im = Image.alpha_composite(im, glow)
    else:
        im = Image.blend(im, glow.convert("RGB"), .40)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([bx,by,bx+bw,by+bh], radius=22, fill=cy)
    ty = by+pad_y
    for l in lines:
        d.text(((W-d.textlength(l,font=font))//2, ty), l, font=font, fill=(10,18,34))
        ty += int(size*1.3)
    # Draw the arrow, do not typeset it. Poppins has no U+2193, so the glyph fell back
    # to tofu. A shape also scales cleanly and cannot be affected by a font swap.
    ax, ay = W//2, by+bh+58
    shaft, head = 52, 26
    d.line([(ax, ay), (ax, ay+shaft)], fill=cy, width=9)
    d.polygon([(ax-head, ay+shaft-6), (ax+head, ay+shaft-6), (ax, ay+shaft+head+2)], fill=cy)
    im.save(out)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script"); ap.add_argument("--render", action="store_true")
    a = ap.parse_args()

    job = json.loads(pathlib.Path(a.script).read_text())
    # Per-client palette override. The role meanings never change, only the hues, so a
    # client's own red and teal can drive the ad without touching the format. Brand
    # values usually need brightening first: a deep brand red sits too close to the
    # navy ground to read as an accent.
    for k, v in (job.get("palette") or {}).items():
        if k in ROLES and isinstance(v, str):
            ROLES[k] = tuple(int(v.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    root = pathlib.Path(job["root_dir"]); slug = job["slug"]
    vo_dir = root/"vo"; frm = root/"frames"; dest = root/"READY FOR REVIEW"
    for p in (vo_dir, dest): p.mkdir(parents=True, exist_ok=True)

    beats = job["beats"]
    def beat_text(b):
        if b.get("spans"):   return " ".join(s[0] for s in b["spans"])
        if b.get("bullets"): return " ".join([b["bullets"].get("title","")] +
                                             [i[1] for i in b["bullets"]["items"]]).strip()
        if b.get("cards"):   return " ".join(b["cards"])
        return ""
    spoken = " ".join(x for x in (beat_text(b) for b in beats) if x)

    wav = vo_dir/f"{slug}.wav"
    wj  = vo_dir/f"{slug}.words.json"
    key = el_key()

    # The VO is cached on disk, but it must be invalidated when the script changes.
    # Keying the cache on the slug alone silently reuses the old audio after an edit
    # and aligns the new script against the old transcript, which renders a broken
    # video with no error. Fingerprint the spoken text instead. tighten_vo.py rewrites
    # the wav in place without changing the words, so tightening does not invalidate.
    sig_f = vo_dir/f"{slug}.vo.sig"
    sig = hashlib.sha256(
        (spoken + "|" + job.get("voice", "CwhRBWXzGAHq8TQ4Fs17")).encode()).hexdigest()
    stale = (not wav.exists()) or (not sig_f.exists()) or sig_f.read_text().strip() != sig
    if stale and wav.exists():
        print("Script or voice changed since the cached VO. Regenerating.")
        for f in (wav, wj, vo_dir/f"{slug}_raw.wav", vo_dir/f"{slug}_raw.words.json"):
            if f.exists(): f.unlink()

    if not wav.exists():
        print("Generating VO...")
        generate_vo(key, job.get("voice","CwhRBWXzGAHq8TQ4Fs17"), spoken, wav)
        sig_f.write_text(sig)
    dur = probe(wav)

    if not wj.exists():
        print("Transcribing for word timings...")
        wj.write_text(json.dumps(transcribe(key, wav), indent=2))
    words = json.loads(wj.read_text())
    print(f"VO {dur:.1f}s, {len(words)} words, {len(words)/dur:.2f} w/s")

    # Align script words to transcript words. These drift because the voice expands
    # numerals ("300" is spoken as "three hundred") and normalises spelling, so a
    # naive 1:1 walk hands the wrong timestamp to every word after the first number
    # and the colours light up out of sync with the voice.
    script_words = [w for b in beats for w in beat_text(b).split()]
    starts = align(script_words, words)
    if len(script_words) != len(words):
        print(f"  aligned {len(script_words)} script words to {len(words)} spoken words")

    if not a.render:
        print("VO and timings ready. Re-run with --render to build the video.")
        return

    if frm.exists(): shutil.rmtree(frm)
    frm.mkdir()
    bg = ground()

    # Walk beats, assigning each its slice of the word timeline.
    # Light each word a fraction BEFORE it is spoken. Landing exactly on the onset
    # reads as late, because the eye has to find the word after the ear has heard it.
    LEAD = job.get("lead", 0.09)
    # A card that holds more than ~16 words sits on screen filling in for 6 seconds or
    # more and the ad feels slow. Split long beats so the frame changes often.
    MAXW = job.get("max_words_per_card", 16)
    hl_until = job.get("headline_seconds", 0)
    headline = job.get("headline")

    seq, wi = [], 0
    for b in beats:
        if b.get("cta"):
            seq.append(("cta", b["cta"], None, None)); continue

        if b.get("bullets"):
            spec = b["bullets"]
            tw = len(spec.get("title","").split())
            # the title holds alone while it is spoken, then each item lands on its
            # own first word, so a bullet never appears before it is mentioned
            if tw:
                seq.append(("bullets", (spec.get("title"), spec["items"], 0),
                            None, max(0.0, starts[wi] - LEAD)))
            k = wi + tw
            for i, (_kind, text) in enumerate(spec["items"]):
                seq.append(("bullets", (spec.get("title"), spec["items"], i+1),
                            None, max(0.0, starts[k] - LEAD)))
                k += len(text.split())
            wi = k
            continue

        if b.get("cards"):
            k = wi
            for i, label in enumerate(b["cards"]):
                seq.append(("cards", b["cards"], i+1, max(0.0, starts[k] - LEAD)))
                k += len(label.split())
            wi = k
            continue

        cards = split_beat(b["spans"], MAXW)
        for card in cards:
            n = sum(len(s[0].split()) for s in card)
            for k in range(n):
                tin = max(0.0, starts[wi+k] - LEAD)
                hl = headline if (headline and tin < hl_until) else None
                seq.append(("beat", card, k+1, tin, hl))
            wi += n
    print(f"Rendering {len(seq)} states across {sum(1 for s in seq if s[0]=='beat')} word steps...")

    # Render one PNG per distinct state, then build a concat list timed to the VO.
    times, files, cta_i = [], [], None
    for i,item in enumerate(seq):
        kind, payload, lit, tin = item[0], item[1], item[2], item[3]
        hl = item[4] if len(item) > 4 else None
        p = frm/f"{i:05d}.png"
        if kind == "bullets":
            title, items, shown = payload
            render_bullets(bg, title, items, shown, job.get("font_size",76), p)
            times.append(tin); files.append(p)
        elif kind == "cards":
            render_cards(bg, payload, lit, job.get("font_size",76), p)
            times.append(tin); files.append(p)
        elif kind == "cta":
            render_cta(bg, payload, p, alpha=True)
            cta_i = i
            times.append((words[-1]["end"] if words else dur) + job.get("hold", 0.7))
            files.append(p)
        else:
            render_beat(bg, payload, lit, job.get("font_size",76), p, hl, alpha=True)
            times.append(tin); files.append(p)
        if (i+1) % 25 == 0: print(f"  {i+1}/{len(seq)}")

    # The voice usually ends within a fraction of a second of the file, and the tighten
    # pass trims the tail further, so the CTA card would get a few frames and then be
    # cut off by -shortest. Pad the audio so the last line holds fully lit, then the
    # button gets real screen time.
    HOLD, CTA_T = job.get("hold", 0.7), job.get("cta_seconds", 2.6)
    last_word_end = words[-1]["end"] if words else dur
    pad = max(0.0, (last_word_end + HOLD + CTA_T) - dur)
    muxwav = wav
    if pad > 0.05:
        muxwav = root/"vo"/f"{slug}_padded.wav"
        subprocess.run(["ffmpeg","-y","-v","error","-i",str(wav),
                        "-af", f"apad=pad_dur={pad:.3f}", str(muxwav)], check=True)
        print(f"  padded {pad:.1f}s of silence so the CTA can hold")
    total = probe(muxwav)

    # Hold the final beat fully lit before the button appears.
    cta_start = last_word_end + HOLD
    concat = root/"concat.txt"
    with open(concat,"w") as f:
        for i,p in enumerate(files):
            if i+1 < len(times):
                end = times[i+1]
            else:
                end = total
            if i == len(files)-1 and files[-1].name.endswith(".png") and cta_i is not None and i == cta_i:
                end = total
            d = max(end - times[i], 1.0/FPS)
            f.write(f"file '{p.resolve()}'\nduration {d:.4f}\n")
        f.write(f"file '{files[-1].resolve()}'\n")

    # The ground is built once as a seamless loop and the text is composited over it.
    # Rendering a fresh background for all ~2,000 output frames in PIL would take
    # fifteen minutes a video; a loop plus an overlay takes seconds and looks the same.
    LOOP_S = job.get("bg_loop_seconds", 10)
    bgdir = root/"bgloop"
    if not bgdir.exists() or len(list(bgdir.glob("*.png"))) != LOOP_S*FPS:
        if bgdir.exists(): shutil.rmtree(bgdir)
        bgdir.mkdir()
        n = LOOP_S*FPS
        print(f"Rendering {n}-frame background loop...")
        for i in range(n):
            ground_frame(i/n).save(bgdir/f"{i:05d}.png")
    bgvid = root/"bgloop.mp4"
    if not bgvid.exists():
        subprocess.run(["ffmpeg","-y","-v","error","-framerate",str(FPS),
            "-i",str(bgdir/"%05d.png"),"-c:v","libx264","-crf","14","-preset","slow","-pix_fmt","yuv420p", str(bgvid)], check=True)

    out = dest/f"{job['title']}.mp4"
    subprocess.run(["ffmpeg","-y","-v","error",
        "-stream_loop","-1","-i",str(bgvid),
        "-f","concat","-safe","0","-i",str(concat),
        "-i",str(muxwav),
        "-filter_complex","[0:v]scale=%d:%d,fps=%d[bg];[1:v]fps=%d[tx];[bg][tx]overlay=0:0:format=auto,format=yuv420p[v]" % (W,H,FPS,FPS),
        "-map","[v]","-map","2:a",
        # tune=grain plus a low crf: without it x264 treats the grain as noise and
        # denoises it out, which puts the banding straight back. aq-mode 3 biases bit
        # allocation toward dark areas, which is the entire frame here.
        "-c:v","libx264","-crf","17","-preset","slow",
        "-x264-params","aq-mode=3:aq-strength=1.0",
        "-r",str(FPS),"-c:a","aac","-b:a","192k","-ar","48000","-ac","2","-shortest",
        "-movflags","+faststart", str(out)], check=True)
    print(f"Done: {out}  ({probe(out):.1f}s)")

if __name__ == "__main__":
    main()
