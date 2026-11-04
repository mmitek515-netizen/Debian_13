#!/usr/bin/env bash
# Reuse the EXISTING VM_Gemini_4 Docker container and its persistent QCOW2 disk.
# Must run on the original Docker host / Codespace, not inside ChatGPT.
set -euo pipefail

CONTAINER='vm_gemini_4'
ACTION="${1:---check}"

usage() {
  cat <<'HELP'
Usage: bash debian13/virtualization/resume-existing-vm.sh [--check|--start|--help]
  --check   Read-only inspection of the previously created VM_Gemini_4 container.
  --start   Start that existing container, WITHOUT rebuilding or creating a VM.
  --help    Display this help.

Run only on the ORIGINAL host / Codespace with the VM's persistent Docker volume.
Does not create disks, download images, remove anything, publish ports or change settings.
HELP
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
case "$ACTION" in
  --help|-h) usage; exit 0 ;;
  --check|--start) [[ $# -le 1 ]] || fail 'Only one argument is supported.' ;;
  *) usage >&2; fail "Unsupported action: $ACTION" ;;
esac

command -v docker >/dev/null 2>&1 || fail 'Docker CLI unavailable on this host.'
docker info >/dev/null 2>&1 || fail 'Docker daemon unavailable; start the original Codespace or host first.'

if ! docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  fail "Existing container $CONTAINER was not found. Stopping: no new VM will be created. Check original Codespace/host."
fi

DATA_DIR="$(docker container inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$CONTAINER")"
[[ -n "$DATA_DIR" && -d "$DATA_DIR" ]] || fail 'Missing original /data mount. Refusing to start.'
[[ -s "$DATA_DIR/vm-gemini-4-restricted.qcow2" ]] || fail 'Existing VM disk absent or empty; refusing to create/reinitialize it.'
[[ -s "$DATA_DIR/debian-13-genericcloud-amd64.qcow2" ]] || fail 'Existing backing image absent or empty; refusing to start.'

STATE="$(docker container inspect --format '{{.State.Running}}' "$CONTAINER")"
case "$STATE" in true|false) ;; *) fail 'Unrecognized container state.' ;; esac
printf 'Found existing VM container: %s\nData directory: %s\nDocker running: %s\n' "$CONTAINER" "$DATA_DIR" "$STATE"
if [[ "$ACTION" == '--check' ]]; then
  printf 'Read-only inspection complete. Nothing was changed.\n'
  exit 0
fi
if [[ "$STATE" == 'true' ]]; then
  printf 'Existing container is already running; no action taken.\n'
else
  docker start "$CONTAINER" >/dev/null
  printf 'Start command submitted for existing VM container.\n'
fi

docker ps --filter "name=^/${CONTAINER}$" --format 'Container: {{.Names}}; status: {{.Status}}'
printf 'VM guest boot, Debian readiness, SSH and agent status still require independent checks.\n'
