#!/bin/bash
# Run from a commit-pinned checkout owned by the server administrator.
set -euo pipefail
umask 077
test "$(id -u)" = 0

repo=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
helper=/usr/local/sbin/rifas-pruebas-observe-writers
library=/usr/local/lib/rifas-pruebas
policy=/etc/sudoers.d/rifas-pruebas-observe-writers
for file in "$repo" "$repo/deployment" "$repo/deployment/arsys" "$repo/deployment/structure.py" \
            "$repo/deployment/arsys/rifas-pruebas-observe-writers"; do
    test ! -L "$file"
    test "$(stat -c %u -- "$file")" = 0
    mode=$(stat -c %a -- "$file")
    test "$((8#$mode & 0022))" = 0
done
for file in "$helper" "$library" "$policy"; do
    if [ -e "$file" ] || [ -L "$file" ]; then
        printf 'ERROR: ya existe %s\n' "$file" >&2
        exit 1
    fi
done

tmp=$(mktemp -d)
created_library=0
created_helper=0
created_policy=0
completed=0
cleanup() {
    if [ "$completed" -eq 0 ]; then
        if [ "$created_policy" -eq 1 ]; then rm -f -- "$policy"; fi
        if [ "$created_helper" -eq 1 ]; then rm -f -- "$helper"; fi
        if [ "$created_library" -eq 1 ]; then rm -rf -- "$library"; fi
    fi
    rm -rf -- "$tmp"
}
trap cleanup EXIT

printf '%s\n' 'dealfonsocom ALL=(root) NOPASSWD: /usr/local/sbin/rifas-pruebas-observe-writers ""' > "$tmp/sudoers"
chmod 0440 "$tmp/sudoers"
/usr/sbin/visudo -cf "$tmp/sudoers"
install -d -o root -g root -m 0755 "$library"
created_library=1
install -o root -g root -m 0644 "$repo/deployment/structure.py" "$library/structure.py"
install -o root -g root -m 0755 "$repo/deployment/arsys/rifas-pruebas-observe-writers" "$helper"
created_helper=1
install -o root -g root -m 0440 "$tmp/sudoers" "$policy"
created_policy=1
/usr/sbin/visudo -c
runuser -u dealfonsocom -- /usr/bin/sudo -n "$helper" > "$tmp/report.json"
/usr/bin/python3 -I -B -c 'import json, sys; report = json.load(sys.stdin); sys.exit(0 if report.get("complete") is True else "Visibilidad incompleta de escritores")' < "$tmp/report.json"
completed=1
echo "OK: observador de escritores de PRUEBAS instalado y verificado"
