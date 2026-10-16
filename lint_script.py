#!/usr/bin/env python3
"""
Flag places a kinetic script should be using a graphic instead of prose.

The engine supports iconned bullet lists and numbered cards, but it will not add
them on its own, and relying on whoever writes the script to remember is how they
got missed for the first six videos. This finds the moments mechanically.

Two patterns, both taken from what the reference ads actually do:

  bullets  a run of negations or a "you don't need" list. On screen these should be
           red crossed items with a green ticked one for the affirmative, not a
           sentence. Three plain sentences in a row that all start the same way is
           the usual tell.

  cards    an enumerated triad. "Leads, sales, delivery." "One. Two. Three."
           The reference always boxes these.

    python3 lint_script.py script.json
"""
import json, re, sys, pathlib

NEG = re.compile(r"^\s*(not|you do not need|you don't need|no |stop )", re.I)
ORD = re.compile(r"^\s*(one|two|three|first|second|third|1\.|2\.|3\.)\b", re.I)

def sentences(spans):
    txt = " ".join(s[0] for s in spans)
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", txt) if x.strip()]

def main():
    job = json.loads(pathlib.Path(sys.argv[1]).read_text())
    beats = job["beats"]
    has_b = any(b.get("bullets") for b in beats)
    has_c = any(b.get("cards") for b in beats)
    findings = []

    for i, b in enumerate(beats):
        if not b.get("spans"):
            continue
        ss = sentences(b["spans"])
        negs = [s for s in ss if NEG.match(s)]
        if len(negs) >= 2:
            findings.append((i, "bullets",
                f"{len(negs)} negations in a row: " + " / ".join(s[:40] for s in negs[:3])))
        ords_ = [s for s in ss if ORD.match(s)]
        if len(ords_) >= 2:
            findings.append((i, "cards",
                "enumerated list: " + " / ".join(s[:34] for s in ords_[:3])))
        # a bare triad of very short sentences is nearly always a card moment
        short = [s for s in ss if len(s.split()) <= 3]
        if len(short) >= 3:
            findings.append((i, "cards", "short triad: " + " / ".join(short[:3])))

    print(f"{pathlib.Path(sys.argv[1]).name}: bullets block {'yes' if has_b else 'NO'}, "
          f"cards block {'yes' if has_c else 'NO'}")
    if not findings:
        print("  no prose that obviously wants a graphic")
    for i, kind, why in findings:
        print(f"  beat {i}: consider a {kind} block  ->  {why}")
    if findings and not (has_b or has_c):
        print("\n  This script has graphic moments written as prose and no graphic blocks.")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
