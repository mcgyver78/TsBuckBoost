#!/bin/sh
# Lists the CP210x ports by stable name. The Buck-Boost sits behind a Silicon
# Labs CP210x USB-to-serial bridge; which of these ports it actually is, the
# driver decides by asking. Handy for troubleshooting only.
for f in /dev/serial/by-id/*CP210* /dev/serial/by-id/*cp210*; do
    [ -e "$f" ] && echo "$f"
done
exit 0
