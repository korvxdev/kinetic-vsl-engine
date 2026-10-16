#!/usr/bin/env bash
# Fetch the two Poppins weights the renderer needs.
# Poppins is published by Indian Type Foundry under the SIL Open Font License 1.1.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p fonts
BASE="https://raw.githubusercontent.com/google/fonts/main/ofl/poppins"
for w in Bold SemiBold; do
  if [ -f "fonts/Poppins-$w.ttf" ]; then
    echo "have  Poppins-$w.ttf"
  else
    echo "fetch Poppins-$w.ttf"
    curl -fsSL "$BASE/Poppins-$w.ttf" -o "fonts/Poppins-$w.ttf"
  fi
done
echo
echo "Fonts ready. Next:"
echo "  cp .env.example .env     and add your ElevenLabs key"
echo "  python3 kinetic_vsl.py example-script.json"
