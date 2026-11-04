#!/usr/bin/env bash
# Opt-in KVM VM provisioning. No host changes occur without --create.
set -euo pipefail

VM_NAME="${DEBIAN13_VM_NAME:-debian13-original}"
VM_RAM_MIB="${DEBIAN13_VM_RAM_MIB:-4096}"
VM_VCPUS="${DEBIAN13_VM_VCPUS:-2}"
VM_DISK_GIB="${DEBIAN13_VM_DISK_GIB:-32}"
VM_NETWORK="${DEBIAN13_VM_NETWORK:-default}"
ISO_PATH="${DEBIAN13_VM_ISO:-}"
ISO_SHA256="${DEBIAN13_VM_ISO_SHA256:-}"
ACTION="${1:---check}"

usage() {
  cat <<'HELP'
Debian13_orginal — Debian 13 VM provisioning (QEMU/KVM, libvirt)
Usage: bash debian13/virtualization/kvm-vm.sh [--help|--check|--create]
  --check   Read-only host diagnostics (default)
  --create  Create a NEW isolated VM from a verified Debian 13 amd64 netinst ISO

Required only for --create:
  DEBIAN13_VM_ISO=/absolute/path/debian-13-amd64-netinst.iso
  DEBIAN13_VM_ISO_SHA256=<64 hex chars from official Debian SHA256SUMS>
Optional: DEBIAN13_VM_NAME, DEBIAN13_VM_RAM_MIB (4096),
          DEBIAN13_VM_VCPUS (2), DEBIAN13_VM_DISK_GIB (32),
          DEBIAN13_VM_NETWORK (default)
No sudo, network changes, downloads or deletions are performed by this script.
HELP
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

case "$ACTION" in
  --help|-h) usage; exit 0 ;;
  --check|--create) [[ "$#" -le 1 ]] || fail 'Only one flag is supported.' ;;
  *) usage >&2; fail "Unknown action: $ACTION" ;;
esac

[[ "$VM_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$ ]] || fail 'Invalid VM name.'
[[ "$VM_NETWORK" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$ ]] || fail 'Invalid libvirt network name.'
for value in "$VM_RAM_MIB" "$VM_VCPUS" "$VM_DISK_GIB"; do
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail 'RAM, vCPUs, and disk size must be positive decimal integers.'
done
(( VM_RAM_MIB >= 2048 && VM_VCPUS >= 1 && VM_DISK_GIB >= 20 )) || fail 'Minimum: 2048 MiB RAM, 1 vCPU, 20 GiB disk.'

if [[ "$ACTION" == '--create' ]]; then
  [[ "$ISO_PATH" == /* && -f "$ISO_PATH" && -r "$ISO_PATH" ]] || fail 'Set DEBIAN13_VM_ISO to an accessible, absolute ISO file path.'
  [[ "$ISO_SHA256" =~ ^[[:xdigit:]]{64}$ ]] || fail 'Set DEBIAN13_VM_ISO_SHA256 from the official Debian SHA256SUMS.'
  command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required to verify the ISO.'
  printf '%s  %s\n' "$ISO_SHA256" "$ISO_PATH" | sha256sum --check --status - || fail 'ISO checksum mismatch; refusing to create the VM.'
fi

error_count=0
for executable in virsh virt-install; do
  if ! command -v "$executable" >/dev/null 2>&1; then
    printf 'MISSING: %s (install libvirt-clients / virtinst on the host)\n' "$executable" >&2
    (( error_count += 1 ))
  fi
done
if [[ ! -c /dev/kvm || ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  printf 'MISSING: usable /dev/kvm (CPU virtualization, host or nested virtualization permissions)\n' >&2
  (( error_count += 1 ))
fi
if command -v virsh >/dev/null 2>&1; then
  if ! virsh --connect qemu:///system list --all >/dev/null 2>&1; then
    printf 'UNAVAILABLE: libvirt qemu:///system (permissions or service)\n' >&2
    (( error_count += 1 ))
  elif ! virsh --connect qemu:///system net-info "$VM_NETWORK" 2>/dev/null | grep -Eq '^Active:[[:space:]]+yes'; then
    printf 'UNAVAILABLE: active libvirt network "%s" (activate it explicitly on host)\n' "$VM_NETWORK" >&2
    (( error_count += 1 ))
  fi
fi
if (( error_count > 0 )); then
  printf 'Prerequisites failed: %s. No VM was created.\n' "$error_count" >&2
  exit 2
fi

printf 'KVM/libvirt prerequisites OK. VM: %s; RAM: %s MiB; CPU: %s; disk: %s GiB; network: %s\n' \
  "$VM_NAME" "$VM_RAM_MIB" "$VM_VCPUS" "$VM_DISK_GIB" "$VM_NETWORK"
if [[ "$ACTION" == '--check' ]]; then
  printf 'Read-only diagnostic complete. Nothing was changed.\n'
  exit 0
fi

if virsh --connect qemu:///system dominfo "$VM_NAME" >/dev/null 2>&1; then
  fail "A VM named '$VM_NAME' already exists; refusing to overwrite it."
fi

virt-install \
  --connect qemu:///system \
  --name "$VM_NAME" \
  --memory "$VM_RAM_MIB" \
  --vcpus "$VM_VCPUS" \
  --disk "size=${VM_DISK_GIB},format=qcow2,bus=virtio" \
  --network "network=${VM_NETWORK},model=virtio" \
  --osinfo detect=on,require=off \
  --cdrom "$ISO_PATH" \
  --graphics vnc,listen=127.0.0.1 \
  --noautoconsole

printf 'VM created. Finish Debian installation with an authorized local VNC/virt-viewer session.\n'
