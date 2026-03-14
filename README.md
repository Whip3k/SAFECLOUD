# SAFE CLOUD

Samowystarczalny serwer plików napisany w czystym Pythonie 3 — bez żadnych zewnętrznych zależności webowych. Cały serwer to jeden plik `.py`.

---

## Szybki start

```bash
python serwer_1_15.py
```

| Adres | Opis |
|---|---|
| `http://localhost:8080` | Główny interfejs |
| `http://<twoje-ip>:8080` | Dostęp z innych urządzeń w sieci Wi-Fi |
| `http://localhost:8081` | Konsola administracyjna |

Przy każdym starcie generowane jest nowe losowe hasło do konta `admin` — pojawia się w terminalu. Aby je zobaczyć ponownie, wpisz `adminpass` w konsoli.

---

## Wymagania

- Python 3.9+
- `Pillow` — miniatury zdjęć i okładki audio *(opcjonalne)*
- `mutagen` — odczyt okładek z plików MP3/FLAC/M4A *(opcjonalne)*
- `psutil` — monitoring RAM i CPU *(opcjonalne)*

### Instalacja zależności

Minimalna instalacja (samo działanie serwera — bez żadnych dodatkowych paczek):
```bash
python serwer_1_15.py
```

Pełna instalacja (miniatury, okładki audio, monitoring RAM):
```bash
pip install Pillow mutagen psutil
```

Poszczególne paczki:

| Paczka | Do czego | Komenda |
|---|---|---|
| `Pillow` | Miniatury zdjęć i grafik | `pip install Pillow` |
| `mutagen` | Okładki albumów z MP3/FLAC/M4A/OGG | `pip install mutagen` |
| `psutil` | Monitoring RAM, CPU, wątków, I/O dysku | `pip install psutil` |
| `pdf2image` | *(nieużywane od v1.15)* | — |

---

## Struktura plików

```
serwer_1_15.py       # cały kod serwera
users.json           # konta użytkowników (hasła SHA-256 + role)
bans.json            # aktywne bany
shares.json          # aktywne linki udostępniania
version.json         # wersja i stage aplikacji
./SAFE CLOUD/        # pliki użytkowników (każdy ma swój podfolder)
```

### Format users.json

```json
{
  "admin": {
    "password": "e3b0c44...",
    "role": null
  },
  "janek": {
    "password": "5d41402...",
    "role": { "name": "VIP", "color": "#ff6600" }
  }
}
```

> Stary format `{ "user": "hash" }` oraz osobny plik `roles.json` są migrowane automatycznie przy pierwszym uruchomieniu. Stary `roles.json` zostaje przemianowany na `roles.json.bak`.

---

## Konfiguracja

Stałe na początku pliku:

| Stała | Domyślnie | Opis |
|---|---|---|
| `PORT` | `8080` | Port głównego serwera |
| `CONSOLE_PORT` | `8081` | Port konsoli WebSocket |
| `SESSION_TTL` | `30 dni` | Czas ważności sesji |
| `ADMIN_USER` | `"admin"` | Nazwa konta administratora |
| `OWNER_USER` | `"whip3kgt"` | Nazwa konta właściciela |
| `LOGIN_MAX_ATTEMPTS` | `10` | Max nieudanych logowań z IP w 60s |
| `RAM_WARN_MB` | `150` | Próg ostrzeżenia RAM |
| `RAM_CLEAN_MB` | `200` | Próg czyszczenia cache |
| `RAM_RESTART_MB` | `280` | Próg automatycznego restartu |

---

## Funkcje

### Zarządzanie plikami
- Widok kafelkowy z miniaturami
- Upload przez drag & drop lub przycisk
- Pobieranie plików i folderów (foldery pakowane do ZIP)
- Tworzenie folderów, zmiana nazwy, przenoszenie, usuwanie
- Zaznaczanie wielu plików i operacje grupowe
- Sortowanie po nazwie, rozmiarze i dacie
- Wyszukiwanie w bieżącym folderze

### Podgląd plików

| Typ | Rozszerzenia |
|---|---|
| Obrazy | `.jpg` `.jpeg` `.png` `.gif` `.webp` `.avif` `.svg` |
| Wideo | `.mp4` `.webm` `.mov` `.avi` `.mkv` |
| Audio | `.mp3` `.wav` `.ogg` `.flac` `.aac` `.m4a` `.opus` + okładka |
| PDF | `.pdf` |
| Kod / tekst | `.py` `.js` `.ts` `.html` `.css` `.json` `.xml` `.md` i inne |
| Archiwa | `.zip` `.tar` `.gz` `.bz2` `.xz` — lista zawartości + pobieranie plików |

### Udostępnianie plików
- Link do pliku z opcjonalnym TTL (czasem wygaśnięcia)
- Działa bez logowania
- Licznik pobrań
- Unieważnianie komendą `revoke`

### Sesje
- Cookie `session` z flagami `HttpOnly`, `SameSite=Strict`, `Max-Age=30 dni`
- Sesja odnawia się automatycznie przy każdej wizycie
- Wylogowanie, ban lub usunięcie konta natychmiast unieważnia sesję

---

## Role użytkowników

| Rola | Uprawnienia |
|---|---|
| `owner` | Dostęp do plików wszystkich użytkowników, nie można zbanować ani usunąć |
| `admin` | Dostęp do plików wszystkich użytkowników, hasło generowane przy starcie |
| niestandardowa | Kolorowa odznaka przy nazwie, widoczna w interfejsie |
| zwykły użytkownik | Dostęp tylko do własnego folderu |

---

## Monitoring RAM

Serwer sprawdza RAM co 15 sekund (wymaga `psutil`):

| Próg | Akcja |
|---|---|
| 150 MB | Ostrzeżenie w logach |
| 200 MB | Czyszczenie 50% cache miniaturek + wygasłe sesje i bany |
| 280 MB | Czyszczenie całego cache + automatyczny restart |

---

## Konsola administracyjna

Dostępna pod `http://localhost:8081` — logi na żywo i terminal komend przez WebSocket.

### Komendy

```
adminpass                          pokaż aktualne hasło admina
ban <user> <czas> <s/m/h/d> [powód]   zbanuj użytkownika na czas
ban <user> permanent [powód]       ban permanentny
unban <user>                       zdejmij bana
list bans                          lista aktywnych banów
list users                         lista użytkowników
list roles                         lista ról
list shares                        lista aktywnych linków udostępniania
add role <user> <nazwa> <#kolor>   nadaj rolę
remove role <user>                 usuń rolę
passwd <user> <hasło>              zmień hasło użytkownika
deluser <user> [--files]           usuń konto (--files usuwa też pliki)
revoke <token>                     unieważnij link udostępniania
disk                               zajęte miejsce per użytkownik
backup                             spakuj SAFE CLOUD do ZIP
status                             RAM, CPU, wątki, połączenia
ping                               ping do serwera lokalnego
ping ngrok                         ping do tunelu ngrok
clear logs                         wyczyść terminal
restart / reset / --r              zrestartuj serwer
--ver                              pokaż wersję aplikacji
--ver set <X.Y.Z> [stage]          ustaw wersję (alpha/beta/rc/stable/lts)
help                               lista wszystkich komend
```

---

## Bezpieczeństwo

- Hasła haszowane SHA-256
- Sesje z losowym tokenem 64-znakowym hex
- Rate-limiting — max 10 nieudanych logowań z jednego IP w 60 sekund
- Path traversal protection — użytkownik nie może wyjść poza swój folder
- Bany z opcjonalnym czasem wygaśnięcia, zapisywane w `bans.json`
