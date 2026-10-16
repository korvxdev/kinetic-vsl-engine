# Kinetic VSL Engine

A Claude Skill that builds kinetic-typography vertical video ads. No footage, no stock,
no B-roll. The whole frame is type on a navy ground, each word lighting up as it is
spoken, closing on a CTA button.

Because nothing is generated except the voiceover, the video costs essentially nothing
to produce. Write a script, get a 1080x1920 MP4. Write ten, get ten.

## What it does

You give Claude a script as JSON. It calls ElevenLabs for the voiceover, transcribes it
back for word-level timings, aligns those timings to your script, renders every frame
with PIL, and muxes the result with ffmpeg.

The output is a 60 to 70 second vertical MP4, ready for Meta, TikTok or YouTube Shorts.

Colour carries meaning rather than decoration. Four roles, assigned per span:

| Role | Default | Used for |
|---|---|---|
| `plain` | white | everything ordinary |
| `pain` | coral | the cost of staying put |
| `win` | cyan | the mechanism, the identity, the CTA |
| `money` | green | money outcomes only |

Pass a `palette` in the job to put the format into a client's brand colours without
changing what the roles mean.

## Install

Requires **Python 3.9+** and **ffmpeg**.

```bash
git clone https://github.com/korvxdev/kinetic-vsl-engine.git
cd kinetic-vsl-engine
pip install -r requirements.txt
./setup.sh                       # fetches the Poppins fonts
cp .env.example .env             # then put your ElevenLabs key in it
```

ffmpeg, if you do not have it:

```bash
brew install ffmpeg              # macOS
sudo apt install ffmpeg          # Debian/Ubuntu
```

## Use it with Claude

Copy the whole folder into your skills directory so Claude picks it up:

```bash
cp -r kinetic-vsl-engine ~/.claude/skills/
```

Then just ask:

> Make me a kinetic VSL for my offer. Here's the script.

Claude reads `SKILL.md`, writes the beats and colour roles, runs the linter, generates
the voiceover, checks the pacing, and renders. `SKILL.md` is the whole operating manual,
including the failure modes that are easy to reintroduce.

## Use it on its own

It is a normal Python program, Claude optional:

```bash
python3 kinetic_vsl.py script.json            # voiceover + word timings, then stops
python3 tighten_vo.py out/vo my-slug          # if the read came back under 2.6 w/s
python3 kinetic_vsl.py script.json --render   # build the video
```

Run the first step alone and read the reported words per second before rendering.
Tightening is cheap, re-rendering is not.

## The script format

```json
{
  "root_dir": "./out",
  "slug": "demo",
  "title": "Demo - Kinetic - v1",
  "voice": "CwhRBWXzGAHq8TQ4Fs17",
  "font_size": 76,
  "beats": [
    {"spans": [["300 dials.", "pain"], ["4 conversations.", "pain"]]},
    {"spans": [["The fix is", "plain"], ["live transfers.", "win"]]},
    {"bullets": {"items": [
        ["cross", "You do not need more leads"],
        ["check", "You need the right ones"]]}},
    {"cards": ["Leads.", "Sales.", "Delivery."]},
    {"cta": "Check capacity\nin your territory"}
  ]
}
```

`example-script.json` is a complete, runnable one.

**Write 170 to 190 words.** The voice reads at roughly 2.8 words per second once
tightened, which lands you in the 60 to 70 second pocket.

## The linter

```bash
python3 lint_script.py script.json
```

Exits non-zero when a script contains prose that obviously wants a `bullets` or `cards`
block and has neither. Graphics are the default in this format, not a flourish, and they
are the thing people forget.

## Cost

The render is free. The only spend is ElevenLabs text-to-speech for a 60-second read,
plus its transcription call for the word timings.

## Things that will bite you

Both are documented at length in `SKILL.md`, and both have been fixed once already:

**Numerals expand in the voice.** The script says `300`, the voice says "three hundred".
A naive one-to-one walk hands the wrong timestamp to every word after the first number.
`align()` maps them with difflib. Do not remove it.

**The accent bloom must be additive.** Blending toward a dark glow layer darkens the
whole frame and compounds per accent word. It uses `ImageChops.screen`. After any
renderer change, sample background luminance across frames and confirm it is flat.

## Licence

MIT, see `LICENSE`.

Poppins is not bundled. `setup.sh` fetches it from Google Fonts, where it is published
under the SIL Open Font License 1.1.
