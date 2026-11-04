# Debian13_orginal — pełna VM Debian 13 (QEMU/KVM)

**Cel:** uruchomić **pełny, niezależny system Debian 13** jako gościa na fizycznym hoście KVM, a następnie uruchomić w nim aplikację `Debian13_orginal` z tego repo. To nie jest własny bootowalny obraz tego projektu; baza to oficjalny instalator Debiana.

## 1. Host (Linux x86_64 z /dev/kvm)

Wymaga obsługi VT-x/AMD-V, KVM, libvirt oraz uprawnienia do `qemu:///system`. Zwykły Codespace, przeglądarka i sesja ChatGPT **nie zapewniają** KVM. Dla serwera w chmurze upewnij się, że dostawca zezwala na nested virtualization. Potrzebne przynajmniej 4 GiB RAM dla VM (lepiej więcej) i 32 GiB miejsca na dysk VM.

Na hoście Debian 13 instalację zależności wykonaj **samodzielnie i świadomie**:

```bash
sudo apt update
sudo apt install --no-install-recommends qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst ovmf
```

Nie włączamy samodzielnie nowych usług ani dostępu sieciowego. Sprawdź stan `libvirtd` i prywatnej sieci `default` za pomocą `virsh -c qemu:///system net-list --all`. Jeśli jest nieaktywna, aktywuj ją samodzielnie po ocenie konfiguracji, np. `sudo virsh net-start default`. Nie udostępniaj VNC ani SSH całemu internetowi.

## 2. ISO i kontrola integralności

Pobierz odpowiednie **amd64 netinst** ze strony [Debian](https://www.debian.org/download) oraz oficjalny plik `SHA256SUMS` odpowiadający *dokładnie tej samej* wersji katalogu wydania. Zapisz lokalną ścieżkę ISO i 64-znakowy SHA-256 z podpisanego wykazu. Zweryfikuj także podpis wykazu zgodnie z instrukcją Debian; samo porównanie sumy nie potwierdza autentyczności, jeśli źródło sumy jest niesprawdzone.

## 3. Weryfikacja i jawne tworzenie VM

```bash
# W katalogu repozytorium — tylko odczyt stanu hosta:
bash debian13/virtualization/kvm-vm.sh --check

# Dopiero po weryfikacji hosta/obrazu i zatwierdzeniu zasobów:
export DEBIAN13_VM_ISO="/absolute/path/debian-13-amd64-netinst.iso"
export DEBIAN13_VM_ISO_SHA256="<sha256 z oficjalnego SHA256SUMS>"
bash debian13/virtualization/kvm-vm.sh --create
```

`--create` zakłada nową VM `debian13-original`, 2 vCPU, 4096 MiB RAM, dysk qcow2 32 GiB, NAT libvirt `default`, VNC tylko na loopback hosta. Nie nadpisuje istniejącej VM. Instalacja Debian odbywa się ręcznie z ISO przy użyciu lokalnego `virt-viewer` lub bezpiecznego tunelu SSH do VNC. Nie ustawiaj VNC na `0.0.0.0`.

Po instalacji sprawdź gościa przez `virsh -c qemu:///system list --all`, połącz się z VM i skonfiguruj użytkownika oraz SSH zgodnie z polityką serwera.

## 4. Uruchomienie aplikacji w gościu (nie na hoście KVM)

Wewnątrz VM, po zainstalowaniu Git, Python i Node jeśli potrzebny do testów:

```bash
git clone https://github.com/mmitek515-netizen/Debian_13.git
cd Debian_13
bash debian13/start-local.sh --check
bash debian13/start-local.sh
```

Aplikacja używa portów `127.0.0.1:3000` (GUI) i `127.0.0.1:8765` (API), wewnątrz VM. Udostępnij prywatne GUI tylko przez SSH forwarding do VM (`ssh -L 3000:127.0.0.1:3000 user@VM_IP` z hosta, który ma trasę do prywatnego IP VM), a nie przez wystawianie serwera Python lub nieautoryzowanego MCP publicznie.

## 5. Granice i odbiór

- Ten skrypt **nie uruchamia QEMU/KVM w ChatGPT**, nie steruje Twoim serwerem i nie uruchamia agentów samoczynnie.
- Testy GitHub Actions tego PR są testami offline/kontraktu, **nie** testami prawdziwej wirtualizacji na Twoim hoście.
- Zamknięcie tematu VM wymaga dowodów: `--check` na realnym hoście, prawdziwego utworzenia VM, `cat /etc/os-release` **wewnątrz** gościa, uruchomienia API/GUI, testów i dostępności tylko przez bezpieczne kanały.
- Następny etap: osobno skonfigurować autoryzowany most MCP/API do ChatGPT oraz rzeczywiste workery Alex, Aria, Astyria i Aurelius. Nie traktować ich profili jako działających procesów.
- Nie scalać automatycznie; PR wymaga przeglądu, zielonego CI i potwierdzenia wdrożenia na hostcie.
