#!/bin/sh
# Installed root-owned and invoked via the fixed production sudo rule.
set -eu
base=/var/www/vhosts/dealfonso.com
coord="$base/rifas-deployment/production"
root="$base/rifas"
control=/var/lib/rifas-production-control

case "${1-}" in
    --help|status|structure|plan|apply|recover) ;;
    *) printf '%s\n' 'Uso: rifas-produccion-deploy --help' >&2; exit 64 ;;
esac

exec /usr/bin/systemd-run --system --no-ask-password --quiet --wait --pipe --collect \
    --expand-environment=no -p "WorkingDirectory=$coord/checkout" \
    -p ProtectSystem=strict -p PrivateTmp=yes -p NoNewPrivileges=yes \
    -p 'InaccessiblePaths=-/run/systemd/private -/run/dbus/system_bus_socket' \
    -p "ReadWritePaths=$root $control" \
    -p "ReadOnlyPaths=$root/staging $base/rifas-deployment/staging /var/lib/rifas-pruebas-control" \
    /usr/bin/unshare --mount --pid --fork --mount-proc --kill-child \
    /usr/bin/setpriv --reuid=dealfonsocom --regid=psacln --init-groups \
    --bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs \
    /usr/bin/python3 -B -m deployment.deploy --config "$coord/config/deployment.json" "$@"
