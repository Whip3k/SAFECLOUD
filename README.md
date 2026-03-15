# 🛡 SAFE CLOUD

Lokalny serwer chmury plików napisany w czystym Pythonie — zero zewnętrznych frameworków. Jeden plik, zero konfiguracji, działa od razu.

---

## Wymagania

**Python 3.8+** — jedyna bezwzględna zależność.

### Opcjonalne (rozszerzają funkcjonalność)

| Pakiet | Do czego |
|---|---|
| `Pillow` | Miniaturki obrazów i okładki audio |
| `mutagen` | Okładki z plików MP3 / FLAC / M4A / OGG |
| `psutil` | Statystyki serwera (RAM, CPU, dysk, sieć) |
| `ffmpeg` | Miniaturki wideo (musi być w PATH) |

```bash
pip install Pillow mutagen psutil
```

---

## Uruchomienie

```bash
python StartUp.py
```

| Adres | Opis |
|---|---|
| `http://localhost:8080` | Główny interfejs |
| `http://<twoje-ip>:8080` | Dostęp z sieci lokalnej (Wi-Fi) |
| `http://localhost:8081` | Konsola administracyjna |

Przy pierwszym uruchomieniu hasło admina jest generowane losowo i wypisywane w terminalu.

---

## Struktura plików

```
StartUp.py          ← cały serwer
users.json          ← konta użytkowników (hasła PBKDF2)
bans.json           ← aktywne bany
shares.json         ← aktywne linki udostępniania
totp.json           ← sekrety 2FA
maintenance.json    ← stan trybu konserwacji
version.json        ← wersja aplikacji
SAFE CLOUD/
  └── <username>/   ← pliki każdego użytkownika
backups/            ← automatyczne backupy ZIP
```

---

## Funkcje

### Zarządzanie plikami
- Upload strumieniowy (bez ładowania całego pliku do RAM)
- Drag & drop plików i folderów
- Tworzenie, usuwanie, zmiana nazwy, przenoszenie
- Pobieranie folderów jako ZIP
- Podgląd obrazów, wideo, audio, PDF, tekstu, archiwów ZIP
- Strumieniowanie wideo z HTTP Range (przewijanie bez pobierania)
- Miniaturki obrazów, wideo (ffmpeg) i okładki plików audio
- Sortowanie po nazwie / dacie / rozmiarze
- Wyszukiwanie w folderze
- Zaznaczanie wielu plików (pobieranie ZIP, usuwanie, przenoszenie)

### Udostępnianie
- Jednorazowe linki do pobierania plików
- Opcjonalny czas wygaśnięcia linku (w godzinach)
- Strona pobierania z odliczaniem czasu wygaśnięcia
- Link `＋/dl/<token>` — faktyczne pobranie dopiero po kliknięciu

### Bezpieczeństwo
- Hasła hashowane PBKDF2-HMAC-SHA256 z losową solą (260 000 iteracji)
- Automatyczna migracja starych hashów SHA-256 przy logowaniu
- Uwierzytelnianie dwuskładnikowe (TOTP / Google Authenticator)
- Propozycja ustawienia 2FA tuż po rejestracji
- Rate-limiting logowania (10 prób / 60 sek per IP)
- Ochrona przed path traversal (`safe_path`)
- Sesje z TTL 30 dni, automatyczne czyszczenie wygasłych
- HttpOnly + SameSite cookies

### System kont
- Rejestracja i logowanie
- Role: **Admin**, **Owner**, **Moderator**, użytkownicy z niestandardowymi rolami
- Bany czasowe (s/m/h/d) i permanentne
- Zmiana hasła, nazwy użytkownika, usunięcie konta

### Wygląd
- 6 motywów kolorystycznych: Mono, Niebieski, Zielony, Czerwony, Fioletowy, Różowy
- Tryb ciemny / jasny — każdy motyw dostępny w obu wariantach
- Animowane tło (gwiazdy + fale gradientów), stan zapisywany między stronami
- Responsywny layout (desktop + mobile)
- Popup uploadu z postępem per plik i możliwością anulowania

### Administracja
- Konsola admina na porcie `8081` (WebSocket, live logi)
- Autobackup co 24h (max 3 kopie w `./backups/`)
- Tryb konserwacji (`maintenance on/off`)
- Integracja z Cloudflare Tunnel
- Monitorowanie RAM, CPU, wątków, połączeń, dysku, sieci
- Wersjonowanie aplikacji (`--ver set X.Y.Z`)

---

## Komendy konsoli (port 8081)

### Dostępne dla Admina i Ownera

```
adminpass                          — pokaż aktualne hasło admina
ban <user> <czas> <s/m/h/d>        — zbanuj na czas
ban <user> permanent               — ban permanentny
unban <user>                       — zdejmij bana
list bans / users / shares / mods / roles
revoke <token>                     — unieważnij link
revoke all                         — usuń wszystkie linki
deluser <user> [--files]           — usuń konto
passwd <user> <haslo>              — zmień hasło
add mod <user>                     — nadaj uprawnienia moderatora
remove mod <user>                  — odbierz uprawnienia moderatora
add role <user> <nazwa> <#kolor>   — nadaj rolę
remove role <user>                 — usuń rolę
set owner <user>                   — ustaw konto właściciela
disk                               — miejsce per użytkownik
backup                             — ręczny backup ZIP
maintenance on [wiadomość]         — włącz tryb konserwacji
maintenance off                    — wyłącz tryb konserwacji
maintenance status                 — sprawdź stan
--m on/off/status                  — skrót komendy maintenance
restart / reset / --r              — restart serwera
--ver                              — pokaż wersję
--ver set <X.Y.Z> [stage]          — ustaw wersję
ping / ping ngrok                  — test połączenia
stats                              — szczegółowe statystyki (ramka)
status                             — krótki stan serwera
clear logs                         — wyczyść terminal
help                               — lista komend
```

### Ograniczenia Moderatora

Moderator ma dostęp do terminala w głównym UI (port 8080) ale **nie** do konsoli administracyjnej (port 8081). Może wykonywać: `ban`, `unban`, `list`, `revoke <token>`, `disk`, `ping`, `stats`, `status`, `clear logs`.

---

## Konfiguracja

Edytuj stałe na górze `StartUp.py`:

```python
PORT        = 8080          # port głównego serwera
CONSOLE_PORT = 8081         # port konsoli admina
SESSION_TTL = 60*60*24*30   # czas sesji (30 dni)
BACKUP_INTERVAL = 60*60*24  # interwał autobackupu (24h)
BACKUP_MAX_KEEP = 3         # ile backupów zachować
LOGIN_MAX_ATTEMPTS = 10     # max prób logowania per IP
LOGIN_WINDOW_SEC   = 60     # okno rate-limitingu (sek)
```

---

## Cloudflare Tunnel

Aby udostępnić serwer przez internet bez otwierania portów:

1. Zainstaluj `cloudflared` i zaloguj się: `cloudflared login`
2. Utwórz tunel: `cloudflared tunnel create safecloud`
3. Umieść `cloudflared.exe` / `cloudflared` w tym samym folderze co `StartUp.py`
4. Serwer automatycznie wykryje i uruchomi tunel przy starcie

---

## Bezpieczeństwo — uwagi

- Serwer działa po **HTTP** (nie HTTPS). Przez Cloudflare Tunnel otrzymujesz HTTPS automatycznie. Na sieci lokalnej rozważ użycie reverse proxy (nginx + certbot).
- Hasło admina jest **generowane losowo przy każdym uruchomieniu** (16 znaków). Wypisywane w terminalu. Nie jest trwale ustawione.
- Pliki są przechowywane lokalnie w `./SAFE CLOUD/<username>/` bez szyfrowania.

---

## Rozmiar projektu

Całość to jeden plik `StartUp.py` (~6700 linii), bez żadnych zewnętrznych frameworków webowych. HTML, CSS i JavaScript są osadzone bezpośrednio w Pythonie jako stringi.
