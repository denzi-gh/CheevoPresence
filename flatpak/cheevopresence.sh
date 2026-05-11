#!/usr/bin/env bash
# Entry-point wrapper installed to /app/bin/cheevopresence.
#
# Discord IPC socket location bridge:
# - Native Discord:  $XDG_RUNTIME_DIR/discord-ipc-{0..9}
# - Flatpak Discord: $XDG_RUNTIME_DIR/app/com.discordapp.Discord/discord-ipc-{0..9}
# - Snap Discord:    $XDG_RUNTIME_DIR/snap.discord/discord-ipc-{0..9}
#
# pypresence resolves the socket path using $XDG_RUNTIME_DIR then $TMPDIR.
# We search each candidate directory for an actual discord-ipc-0 socket file
# and set TMPDIR to whichever directory contains it, so pypresence always wins.
for _dir in \
    "${XDG_RUNTIME_DIR}/app/com.discordapp.Discord" \
    "${XDG_RUNTIME_DIR}/snap.discord" \
    "${XDG_RUNTIME_DIR}"; do
    if [ -S "${_dir}/discord-ipc-0" ]; then
        export TMPDIR="${_dir}"
        break
    fi
done

exec python3 -m desktop.shell.cli "$@"
