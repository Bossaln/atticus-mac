#!/bin/bash
# Holt die neuen Änderungen vom Original (upstream/main) in den deutschen Branch, baut neu und schiebt sie in den Fork.
# Der eingebaute Auto-Updater folgt danach origin/deutsch, also diesem Fork.
set -e; cd "$(dirname "$0")/.."
[ "$(git branch --show-current)" = deutsch ] || { echo "Nicht auf dem Branch deutsch."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Es gibt nicht committete Änderungen. Erst committen oder verwerfen."; exit 1; }
git fetch -q upstream
if git merge-base --is-ancestor upstream/main HEAD; then echo "Schon aktuell."; exit 0; fi
git merge --no-edit upstream/main || { echo "Merge-Konflikt: lösen, committen, dann dieses Skript erneut starten."; exit 1; }
./build.sh
git push -q origin deutsch
echo "Aktualisiert auf $(git log -1 --format='%h %s' upstream/main)."
