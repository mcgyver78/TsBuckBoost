#!/bin/sh
# Gibt den by-id-Pfad des Buck-Boost aus, falls vorhanden.
# Der Wandler haengt an einem Silicon-Labs-CP210x-Wandler.
for f in /dev/serial/by-id/*CP210*; do
    [ -e "$f" ] && echo "$f" && exit 0
done
exit 1
