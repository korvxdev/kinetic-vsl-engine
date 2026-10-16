---
name: kinetic-vsl-engine
description: Build kinetic-typography vertical video ads. Navy ground, no footage, full sentences on screen with each word lighting up as it is spoken, colour carrying meaning, closing on a CTA button. Use when the user wants a typography-only video ad, a kinetic text ad, or a video ad with no B-roll and no face.
---

# Kinetic VSL Engine

Typography-only vertical video ads. **No footage anywhere.** The entire frame is type
on a navy ground.

Nothing is generated except the voiceover, so the video itself costs nothing to make.
Once a script is written the render is free, which makes this the volume format: ten
variants cost the same as one.

## The format

Vertical 1080x1920 at 30fps, landing 60 to 70 seconds.

1. **The whole beat is on screen at once**, dimmed to 30 percent, and each word lights
   to full colour as it is spoken. That progressive illumination is the entire mechanic.
   It is not a caption that replaces itself, it is a paragraph filling in.
2. **Colour carries meaning**, it is never decoration:
   - `pain` coral `#F86060` for the cost of staying put
   - `win` cyan `#38D8F8` for the mechanism, the identity, the CTA
   - `money` green `#48D878` for money outcomes only
   - `plain` white `#F0F0F8` for everything else
3. **Open on a number.** A bare statistic, stacked on its own lines, before any claim.
   Two or three short figures that imply the whole problem.
4. **One specific story beat.** Not a testimonial, a short third-person example.
5. **Rule out the alternatives** before naming the mechanism, so the viewer stops
   mentally reaching for the thing they have already tried.
6. **Close on a cyan pill button plus a down arrow.**

Write **170 to 190 words**. The voice reads at roughly 2.8 words per second once
tightened, which puts you in the 60 to 70 second pocket.

## Per-client palette

The role meanings never change, only the hues. Pass a `palette` in the job JSON to put
the format in a client's colours:

```json
"palette": {"plain": "#F0EDE4", "pain": "#E8705C", "win": "#E8B84B", "money": "#7FD4A8"}
```

Brand values usually need brightening first. A deep brand red sits too close to the navy
ground to register as an accent.

## Graphics are the default, not an extra

Two graphic beat types exist and **you look for a place to use each one on every
script, without being asked**. Shipping a kinetic ad as pure prose when it had an
obvious list or triad in it is a miss, not a stylistic choice.

| Beat type | Use it when the script has |
|---|---|
| `bullets` | A run of negations, or a "you don't need" list. Red crossed items for what it is not, one green ticked item for what it is |
| `cards` | An enumerated triad. One, two, three. Numbered outline boxes, stacking |

```json
{"bullets": {"title": "Not what you think", "items": [
    ["cross", "You do not need a bigger list"],
    ["cross", "You do not need more traffic"],
    ["check", "You need the offer to answer one question"]]}}

{"cards": ["Leads.", "Sales.", "Delivery."]}
```

Both reveal one item at a time, each on its own first spoken word, so nothing appears
before it is mentioned. Their text counts toward the voiceover like any other beat.

Card labels and bullet titles do not wrap, so keep card labels to one or two short words
and bullet titles under about four. Bullet item text does wrap.

**Run the linter before rendering.** It finds the moments mechanically rather than
relying on anyone remembering:

```bash
python3 lint_script.py script.json
```

It exits non-zero when a script contains prose that clearly wants a graphic and has no
graphic blocks at all.

**Use them sparingly.** Two moments in a sixty second ad is right. The format's power
is that the type carries everything, and a graphic on every beat turns it into a
different, busier format.

## Running it

```bash
python3 kinetic_vsl.py script.json            # VO + word timings, then stop
python3 tighten_vo.py <root>/vo <slug>        # if the read came back under 2.6 w/s
python3 kinetic_vsl.py script.json --render   # build the video
```

Always run the first step alone and read the reported words per second before rendering.
Tightening after the fact is cheap; re-rendering is not.

Script format. Every span is `[text, role]`, roles as above:

```json
{
  "root_dir": "/path/to/batch",
  "slug": "client-angle",
  "title": "Client - Angle - v1",
  "voice": "CwhRBWXzGAHq8TQ4Fs17",
  "font_size": 76,
  "beats": [
    {"spans": [["300 dials.", "pain"], ["4 conversations.", "pain"]]},
    {"spans": [["The fix is", "plain"], ["live transfers.", "win"]]},
    {"cta": "Check capacity\nin your territory"}
  ]
}
```

Optional top-level keys: `palette`, `lead` (caption lead offset, default 0.09s),
`max_words_per_card` (default 16), `music` (path to a bed).

## Two things that will bite you

**Numerals expand in the voice.** The script says `300`, the voice says "three hundred",
so the script and the transcript are different lengths. A naive one-to-one walk hands the
wrong timestamp to every word after the first number and the colours light up out of sync.
`align()` maps them with difflib and spreads replaced runs evenly. Do not remove it.

**The accent bloom must be additive.** Blending toward a mostly black glow layer darkens
the whole frame, and it compounds per accent word, so a line with three accents comes out
visibly blacker than its neighbours. It uses `ImageChops.screen`. Check background
luminance is flat across frames after any change to the renderer.

## A note on the background

There is no film grain on the navy ground, and there should not be. An earlier version
added two octaves of it after an 8x8 noise measurement came back at 6.33. That
measurement was wrong: the patches were catching the dot lattice, not a grain field. A
proper high-pass and median-absolute-deviation measurement puts the reference at sigma
0.00. Grain made it look like static and tripled the file size. Do not add it back.

The dot lattice is real and measured: 54px pitch on both axes, autocorrelation 0.86.

## QA before you ship

- `ffprobe` duration and dimensions
- Contact sheet across the whole ad, and actually look at every frame
- Background luminance sampled per frame, must be flat. Standard deviation under about
  1.5 across sampled frames means the bloom is still additive
- Audio ends before the video does, so the CTA card holds. Two seconds of tail is right
- No word on screen that is not in the script. The renderer draws from the script, never
  from the transcript, so transcription misspellings cannot reach the frame
- Pick one spelling convention and hold it across the batch
