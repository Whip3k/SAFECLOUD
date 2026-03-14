#!/usr/bin/env python3
"""
Uruchom:  python3 serwer.py
Komputer: http://localhost:8080
Telefon:  http://<twoje-ip>:8080   (ta sama siec Wi-Fi)

Logowanie: kazdy uzytkownik ma swoj wlasny folder w ./SAFE CLOUD/<username>/
Dane kont sa zapisane w ./users.json (hasla jako hash SHA-256)

ADMIN: konto 'admin' ma dostep do plikow wszystkich uzytkownikow (./SAFE CLOUD/)
"""

import http.server, socketserver, os, json, urllib.parse
import mimetypes, shutil, html, socket, hashlib, secrets, time, threading
from pathlib import Path
from datetime import datetime

# ── KONFIGURACJA ──────────────────────────────────────
PORT        = 8080
STORAGE_DIR = Path("./SAFE CLOUD")
USERS_FILE  = Path("./users.json")
BANS_FILE   = Path("./bans.json")
SHARES_FILE  = Path("./shares.json")
VERSION_FILE = Path("./version.json")
HOST        = "0.0.0.0"
SESSION_TTL = 60 * 60 * 24 * 30  # sesja wazna 30 dni
ADMIN_USER  = "admin"        # nazwa konta admina
OWNER_USER  = "whip3kgt"     # nazwa konta ownera
# ──────────────────────────────────────────────────────

STORAGE_DIR.mkdir(exist_ok=True)

def load_users():
    """
    Zwraca słownik { username: { "password": hash, "role": {...} | None } }.
    Obsługuje stary format { username: hash_string } i migruje automatycznie.
    """
    if not USERS_FILE.exists():
        return {}
    raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    # Migracja ze starego formatu { user: "hash" }
    migrated = False
    for k, v in raw.items():
        if isinstance(v, str):
            raw[k] = {"password": v, "role": None}
            migrated = True
    # Wczytaj stary roles.json jeśli istnieje i jeszcze nie zmigrowaliśmy ról
    roles_file = Path("./roles.json")
    if roles_file.exists():
        try:
            old_roles = json.loads(roles_file.read_text(encoding="utf-8"))
            for user, role in old_roles.items():
                if user in raw and not raw[user].get("role"):
                    raw[user]["role"] = role
                    migrated = True
            roles_file.rename(roles_file.with_suffix(".json.bak"))
        except: pass
    if migrated:
        save_users(raw)
    return raw

def save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")

def get_user_password(users, username):
    """Zwraca hash hasła dla użytkownika (obsługuje oba formaty)."""
    v = users.get(username)
    if v is None: return None
    if isinstance(v, str): return v
    return v.get("password")

def get_user_role(users, username):
    """Zwraca słownik roli lub None."""
    v = users.get(username)
    if v is None or isinstance(v, str): return None
    return v.get("role")

def set_user_role(users, username, role):
    """Ustawia lub usuwa rolę użytkownika (role=None = usuń)."""
    if username not in users: return
    v = users[username]
    if isinstance(v, str):
        users[username] = {"password": v, "role": role}
    else:
        users[username]["role"] = role

def load_bans():
    if BANS_FILE.exists():
        return json.loads(BANS_FILE.read_text())
    return {}

def save_bans():
    BANS_FILE.write_text(json.dumps(bans, indent=2))

def get_ban(username):
    """Zwraca dane bana jeśli aktywny, None jeśli brak lub wygasł."""
    b = bans.get(username)
    if not b:
        return None
    if b.get("expires") and time.time() > b["expires"]:
        del bans[username]
        save_bans()
        return None
    return b

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def generate_admin_password():
    charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%&*"
    return "".join(secrets.choice(charset) for _ in range(5))

def ensure_admin():
    new_pass = generate_admin_password()
    users = load_users()
    if ADMIN_USER not in users:
        users[ADMIN_USER] = {"password": hash_password(new_pass), "role": None}
    else:
        users[ADMIN_USER]["password"] = hash_password(new_pass)
    save_users(users)
    return new_pass

sessions = {}
bans  = load_bans()

# ── UDOSTĘPNIANIE PLIKÓW ──────────────────────────────
# Dane trzymane w shares.json, nie w RAM

def load_shares():
    if SHARES_FILE.exists():
        try: return json.loads(SHARES_FILE.read_text(encoding="utf-8"))
        except: return {}
    return {}

def save_shares(s):
    SHARES_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

def create_share(username, rel_path, filename, ttl_hours=None):
    token   = secrets.token_urlsafe(24)
    expires = (time.time() + ttl_hours * 3600) if ttl_hours else None
    s = load_shares()
    s[token] = {
        "owner":     username,
        "path":      rel_path,
        "name":      filename,
        "expires":   expires,
        "downloads": 0,
        "created":   time.time(),
    }
    save_shares(s)
    return token

def get_share(token):
    s = load_shares()
    entry = s.get(token)
    if not entry:
        return None
    if entry["expires"] and time.time() > entry["expires"]:
        del s[token]
        save_shares(s)
        return None
    return entry

def delete_share(token):
    s = load_shares()
    if token in s:
        del s[token]
        save_shares(s)

def list_shares():
    s = load_shares()
    now = time.time()
    # przy okazji wyczyść wygasłe
    expired = [t for t, v in s.items() if v["expires"] and now > v["expires"]]
    if expired:
        for t in expired: del s[t]
        save_shares(s)
    return s

# ── WERSJA APLIKACJI ──────────────────────────────────
def load_version():
    if VERSION_FILE.exists():
        try: return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        except: pass
    return {"version": "0.1.0", "stage": "alpha"}

def save_version(ver, stage):
    VERSION_FILE.write_text(json.dumps({"version": ver, "stage": stage}, indent=2, ensure_ascii=False), encoding="utf-8")

# Rate-limiting logowania: { ip: [timestamp, ...] }
login_attempts = {}
LOGIN_MAX_ATTEMPTS = 10   # max prób
LOGIN_WINDOW_SEC   = 60   # w ciągu tylu sekund

def check_login_rate_limit(ip):
    """Zwraca True jeśli IP jest zablokowane. Czyści stare wpisy."""
    now = time.time()
    attempts = login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW_SEC]
    login_attempts[ip] = attempts
    return len(attempts) >= LOGIN_MAX_ATTEMPTS

def record_login_attempt(ip):
    """Rejestruje nieudaną próbę logowania dla danego IP."""
    now = time.time()
    attempts = login_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW_SEC]
    attempts.append(now)
    login_attempts[ip] = attempts

def handle_command(cmd):
    """Obsługa komend z konsoli. Zwraca odpowiedź jako string."""
    parts = cmd.strip().split()
    if not parts:
        return None
    c = parts[0].lower()

    # --ver
    if c == "--ver":
        if len(parts) >= 3 and parts[1].lower() == "set":
            # --ver set <wersja> [stage]
            ver = parts[2]
            # walidacja formatu x.y.z
            import re
            if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
                return "[CMD] ✗ Nieprawidłowy format wersji. Użyj: --ver set <X.Y.Z> [alpha/beta/rc/stable]"
            valid_stages = {"alpha", "beta", "rc", "stable", "pre-alpha", "nightly", "lts"}
            stage = parts[3].lower() if len(parts) >= 4 else "stable"
            if stage not in valid_stages:
                return f"[CMD] ✗ Nieznany stage '{stage}'. Dostępne: alpha, beta, rc, stable, pre-alpha, nightly, lts"
            save_version(ver, stage)
            return f"[CMD] ✓ Wersja ustawiona na {ver} ({stage})"
        else:
            v = load_version()
            return f"[CMD] Wersja: {v['version']} ({v['stage']})"

    # ban <user> <czas> <jednostka> [powód]   np: ban janek 2 h Spam
    # ban <user> permanent [powód]
    if c == "ban":
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: ban <user> <czas> <s/m/h/d> [powód]  lub  ban <user> permanent [powód]"
        user = parts[2] if len(parts) > 2 else ""
        # poprawna składnia: ban <user> ...
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: ban <user> <czas> <s/m/h/d> [powód]"
        user = parts[1]
        users = load_users()
        if user not in users:
            return f"[CMD] ✗ Użytkownik '{user}' nie istnieje."
        if user == ADMIN_USER or user == OWNER_USER:
            return f"[CMD] ✗ Nie możesz zbanować admina ani ownera."
        duration_str = parts[2].lower()
        if duration_str == "permanent":
            expires = None
            human   = "permanentny"
            reason  = " ".join(parts[3:]) or "Brak powodu."
        else:
            if len(parts) < 4:
                return "[CMD] ✗ Podaj jednostkę czasu: s, m, h, d  (np. ban janek 2 h Spam)"
            unit = parts[3].lower()
            try: amount = float(duration_str)
            except: return "[CMD] ✗ Nieprawidłowy czas. Podaj liczbę, np: ban janek 2 h"
            mult = {"s":1,"m":60,"h":3600,"d":86400}.get(unit)
            if not mult:
                return "[CMD] ✗ Jednostka musi być: s, m, h, d"
            expires = time.time() + amount * mult
            names   = {"s":"sekund","m":"minut","h":"godzin","d":"dni"}
            human   = f"{int(amount)} {names[unit]}"
            reason  = " ".join(parts[4:]) or "Brak powodu."
        bans[user] = {"reason": reason, "expires": expires, "human": human}
        save_bans()
        # wyloguj zbanowanego
        to_del = [t for t,s in sessions.items() if s["username"] == user]
        for t in to_del: del sessions[t]
        return f"[CMD] ✓ Użytkownik '{user}' zbanowany na {human}. Powód: {reason}"

    # unban <user>
    if c == "unban":
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: unban <user>"
        user = parts[1]
        if user in bans:
            del bans[user]
            save_bans()
            return f"[CMD] ✓ Zdjęto bana z '{user}'."
        return f"[CMD] ✗ '{user}' nie jest zbanowany."

    # list bans
    if c == "list" and len(parts) >= 2 and parts[1].lower() == "bans":
        active = {u: b for u, b in bans.items() if get_ban(u)}
        if not active:
            return "[CMD] Brak aktywnych banów."
        lines = ["[CMD] Aktywne bany:"]
        for u, b in active.items():
            exp = "permanentny" if not b["expires"] else f"wygasa za {max(0,int(b['expires']-time.time()))}s"
            lines.append(f"  {u}  |  {b['human']}  |  {exp}  |  {b['reason']}")
        return "\n".join(lines)

    # add role <user> <role_name> <hex_color>
    if c == "add" and len(parts) >= 2 and parts[1].lower() == "role":
        if len(parts) < 5:
            return "[CMD] ✗ Użycie: add role <user> <nazwa_roli> <kolor_hex>  np: add role janek VIP #ff6600"
        user  = parts[2]
        rname = parts[3]
        color = parts[4] if parts[4].startswith("#") else "#" + parts[4]
        users = load_users()
        if user not in users:
            return f"[CMD] ✗ Użytkownik '{user}' nie istnieje."
        set_user_role(users, user, {"name": rname, "color": color})
        save_users(users)
        return f"[CMD] ✓ Rola '{rname}' ({color}) nadana użytkownikowi '{user}'."

    # remove role <user>
    if c == "remove" and len(parts) >= 2 and parts[1].lower() == "role":
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: remove role <user>"
        user = parts[2]
        users = load_users()
        old = get_user_role(users, user)
        if old:
            set_user_role(users, user, None)
            save_users(users)
            return f"[CMD] ✓ Rola '{old['name']}' usunięta od '{user}'."
        return f"[CMD] ✗ Użytkownik '{user}' nie ma żadnej roli."

    # list roles
    if c == "list" and len(parts) >= 2 and parts[1].lower() == "roles":
        users = load_users()
        role_list = [(u, get_user_role(users, u)) for u in users if get_user_role(users, u)]
        if not role_list:
            return "[CMD] Brak przypisanych ról."
        lines = ["[CMD] Przypisane role:"]
        for u, r in role_list:
            lines.append(f"  {u}  →  {r['name']}  ({r['color']})")
        return "\n".join(lines)

    # list users
    if c == "list" and len(parts) >= 2 and parts[1].lower() == "users":
        users = load_users()
        if not users:
            return "[CMD] Brak użytkowników."
        lines = ["[CMD] Użytkownicy:"]
        for u in users:
            r = get_user_role(users, u)
            role_info = f"  [{r['name']}]" if r else ""
            ban_info  = "  [ZBANOWANY]" if get_ban(u) else ""
            tag = " [ADMIN]" if u == ADMIN_USER else (" [OWNER]" if u == OWNER_USER else "")
            lines.append(f"  {u}{tag}{role_info}{ban_info}")
        return "\n".join(lines)

    # list shares
    if c == "list" and len(parts) >= 2 and parts[1].lower() == "shares":
        active = list_shares()
        if not active:
            return "[CMD] Brak aktywnych linków."
        lines = ["[CMD] Aktywne linki udostępniania:"]
        for token, s in active.items():
            exp = "∞" if not s["expires"] else f"wygasa za {max(0,int(s['expires']-time.time()))}s"
            lines.append(f"  {token[:10]}…  |  {s['owner']}  |  {s['name']}  |  {exp}  |  pobrań: {s['downloads']}")
        return "\n".join(lines)

    # revoke <token>
    if c == "revoke":
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: revoke <token>"
        tok = parts[1]
        all_shares = load_shares()
        matched = [t for t in all_shares if t == tok or t.startswith(tok)]
        if not matched:
            return f"[CMD] ✗ Nie znaleziono linku '{tok}'."
        last_name = ""
        for t in matched:
            last_name = all_shares[t]["name"]
            del all_shares[t]
        save_shares(all_shares)
        return f"[CMD] ✓ Unieważniono {len(matched)} link(i) dla '{last_name}'."

    # deluser <user> [--files]
    if c == "deluser":
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: deluser <user> [--files]"
        user = parts[1]
        if user == ADMIN_USER or user == OWNER_USER:
            return f"[CMD] ✗ Nie możesz usunąć konta admina ani ownera."
        users = load_users()
        if user not in users:
            return f"[CMD] ✗ Użytkownik '{user}' nie istnieje."
        del users[user]
        save_users(users)
        # wyloguj aktywne sesje
        to_del = [t for t, s in sessions.items() if s["username"] == user]
        for t in to_del:
            del sessions[t]
        # usuń bany (rola jest już w users.json, usunięta razem z kontem)
        bans.pop(user, None)
        save_bans()
        # opcjonalnie usuń pliki
        delete_files = "--files" in parts
        if delete_files:
            user_dir = STORAGE_DIR / user
            if user_dir.exists():
                shutil.rmtree(user_dir)
                return f"[CMD] ✓ Konto '{user}' usunięte wraz z plikami."
        return f"[CMD] ✓ Konto '{user}' usunięte. Pliki zachowane (dodaj --files żeby usunąć)."



    # help
    # adminpass
    if c == "adminpass":
        return f"[CMD] \U0001f511 Aktualne haslo admina: {_current_admin_pass}"

    if c == "help" and len(parts) >= 2 and parts[1].lower() == "ban":
        return (
            "[CMD] ────────────────────────── Pomoc: komenda BAN ──────────────────────────\n"
            "  Składnia:\n"
            "    ban <user> <czas> <jednostka> [powód]\n"
            "    ban <user> permanent [powód]\n"
            "\n"
            "  Jednostki czasu:\n"
            "    s  – sekundy    (np. ban janek 30 s)\n"
            "    m  – minuty     (np. ban janek 15 m Spam)\n"
            "    h  – godziny    (np. ban janek 2 h Wulgaryzmy)\n"
            "    d  – dni        (np. ban janek 7 d Naruszenie regulaminu)\n"
            "\n"
            "  Ban permanentny:\n"
            "    ban janek permanent Poważne naruszenie\n"
            "\n"
            "  Zdejmowanie bana:\n"
            "    unban janek\n"
            "\n"
            "  Lista aktywnych banów:\n"
            "    list bans\n"
            "\n"
            "  Uwagi:\n"
            "    · Powód jest opcjonalny – jeśli pominięty, wpisuje 'Brak powodu.'\n"
            "    · Nie możesz zbanować konta admin ani owner\n"
            "    · Ban wylogowuje użytkownika natychmiast\n"
            "    · Bany zapisują się w bans.json i przeżywają restart\n"
            "[CMD] ──────────────────────────────────────────────────────────────────────────"
        )

    if c == "help":
        return (
            "────────────────────────────────────────────────────KOMENDY────────────────────────────────────────────────────\n"
            "[CMD] Dostępne komendy:\n"
            "  adminpass                             – pokaż aktualne hasło admina\n"
            "  ban <user> <czas> <s/m/h/d> [powód]   – zbanuj na czas\n"
            "  ban <user> permanent [powód]          – ban permanentny\n"
            "  unban <user>                          – zdejmij bana\n"
            "  list bans                             – lista banów\n"
            "  add role <user> <nazwa> <#kolor>      – nadaj rolę\n"
            "  remove role <user>                    – usuń rolę\n"
            "  list roles                            – lista ról\n"
            "  list users                            – lista użytkowników\n"
            "  list shares                           – lista aktywnych linków udostępniania\n"
            "  revoke <token>                        – unieważnij link udostępniania\n"
            "  deluser <user>                        – usuń konto (pliki zostają)\n"
            "  deluser <user> --files                – usuń konto i wszystkie pliki\n"
            "  passwd <user> <haslo>                 – zmień hasło użytkownika\n"
            "  disk                                  – zajęte miejsce per użytkownik\n"
            "  backup                                – spakuj cały SAFE CLOUD do ZIP\n"
            "  clear logs                            – wyczyść terminal\n"
            "  ping                                  – sprawdź ping między tobą a serwerem\n"
            "  ping ngrok                            – sprawdź ping do tunelu ngrok\n"
            "  status                                – stan serwera (RAM, CPU, wątki...)\n"
            "  restart / reset / --r                 – zrestartuj serwer\n"
            "  --ver                                 – pokaż aktualną wersję aplikacji\n"
            "  --ver set <X.Y.Z> [stage]             – ustaw wersję (stage: alpha/beta/rc/stable)\n"
            "  help                                  – ta pomoc\n"
            "\n" 
            "──────────────────────────────────────────────────────────────────────────────────────────────────────────────────"
        )

    # status
    if c == "status":
        s = get_stats()
        if not s.get("ok"):
            return f"[CMD] ✗ Błąd pobierania statystyk: {s.get('error','?')}"
        ram_mb = s["ram_rss_raw"] / (1024*1024)
        cpu    = s["cpu"]
        thr    = s["threads"]
        con    = s["conns"]
        ses    = s["sessions"]
        cache  = s["cache"]
        # ocena stanu
        problems = []
        if ram_mb >= 280:   problems.append(f"RAM krytyczny ({s['ram_rss']})")
        elif ram_mb >= 220: problems.append(f"RAM podwyższony ({s['ram_rss']})")
        if cpu >= 80:       problems.append(f"CPU bardzo wysokie ({cpu}%)")
        elif cpu >= 50:     problems.append(f"CPU podwyższone ({cpu}%)")
        if thr >= 50:       problems.append(f"dużo wątków ({thr})")
        if con >= 30:       problems.append(f"dużo połączeń ({con})")
        if cache >= 100:    problems.append(f"duży cache miniaturek ({cache})")
        if not problems:
            if ram_mb < 100 and cpu < 20:
                ocena = "✓ Doskonały — serwer działa bez zarzutu"
            elif ram_mb < 150 and cpu < 40:
                ocena = "✓ Dobry — wszystko w normie"
            else:
                ocena = "~ Stabilny — brak problemów, ale zasoby rosną"
        elif len(problems) == 1:
            ocena = f"⚠ Uwaga — {problems[0]}"
        else:
            ocena = f"⚠ Problemy: {', '.join(problems)}"
        dr = s.get('disk_r') or '—'
        dw = s.get('disk_w') or '—'
        return f"[STATUS] {ocena}"

    # ping / ping ngrok
    if c == "ping":
        if len(parts) >= 2 and parts[1].lower() == "ngrok":
            import urllib.request as _ur
            ngrok_host = None
            try:
                import re as _re
                m = _re.search(r'https?://([\w\-]+\.ngrok[\w\-\.]*\.(?:dev|io|app))', CONSOLE_HTML)
                if m:
                    ngrok_host = m.group(1)
            except: pass
            if not ngrok_host:
                return "[CMD] ✗ Nie znaleziono adresu ngrok w konfiguracji."
            results = []
            errors  = 0
            for i in range(3):
                t_start = time.perf_counter()
                try:
                    req = _ur.Request(f"https://{ngrok_host}", headers={"ngrok-skip-browser-warning": "true", "User-Agent": "SafeCloud-Ping/1.0"})
                    with _ur.urlopen(req, timeout=8) as resp:
                        resp.read(1)
                    ms = (time.perf_counter() - t_start) * 1000
                    results.append(ms)
                except Exception as e:
                    errors += 1
                    results.append(None)
                if i < 2:
                    time.sleep(0.3)
            valid = [r for r in results if r is not None]
            if not valid:
                return f"[CMD] ✗ Ping ngrok nieudany — tunel może być offline"
            avg = sum(valid) / len(valid)
            mn  = min(valid)
            mx  = max(valid)
            loss = int(errors / 3 * 100)
            quality = "🟢 dobry" if avg < 150 else ("🟡 średni" if avg < 400 else "🔴 słaby")
            lines = [
                f"[CMD] 🏓 Ping → {ngrok_host}",
                f"[CMD]   min: {mn:.0f} ms  avg: {avg:.0f} ms  max: {mx:.0f} ms  utrata: {loss}%  jakość: {quality}",
            ]
            for i, r in enumerate(results):
                lines.append(f"[CMD]   #{i+1}: {'timeout' if r is None else f'{r:.0f} ms'}")
            return "\n".join(lines)
        else:
            t_start = time.perf_counter()
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
                s.close()
                ms = (time.perf_counter() - t_start) * 1000
                return f"[CMD] 🏓 Pong! Ping do serwera: {ms:.2f} ms"
            except Exception as e:
                return f"[CMD] ✗ Ping nieudany: {e}"

    # restart / reset / --r
    if c in ("restart", "reset", "--r"):
        import threading as _th
        def _do_restart():
            time.sleep(0.5)
            import sys, os as _os
            _os.execv(sys.executable, [sys.executable] + sys.argv)
        _th.Thread(target=_do_restart, daemon=True).start()
        return "[CMD] ✓ Serwer restartuje się... odśwież stronę za chwilę."

    # passwd <user> <nowe_haslo>
    if c == "passwd":
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: passwd <user> <nowe_haslo>"
        user, new_pass = parts[1], parts[2]
        users = load_users()
        if user not in users:
            return f"[CMD] ✗ Użytkownik '{user}' nie istnieje."
        v = users[user]
        new_hash = hashlib.sha256(new_pass.encode()).hexdigest()
        if isinstance(v, dict):
            users[user]["password"] = new_hash
        else:
            users[user] = {"password": new_hash, "role": None}
        save_users(users)
        # wyloguj aktywne sesje tego użytkownika
        to_del = [t for t, s in sessions.items() if s["username"] == user]
        for t in to_del:
            del sessions[t]
        return f"[CMD] ✓ Hasło '{user}' zmienione. Aktywne sesje wylogowane ({len(to_del)})."

    # disk
    if c == "disk":
        if not STORAGE_DIR.exists():
            return "[CMD] ✗ Katalog SAFE CLOUD nie istnieje."
        lines = ["[CMD] Zajęte miejsce per użytkownik:"]
        totals = []
        for d in sorted(STORAGE_DIR.iterdir()):
            if not d.is_dir():
                continue
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
            count = sum(1 for f in d.rglob("*") if f.is_file())
            totals.append((d.name, size, count))
        totals.sort(key=lambda x: x[1], reverse=True)
        for name, size, count in totals:
            tag = " [ADMIN]" if name == ADMIN_USER else (" [OWNER]" if name == OWNER_USER else "")
            lines.append(f"  {name}{tag}  —  {human_size(size)}  ({count} plików)")
        grand = sum(x[1] for x in totals)
        lines.append(f"  ─────────────────────────")
        lines.append(f"  RAZEM  —  {human_size(grand)}")
        return "\n".join(lines)

    # backup
    if c == "backup":
        import zipfile as _zf, io as _io
        if not STORAGE_DIR.exists():
            return "[CMD] ✗ Katalog SAFE CLOUD nie istnieje."
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(f"./backup_{ts}.zip")
        count = 0
        try:
            with _zf.ZipFile(backup_path, "w", _zf.ZIP_DEFLATED) as zf:
                for fp in STORAGE_DIR.rglob("*"):
                    if fp.is_file():
                        zf.write(fp, fp.relative_to(STORAGE_DIR.parent))
                        count += 1
            size = human_size(backup_path.stat().st_size)
            return f"[CMD] ✓ Backup zapisany: {backup_path.name}  ({count} plików, {size})"
        except Exception as e:
            return f"[CMD] ✗ Błąd backupu: {e}"

    # clear logs
    if c == "clear" and len(parts) >= 2 and parts[1].lower() == "logs":
        return "__CLEAR_LOGS__"

    return f"[CMD] ✗ Nieznana komenda '{cmd}'. Wpisz 'help' po listę komend."

def create_session(username):
    token = secrets.token_hex(32)
    sessions[token] = {"username": username, "expires": time.time() + SESSION_TTL}
    return token

def get_session(token):
    if not token:
        return None
    s = sessions.get(token)
    if s and s["expires"] > time.time():
        # Odnów TTL przy każdym żądaniu
        s["expires"] = time.time() + SESSION_TTL
        return s["username"]
    if s:
        del sessions[token]
    return None

def get_token_from_request(handler):
    cookie = handler.headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("session="):
            return part[8:]
    return None

def is_admin(username):
    return username == ADMIN_USER

def is_owner(username):
    return username == OWNER_USER

def user_storage(username):
    if is_admin(username):
        STORAGE_DIR.mkdir(exist_ok=True)
        return STORAGE_DIR
    p = STORAGE_DIR / username
    p.mkdir(exist_ok=True)
    return p

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "?.?.?.?"

def human_size(n):
    for u in ["B","KB","MB","GB","TB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"

def dir_stats(path):
    count, total = 0, 0
    for r, d, files in os.walk(path):
        count += len(files)
        for f in files:
            try: total += os.path.getsize(os.path.join(r, f))
            except: pass
    return count, total

def file_icon(name, is_dir):
    if is_dir: return "folder"
    ext = Path(name).suffix.lower()
    if ext in {".jpg",".jpeg",".png",".gif",".webp",".svg",".avif"}: return "image"
    if ext in {".mp4",".avi",".mov",".mkv",".webm"}: return "video"
    if ext in {".mp3",".wav",".flac",".ogg",".aac",".m4a"}: return "audio"
    if ext in {".pdf"}: return "pdf"
    if ext in {".zip",".rar",".7z",".tar",".gz"}: return "archive"
    if ext in {".doc",".docx",".odt"}: return "doc"
    if ext in {".xls",".xlsx",".csv"}: return "sheet"
    if ext in {".py",".js",".ts",".html",".css",".json",".xml",".sh"}: return "code"
    return "file"

def is_image(name):
    return Path(name).suffix.lower() in {".jpg",".jpeg",".png",".gif",".webp",".svg",".avif"}

def viewer_type(name):
    ext = Path(name).suffix.lower()
    if ext in {".jpg",".jpeg",".png",".gif",".webp",".avif"}: return "image"
    if ext == ".svg": return "svg"
    if ext in {".mp4",".webm",".mov",".avi",".mkv"}: return "video"
    if ext in {".mp3",".wav",".ogg",".flac",".aac",".m4a"}: return "audio"
    if ext == ".pdf": return "pdf"
    if ext in {".txt",".md",".csv",".log",".ini",".cfg",".conf",".env",
               ".py",".js",".ts",".jsx",".tsx",".html",".css",".json",
               ".xml",".yaml",".yml",".sh",".bat",".c",".cpp",".h",
               ".java",".go",".rs",".php",".rb",".sql",".toml"}: return "text"
    if ext in {".zip", ".tar", ".gz", ".bz2", ".xz"}: return "archive"
    return None

def safe_path(base_dir, sub):
    base = base_dir.resolve()
    t = (base / sub.lstrip("/")).resolve()
    if not str(t).startswith(str(base)): return None
    return t

def breadcrumb_html(path_str, username):
    parts = [p for p in path_str.strip("/").split("/") if p]
    if is_admin(username):
        out = '<a href="/?path=" class="brand">&#x1F6E1; Admin – SAFE CLOUD</a>'
    else:
        out = '<a href="/?path=" class="brand">SAFE CLOUD</a>'
    cur = ""
    for p in parts:
        cur += "/" + p
        ep = html.escape(urllib.parse.quote(cur))
        out += f' <span>/</span> <a href="/?path={ep}">{html.escape(p)}</a>'
    return out

ICONS = {
"folder":  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>',
"image":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
"video":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><rect x="2" y="4" width="15" height="16" rx="2"/><path d="M17 8l5-3v14l-5-3V8z"/></svg>',
"audio":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
"pdf":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/></svg>',
"archive": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v11a2 2 0 002 2h12a2 2 0 002-2V9"/><path d="M10 13h4"/></svg>',
"doc":     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/></svg>',
"sheet":   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/></svg>',
"code":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
"file":    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>',
}

DOWN_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
DEL_ICO  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>'
OPEN_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M5 12h14M12 5l7 7-7 7"/></svg>'

thumb_cache = {}  # { path_str: (mtime, jpeg_bytes) }

def get_audio_cover(path):
    """Wyciąga okładkę z pliku audio. Zwraca bytes obrazka lub None."""
    try:
        ext = path.suffix.lower()
        if ext in {".mp3", ".mp2", ".mp1"}:
            from mutagen.id3 import ID3
            tags = ID3(str(path))
            for k, v in tags.items():
                if k.startswith("APIC"):
                    return v.data
        elif ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(str(path))
            if audio.pictures:
                return audio.pictures[0].data
        elif ext in {".m4a", ".aac", ".mp4", ".m4b"}:
            from mutagen.mp4 import MP4
            audio = MP4(str(path))
            if "covr" in audio.tags:
                return bytes(audio.tags["covr"][0])
        elif ext in {".ogg", ".oga"}:
            from mutagen.oggvorbis import OggVorbis
            import base64
            audio = OggVorbis(str(path))
            if "metadata_block_picture" in audio:
                from mutagen.flac import Picture
                pic = Picture(base64.b64decode(audio["metadata_block_picture"][0]))
                return pic.data
        elif ext == ".opus":
            from mutagen.oggopus import OggOpus
            import base64
            audio = OggOpus(str(path))
            if "metadata_block_picture" in audio:
                from mutagen.flac import Picture
                pic = Picture(base64.b64decode(audio["metadata_block_picture"][0]))
                return pic.data
    except Exception:
        pass
    return None

def get_thumbnail(path, size=1500):
    """Zwraca JPEG miniaturkę jako bytes. Cache po mtime."""
    try:
        from PIL import Image
        import io
        key   = str(path)
        mtime = path.stat().st_mtime
        if key in thumb_cache and thumb_cache[key][0] == mtime:
            return thumb_cache[key][1]

        # Obsługa plików audio — wyciągnij okładkę
        audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".oga", ".mp2"}
        if path.suffix.lower() in audio_exts:
            cover_bytes = get_audio_cover(path)
            if not cover_bytes:
                return None
            with Image.open(io.BytesIO(cover_bytes)) as img:
                img = img.convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85, optimize=True)
                data = buf.getvalue()
            thumb_cache[key] = (mtime, data)
            return data

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            data = buf.getvalue()
        thumb_cache[key] = (mtime, data)
        # ogranicz cache: max 100 wpisów lub 50 MB łącznie — usuń najstarsze
        CACHE_MAX_ENTRIES = 100
        CACHE_MAX_BYTES   = 50 * 1024 * 1024  # 50 MB
        total_bytes = sum(v[1].__len__() for v in thumb_cache.values())
        while thumb_cache and (len(thumb_cache) > CACHE_MAX_ENTRIES or total_bytes > CACHE_MAX_BYTES):
            oldest_key = next(iter(thumb_cache))
            total_bytes -= len(thumb_cache[oldest_key][1])
            del thumb_cache[oldest_key]
        return data
    except Exception as e:
        return None

def build_cards(dir_path, url_path, sort_by="name", sort_dir="asc", search=""):
    try:
        all_entries = list(dir_path.iterdir())
    except:
        return '<p style="color:#888;padding:2rem">Brak dostepu.</p>'

    # filtrowanie
    if search:
        sl = search.lower()
        all_entries = [e for e in all_entries if sl in e.name.lower()]

    # sortowanie
    def sort_key(x):
        is_dir = x.is_dir()
        if sort_by == "size":
            try: sz = x.stat().st_size if not is_dir else 0
            except: sz = 0
            return (not is_dir, sz if sort_dir == "asc" else -sz)
        elif sort_by == "date":
            try: mt = x.stat().st_mtime
            except: mt = 0
            return (not is_dir, mt if sort_dir == "asc" else -mt)
        else:  # name
            n = x.name.lower()
            return (not is_dir, n if sort_dir == "asc" else tuple(-ord(c) for c in n))

    entries = sorted(all_entries, key=sort_key)

    if not entries:
        msg = "Brak wyników wyszukiwania" if search else "Folder jest pusty"
        sub = "Spróbuj innej frazy" if search else "Przeciagnij pliki lub kliknij powyzej"
        return f'''<div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" width="48" height="48" style="opacity:.25"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>
          <p>{msg}</p><small>{sub}</small>
        </div>'''

    out = []
    for e in entries:
        name   = e.name
        sname  = html.escape(name)
        is_dir = e.is_dir()
        enc    = urllib.parse.quote(url_path.rstrip("/") + "/" + name)
        itype  = file_icon(name, is_dir)
        icon   = ICONS.get(itype, ICONS["file"])

        RENAME_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>'
        MOVE_ICO   = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>'
        SHARE_ICO  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>'

        if is_dir:
            try: sub = len(list(e.iterdir()))
            except: sub = 0
            meta   = f"{sub} elem."
            href   = f"/?path={enc}"
            thumb  = f'<div class="thumb thumb-folder">{icon}</div>'
            actions = f'<div class="card-actions"><a class="act" href="{href}">{OPEN_ICO}</a><button class="act" onclick="dlFolder(\'{sname}\',event)" title="Pobierz jako ZIP">{DOWN_ICO}</button><button class="act" onclick="renameItem(\'{sname}\',true,event)" title="Zmień nazwę">{RENAME_ICO}</button><button class="act act-del" onclick="del(\'{sname}\',true,event)">{DEL_ICO}</button></div>'
            click   = f'onclick="location.href=\'/?path={enc}\'"'
        else:
            sz     = e.stat().st_size
            meta   = human_size(sz)
            href   = f"/file?path={enc}"
            audio_exts = {".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".oga", ".wav", ".mp2"}
            if is_image(name):
                thumb = f'<div class="thumb thumb-img"><img data-src="/thumb?path={enc}" alt="{sname}" class="lazy"></div>'
            elif Path(name).suffix.lower() in audio_exts:
                thumb = f'<div class="thumb thumb-audio" data-src="/thumb?path={enc}"><div class="thumb-audio-inner">{icon}<img class="thumb-audio-cover lazy" data-src="/thumb?path={enc}" alt="" style="display:none"></div></div>'
            else:
                thumb = f'<div class="thumb thumb-file">{icon}</div>'
            vtype = viewer_type(name)
            view_href = f"/view?path={enc}" if vtype else href
            actions = f'<div class="card-actions"><a class="act" href="{href}" download="{sname}">{DOWN_ICO}</a><button class="act" onclick="shareItem(\'{sname}\',event)" title="Udostępnij">{SHARE_ICO}</button><button class="act" onclick="renameItem(\'{sname}\',false,event)" title="Zmień nazwę">{RENAME_ICO}</button><button class="act act-del" onclick="del(\'{sname}\',false,event)">{DEL_ICO}</button></div>'
            click   = f'onclick="location.href=\'{view_href}\'"'

        drag_attrs = f'draggable="true" data-name="{sname}" data-isdir="{str(is_dir).lower()}"'
        cb = f'<div class="card-cb" onclick="toggleSel(this,event)"><svg viewBox="0 0 12 12" fill="none" width="10" height="10"><polyline points="1,6 4,10 11,2" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>'
        out.append(f'<div class="card" {click} {drag_attrs}>{cb}{thumb}{actions}<div class="card-info"><span class="card-name" title="{sname}">{sname}</span><span class="card-meta">{meta}</span></div></div>')

    return "\n".join(out)


# ── LOGIN / REGISTER PAGE ─────────────────────────────
AUTH_HTML = r"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>SAFE CLOUD – Logowanie</title>
<link rel="icon" type="image/svg+xml" href="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0c14;--sur:#111827;--brd:#1e2535;
  --txt:#e6edf3;--muted:#7d8590;
  --acc:#818cf8;--acc2:#4f46e5;--red:#f85149;
}
body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
  background-image:
    radial-gradient(ellipse 160% 120% at 50% -10%, rgba(79,70,229,.55)  0%, rgba(109,40,217,.30) 38%, transparent 65%),
    radial-gradient(ellipse 60%  50% at 90% 100%,  rgba(67,56,202,.28)  0%, transparent 55%),
    radial-gradient(ellipse 45%  40% at 0%   70%,  rgba(124,58,237,.20) 0%, transparent 50%);
}
.card{background:var(--sur);border:1px solid var(--brd);border-radius:16px;padding:36px 32px;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.logo{display:flex;align-items:center;justify-content:center;gap:10px;font-weight:700;font-size:20px;margin-bottom:28px;font-family:'Audiowide',sans-serif;letter-spacing:.04em}
.lm{width:38px;height:38px;border-radius:10px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.tabs{display:flex;background:var(--bg);border:1px solid var(--brd);border-radius:8px;padding:3px;margin-bottom:24px;gap:3px}
.tab{flex:1;text-align:center;padding:7px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;color:var(--muted);transition:all .15s;user-select:none}
.tab.active{background:var(--sur);color:var(--txt);box-shadow:0 1px 3px rgba(0,0,0,.3)}
label{display:block;font-size:12px;font-weight:500;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
input{width:100%;padding:10px 13px;border:1px solid var(--brd);border-radius:8px;font-family:inherit;font-size:14px;color:var(--txt);background:var(--bg);outline:none;margin-bottom:16px;transition:border-color .15s}
input:focus{border-color:var(--acc)}
.submit{width:100%;padding:11px;border:none;border-radius:8px;background:var(--acc2);color:#e0e7ff;font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s;margin-top:4px}
.submit:hover{background:#4338ca}
.err{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.4);color:var(--red);border-radius:8px;padding:10px 13px;font-size:13px;margin-bottom:14px;display:%%ERR_DISPLAY%%}
.info{background:rgba(129,140,248,.1);border:1px solid rgba(129,140,248,.3);color:var(--acc);border-radius:8px;padding:10px 13px;font-size:13px;margin-bottom:14px;display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><div class="lm"><img src="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg" width="38" height="38" style="object-fit:contain"></div>SAFE CLOUD</div>
  <div style="text-align:center;margin-top:-18px;margin-bottom:20px;font-size:10px;font-family:'JetBrains Mono',monospace;color:#4a3570;letter-spacing:.04em;font-weight:600">%%APP_VERSION%%</div>
  <div class="tabs">
    <div class="tab %%TAB_LOGIN%%" id="t-login" onclick="switchTab('login')">Logowanie</div>
    <div class="tab %%TAB_REG%%" id="t-reg" onclick="switchTab('reg')">Rejestracja</div>
  </div>
  <div class="err" id="err">%%ERROR_MSG%%</div>
  <div class="info" id="info"></div>
  <div id="form-login" style="display:%%SHOW_LOGIN%%">
    <form method="POST" action="/login">
      <label>Nazwa użytkownika</label>
      <input type="text" name="username" placeholder="twoja_nazwa" autocomplete="username" required>
      <label>Hasło</label>
      <input type="password" name="password" placeholder="••••••••" autocomplete="current-password" required>
      <button class="submit" type="submit">Zaloguj się</button>
    </form>
  </div>
  <div id="form-reg" style="display:%%SHOW_REG%%">
    <form method="POST" action="/register">
      <label>Nazwa użytkownika</label>
      <input type="text" name="username" placeholder="twoja_nazwa" autocomplete="username" pattern="[a-zA-Z0-9_\-]+" title="Tylko litery, cyfry, _ i -" required>
      <label>Hasło</label>
      <input type="password" name="password" placeholder="min. 4 znaki" autocomplete="new-password" minlength="4" required>
      <label>Powtórz hasło</label>
      <input type="password" name="password2" placeholder="••••••••" autocomplete="new-password" required>
      <button class="submit" type="submit">Zarejestruj się</button>
    </form>
  </div>
</div>
<script>
function switchTab(t){
  document.getElementById('form-login').style.display = t==='login'?'block':'none';
  document.getElementById('form-reg').style.display   = t==='reg'?'block':'none';
  document.getElementById('t-login').className = 'tab'+(t==='login'?' active':'');
  document.getElementById('t-reg').className   = 'tab'+(t==='reg'?' active':'');
  document.getElementById('err').style.display='none';
}
</script>
</body>
</html>"""


MAIN_HTML = r"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>SAFE CLOUD%%ADMIN_TITLE%%</title>
<link rel="icon" type="image/svg+xml" href="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0c14;--sur:#111827;--brd:#1e2535;
  --txt:#e6edf3;--muted:#7d8590;
  --acc:#818cf8;--acc2:#4f46e5;
  --red:#f85149;--folder:#e3b341;
  --admin:#a78bfa;
  --r:12px;
}
body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;font-size:14px;
  overflow-y:scroll;scrollbar-width:none;
  background-image:
    radial-gradient(ellipse 160% 120% at 50% -10%, rgba(79,70,229,.55)  0%, rgba(109,40,217,.30) 38%, transparent 65%),
    radial-gradient(ellipse 60%  50% at 90% 100%,  rgba(67,56,202,.28)  0%, transparent 55%),
    radial-gradient(ellipse 45%  40% at 0%   70%,  rgba(124,58,237,.20) 0%, transparent 50%);
}
body::-webkit-scrollbar{display:none}
html{scrollbar-width:none}
html::-webkit-scrollbar{display:none}
header{background:rgba(10,12,20,.82);backdrop-filter:blur(18px);border:1px solid var(--brd);border-radius:10px;position:sticky;top:10px;z-index:50;margin:10px 10px 0;box-shadow:0 4px 24px rgba(0,0,0,.4)}
%%ADMIN_HEADER_STYLE%%
.hi{padding:0 20px;height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.logo{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px;color:var(--txt);text-decoration:none}
.brand{font-family:'Audiowide',sans-serif;letter-spacing:.04em}
.lm{width:30px;height:30px;border-radius:8px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.lm-admin{background:linear-gradient(135deg,#3730a3,#a78bfa);}
.hs{display:flex;align-items:center;gap:16px}
.st{font-size:12px;color:var(--muted)}
.st b{color:var(--txt);font-weight:500}
.user-badge{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:500;color:var(--txt)}
.avatar{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#3730a3,#818cf8);display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700;flex-shrink:0}
.avatar-admin{background:linear-gradient(135deg,#4c1d95,#a78bfa);}
.avatar-owner{background:linear-gradient(135deg,#92400e,#f59e0b);}
.admin-badge{font-size:10px;font-weight:700;background:rgba(167,139,250,.15);color:var(--admin);border:1px solid rgba(167,139,250,.35);border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.owner-badge{font-size:10px;font-weight:700;background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid rgba(245,158,11,.35);border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.role-badge{font-size:10px;font-weight:700;border:1px solid;border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.logout-btn{font-size:12px;color:var(--muted);background:none;border:1px solid var(--brd);border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;transition:all .15s}
.logout-btn:hover{color:var(--red);border-color:#6e3535;background:rgba(248,81,73,.08)}
.ver-badge{font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace;color:#4a3570;border-radius:4px;padding:1px 5px;letter-spacing:.04em;line-height:1.4;white-space:nowrap;align-self:center;margin-bottom:0;vertical-align:middle;position:relative;top:1px}

main{max-width:1200px;margin:0 auto;padding:24px 20px}

.bc{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:20px;font-size:13px;color:var(--muted)}
.bc a{color:var(--acc);text-decoration:none;font-weight:500}
.bc a:hover{text-decoration:underline}
.bc span{color:var(--muted)}

.dz{border:1.5px dashed var(--brd);border-radius:var(--r);background:var(--sur);padding:28px 20px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;margin-bottom:20px}
.dz:hover,.dz.over{border-color:var(--acc);background:rgba(129,140,248,.06)}
.dz-ic{display:flex;align-items:center;justify-content:center;margin-bottom:8px;transition:transform .2s}
.dz:hover .dz-ic,.dz.over .dz-ic{transform:translateY(-3px)}
.dz h3{font-size:14px;font-weight:600;margin-bottom:4px}
.dz p{font-size:12px;color:var(--muted)}
#fi{display:none}
.pw{display:none;margin-top:12px}
.pt{height:4px;background:var(--brd);border-radius:99px;overflow:hidden}
.pf{height:100%;background:var(--acc);border-radius:99px;transition:width .25s;width:0}
.pl{font-size:11px;color:var(--muted);margin-top:6px}

.tb{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;flex-wrap:wrap}
.tbl{display:flex;align-items:center;gap:8px}
.tbr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tl{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.cnt{font-size:12px;color:var(--muted);background:var(--bg);border:1px solid var(--brd);border-radius:99px;padding:2px 10px}
.btn{display:inline-flex;align-items:center;gap:6px;font-family:inherit;font-size:13px;font-weight:500;padding:7px 14px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:background .15s,border-color .15s;text-decoration:none;white-space:nowrap}
.btn:hover{background:#161d2e;border-color:#2d3a52}
.btnp{background:var(--acc2);border-color:var(--acc2);color:#e0e7ff}
.btnp:hover{background:#4338ca;border-color:#4338ca}
.sort-btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 10px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--muted);transition:all .15s;white-space:nowrap}
.sort-btn:hover,.sort-btn.active{color:var(--txt);border-color:#2d3a52;background:#161d2e}
.search-wrap{position:relative;display:flex;align-items:center}
.search-wrap svg{position:absolute;left:9px;color:var(--muted);pointer-events:none}
.search-inp{font-family:inherit;font-size:13px;padding:6px 10px 6px 30px;border-radius:8px;border:1px solid var(--brd);background:var(--bg);color:var(--txt);outline:none;width:180px;transition:border-color .15s,width .2s}
.search-inp:focus{border-color:var(--acc);width:220px}
.search-inp::placeholder{color:var(--muted)}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.card{background:var(--sur);border:1px solid var(--brd);border-radius:var(--r);overflow:hidden;cursor:pointer;transition:box-shadow .2s,border-color .2s;position:relative}
.card:hover{box-shadow:0 4px 20px rgba(79,70,229,.2);border-color:#2d3a52}
.card:active{opacity:.85}
.card-cb{position:absolute;top:6px;left:6px;z-index:10;width:18px;height:18px;border-radius:5px;border:2px solid rgba(255,255,255,.4);background:rgba(0,0,0,.4);cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .15s}
.card:hover .card-cb,.card.selected .card-cb{opacity:1}
.card.selected{border-color:var(--acc);box-shadow:0 0 0 2px rgba(129,140,248,.4)}
.card.selected .card-cb{background:var(--acc);border-color:var(--acc)}
.multi-bar{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(80px);background:#1a2035;border:1px solid #2d3a52;border-radius:14px;padding:10px 18px;display:flex;align-items:center;gap:12px;box-shadow:0 8px 32px rgba(0,0,0,.6);z-index:300;transition:transform .25s cubic-bezier(.34,1.56,.64,1);white-space:nowrap}
.multi-bar.show{transform:translateX(-50%) translateY(0)}
.multi-cnt{font-size:13px;font-weight:600;color:var(--txt);min-width:80px}
.multi-btn{font-family:inherit;font-size:12px;font-weight:500;padding:6px 14px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s;display:flex;align-items:center;gap:6px}
.multi-btn:hover{background:#161d2e;border-color:#2d3a52}
.multi-btn-red{border-color:#6e3535;color:var(--red)}
.multi-btn-red:hover{background:rgba(248,81,73,.1)}
.multi-btn-acc{border-color:var(--acc2);color:#c7d2fe;background:rgba(79,70,229,.15)}
.multi-btn-acc:hover{background:rgba(79,70,229,.3)}
.thumb{height:110px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.thumb-folder{background:rgba(227,179,65,.08);color:var(--folder)}
.thumb-img{background:var(--bg)}
.thumb-img img{width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
.thumb-img img.loaded{opacity:1}
.thumb-file{background:rgba(129,140,248,.07);color:#818cf8}
.thumb-audio{background:rgba(129,140,248,.07);color:#818cf8;position:relative;overflow:hidden}
.thumb-audio-inner{width:100%;height:100%;display:flex;align-items:center;justify-content:center;position:relative}
.thumb-audio-cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
.thumb-audio-cover.loaded{opacity:1}
.thumb-audio.has-cover .thumb-audio-inner svg{display:none}
.card-info{padding:10px 10px 11px;border-top:1px solid var(--brd)}
.card-name{display:block;font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px}
.card-meta{font-size:11px;color:var(--muted)}
.card-actions{position:absolute;top:7px;right:7px;display:flex;gap:4px;opacity:0;transition:opacity .15s}
.card:hover .card-actions{opacity:1}
.act{width:28px;height:28px;background:rgba(10,12,20,.9);border:1px solid var(--brd);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--txt);text-decoration:none;transition:background .15s}
.act:hover{background:#1e2535}
.act-del:hover{color:var(--red);border-color:#6e3535;background:rgba(248,81,73,.1)}
.share-ttl-btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 12px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--muted);transition:all .15s}
.share-ttl-btn:hover{color:var(--txt);border-color:#2d3a52}
.share-ttl-btn.active{background:rgba(79,70,229,.2);border-color:#4f46e5;color:#c7d2fe}

.card.drag-over{border-color:var(--acc)!important;box-shadow:0 0 0 2px rgba(129,140,248,.5),0 8px 32px rgba(79,70,229,.3)!important;background:rgba(129,140,248,.1)!important}
.card.drag-over .thumb{filter:brightness(1.15)}
.card.dragging-sel{opacity:.28;transform:scale(.95) rotate(-1deg);transition:opacity .2s,transform .2s;filter:saturate(.5)}
#drag-ghost{pointer-events:none}
.dg-stack{position:relative;width:160px;height:52px}
.dg-card{position:absolute;border-radius:10px;height:44px;display:flex;align-items:center;padding:0 12px;gap:8px;font-size:12px;font-weight:600;backdrop-filter:blur(12px)}
.dg-card1{background:rgba(26,32,53,.97);border:1.5px solid #4f46e5;box-shadow:0 8px 32px rgba(79,70,229,.55),0 2px 8px rgba(0,0,0,.4);color:#c7d2fe;top:4px;left:0;width:156px;z-index:3}
.dg-card2{background:rgba(30,38,64,.9);border:1.5px solid #3730a3;top:0px;left:8px;width:148px;z-index:2;transform:rotate(2.5deg);opacity:.85}
.dg-card3{background:rgba(35,44,75,.85);border:1.5px solid #312e81;top:-3px;left:14px;width:140px;z-index:1;transform:rotate(5deg);opacity:.65}
.dg-badge{background:linear-gradient(135deg,#4f46e5,#818cf8);border-radius:99px;min-width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;padding:0 5px;flex-shrink:0}
.dg-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px}

.empty-state{grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--muted)}
.empty-state p{font-size:14px;font-weight:500;color:var(--txt);margin:12px 0 4px}
.empty-state small{font-size:12px}

.mb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(6px);z-index:200;align-items:center;justify-content:center}
.mb.show{display:flex}
.modal{background:var(--sur);border:1px solid var(--brd);border-radius:14px;padding:24px;width:360px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.6)}
.modal h3{font-size:15px;font-weight:600;margin-bottom:14px}
.modal input{width:100%;padding:9px 12px;border:1px solid var(--brd);border-radius:8px;font-family:inherit;font-size:14px;color:var(--txt);background:var(--bg);outline:none;margin-bottom:14px;transition:border-color .15s}
.modal input:focus{border-color:var(--acc)}
.mbtns{display:flex;gap:8px;justify-content:flex-end}
.rename-row{display:flex;align-items:center;border:1px solid var(--brd);border-radius:8px;background:var(--bg);margin-bottom:14px;overflow:hidden;transition:border-color .15s}
.rename-row:focus-within{border-color:var(--acc)}
.rename-row input{flex:1;padding:9px 12px;border:none;font-family:inherit;font-size:14px;color:var(--txt);background:transparent;outline:none}
.rename-ext{padding:9px 12px 9px 0;font-size:14px;color:var(--muted);white-space:nowrap;user-select:none}

.toast{position:fixed;bottom:24px;right:20px;left:20px;max-width:340px;margin:0 auto;background:#1e2535;border:1px solid var(--brd);color:var(--txt);border-radius:10px;padding:12px 16px;font-size:13px;font-weight:500;z-index:300;pointer-events:none;transform:translateY(80px);opacity:0;transition:all .3s;display:flex;align-items:center;gap:8px}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{background:rgba(248,81,73,.15);border-color:#6e3535;color:var(--red)}

.term-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);z-index:399;opacity:0;pointer-events:none;transition:opacity .25s ease}
.term-overlay.open{opacity:1;pointer-events:all}
.term-fab{display:none}
.term-fab-btn{display:none!important}
.term-header-btn{font-family:inherit;font-size:12px;font-weight:500;padding:6px 12px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s;display:flex;align-items:center;gap:6px}
.term-header-btn:hover{background:#161d2e;border-color:#4f46e5;color:#c7d2fe}
.term-header-btn.open{background:rgba(79,70,229,.2);border-color:#4f46e5;color:#c7d2fe}
.term-panel{position:fixed;bottom:20px;right:20px;width:480px;max-width:calc(100vw - 40px);height:380px;background:#0d1117;border:1px solid var(--brd);border-radius:12px;box-shadow:0 16px 64px rgba(0,0,0,.7);z-index:400;display:none;flex-direction:column;overflow:hidden;transform:translateY(20px) scale(.97);opacity:0;pointer-events:none;transition:transform .2s cubic-bezier(.34,1.56,.64,1),opacity .2s}
.term-panel.open{transform:translateY(0) scale(1);opacity:1;pointer-events:all}
.term-slider-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--sur);border-bottom:1px solid var(--brd);flex-shrink:0}
.term-slider-close{background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1;transition:color .15s}
.term-slider-close:hover{color:var(--red)}
.term-title{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;display:flex;align-items:center;gap:7px}
.term-dot{width:7px;height:7px;border-radius:50%}
.term-out{flex:1;overflow-y:auto;padding:12px 16px;font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;color:#7d8590}
.term-out .tline{padding:1px 0;border-left:2px solid transparent;padding-left:8px}
.term-out .tline.ok{color:#3fb950;border-left-color:#3fb950}
.term-out .tline.err{color:#f85149;border-left-color:#f85149}
.term-out .tline.cmd{color:#818cf8;border-left-color:#818cf8}
.term-bar{display:flex;align-items:center;gap:8px;padding:10px 16px;border-top:1px solid var(--brd);background:#0a0c14;flex-shrink:0}
.term-prefix{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--acc)}
.term-input{flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;background:transparent;border:none;outline:none;color:var(--txt);caret-color:var(--acc)}
.term-input::placeholder{color:#2d3a52}
.term-send{font-family:inherit;font-size:12px;font-weight:500;padding:4px 10px;border-radius:6px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s}
.term-send:hover{background:var(--acc2);border-color:var(--acc2);color:#e0e7ff}

/* ── HAMBURGER MENU ── */
.ham-btn{display:none;flex-direction:column;justify-content:center;align-items:center;width:40px;height:40px;gap:5px;background:none;border:1px solid var(--brd);border-radius:8px;cursor:pointer;padding:0;transition:background .15s,border-color .15s;flex-shrink:0;-webkit-tap-highlight-color:transparent;touch-action:manipulation;user-select:none}
.ham-btn:hover{background:#161d2e;border-color:#2d3a52}
.ham-btn span{display:block;width:16px;height:2px;background:var(--txt);border-radius:2px;transition:transform .25s,opacity .25s,width .25s}
.ham-btn.open span:nth-child(1){transform:translateY(7px) rotate(45deg)}
.ham-btn.open span:nth-child(2){opacity:0;width:0}
.ham-btn.open span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}

.mob-menu{position:fixed;top:0;left:0;right:0;bottom:0;z-index:400;display:flex;visibility:hidden;pointer-events:none}
.mob-menu.open{visibility:visible;pointer-events:all}
.mob-menu-overlay{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.55);backdrop-filter:blur(4px);z-index:1;-webkit-tap-highlight-color:transparent;opacity:0;transition:opacity .3s ease}
.mob-menu.open .mob-menu-overlay{opacity:1}
.mob-menu-panel{position:relative;z-index:2;margin-left:auto;width:min(280px,85vw);height:100%;background:#0d1017;border-left:1px solid var(--brd);box-shadow:-8px 0 40px rgba(0,0,0,.6);transform:translateX(calc(100% + 50px));transition:transform .32s cubic-bezier(.34,1.1,.64,1);display:flex;flex-direction:column;padding:0;flex-shrink:0;overflow:hidden}
.mob-menu.open .mob-menu-panel{transform:translateX(0)}
.mob-menu-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--brd);user-select:none}
.mob-menu-user{display:flex;align-items:center;gap:12px}
.mob-menu-user-info{display:flex;flex-direction:column;gap:5px}
.mob-menu-close{width:34px;height:34px;background:none;border:1px solid var(--brd);border-radius:7px;cursor:pointer;color:var(--txt);display:flex;align-items:center;justify-content:center;font-size:16px;transition:background .15s;-webkit-tap-highlight-color:transparent;touch-action:manipulation;flex-shrink:0}
.mob-menu-close:hover{background:#1e2535}
.mob-menu-body{flex:1;padding:0;overflow-y:auto;-webkit-overflow-scrolling:touch}
.mob-menu-item{display:flex;align-items:center;justify-content:center;gap:10px;padding:13px 16px;font-size:15px;font-weight:500;color:var(--txt);text-decoration:none;cursor:pointer;transition:background .15s;border:none;background:none;width:100%;font-family:inherit;text-align:center;user-select:none;-webkit-tap-highlight-color:transparent;touch-action:manipulation;-webkit-user-select:none}
.mob-menu-item:active{background:rgba(129,140,248,.15)}
.mob-menu-item svg{color:var(--muted);flex-shrink:0}
.mob-menu-sep{height:1px;background:var(--brd);margin:0}
.mob-menu-stat{padding:10px 16px;font-size:11px;color:var(--muted);user-select:none;text-align:center}
.mob-menu-stat b{color:var(--txt);font-weight:500}
.mob-menu-item.red{color:var(--red)}
.mob-menu-item.red svg{color:var(--red)}

@media(max-width:600px){
  .hs{display:none!important}
  .ham-btn{display:flex!important}
  .grid{grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px}
  .thumb{height:95px}
  main{padding:16px 14px}
  .card-actions{opacity:1}
  .hi{padding:0 14px}
  .term-fab{display:none!important}
}
@media(min-width:601px){
  .ham-btn{display:none!important}
  .mob-menu{visibility:hidden!important;pointer-events:none!important}
}
@media(max-width:480px){
  .grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
}
.sbar{display:flex;align-items:center;gap:0;background:#0a0c14;border-bottom:1px solid var(--brd);padding:0 18px;height:32px;font-size:11px;font-family:'JetBrains Mono',monospace;overflow-x:auto;flex-wrap:nowrap}
.sbar-item{display:flex;align-items:center;gap:5px;padding:0 12px;border-right:1px solid var(--brd);white-space:nowrap;color:var(--muted)}
.sbar-item:first-child{padding-left:0}
.sbar-item:last-child{border-right:none}
.sbar-lbl{color:#3d4a5e;font-size:10px;text-transform:uppercase;letter-spacing:.04em}
.sbar-val{color:#e2e8f0;font-weight:600}
.sbar-val.warn{color:#f59e0b}
.sbar-val.over{color:#f85149}
.sbar-dot{width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0}
.sbar-dot.warn{background:#f59e0b}
.sbar-dot.over{background:#f85149}
.mob-stats-block{margin:16px 16px 12px;padding:0;text-align:center}
.mob-stats-block .msb-title{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#3d4a5e;margin-bottom:10px;font-weight:600;text-align:center}
.mob-stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.msb-row{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:8px 6px;background:#0d1117;border-radius:9px;border:1px solid var(--brd)}
.msb-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.05em;color:#3d4a5e}
.msb-val{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#e2e8f0}
.msb-val.warn{color:#f59e0b}
.msb-val.over{color:#f85149}
@media(max-width:600px){
  .sbar{height:auto;padding:6px 14px;flex-wrap:wrap;gap:4px 0}
  .sbar-item{padding:2px 10px;border-right:1px solid var(--brd)}
}
</style>
</head>
<body>
<header%%ADMIN_HEADER_ATTR%%>
  <div class="hi">
    <a class="logo" href="/?path="><div class="lm%%ADMIN_LM%%"><img src="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg" width="30" height="30" style="object-fit:contain"></div><span class="brand">%%HEADER_TITLE%%</span><span class="ver-badge">%%APP_VERSION%%</span></a>
    <div class="hs">
      <div class="st">Pliki: <b>%%FILE_COUNT%%</b></div>
      <div class="st">Zajęte: <b>%%TOTAL_SIZE%%</b></div>
      <div class="user-badge">
        <div class="avatar%%ADMIN_AVATAR%%">%%USER_INITIAL%%</div>
        <span>%%USERNAME%%</span>
        %%ADMIN_BADGE%%
      </div>
      <form method="POST" action="/logout" style="margin:0">
        <button class="logout-btn" type="submit">Wyloguj</button>
      </form>
      %%TERMINAL_BTN%%
    </div>
    <!-- Hamburger button – only on mobile -->
    <button class="ham-btn" id="ham-btn" aria-label="Menu">
      <span></span><span></span><span></span>
    </button>
  </div>
</header>

<!-- Mobile slide-in menu -->
<div class="mob-menu" id="mob-menu">
  <div class="mob-menu-overlay" id="mob-overlay" onclick="closeMobMenu()"></div>
  <div class="mob-menu-panel">
    <div class="mob-menu-head">
      <div class="mob-menu-user">
        <div class="avatar%%ADMIN_AVATAR%%">%%USER_INITIAL%%</div>
        <div class="mob-menu-user-info">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span style="font-size:14px;font-weight:600;line-height:1">%%USERNAME%%</span>%%ADMIN_BADGE%%</div>
        </div>
      </div>
      <button class="mob-menu-close" onclick="closeMobMenu()">&#x2715;</button>
    </div>
    <div class="mob-menu-stat">Pliki: <b>%%FILE_COUNT%%</b> &nbsp;&middot;&nbsp; Zajęte: <b>%%TOTAL_SIZE%%</b></div>
    <div class="mob-menu-sep"></div>
    <div class="mob-menu-body">
      <a class="mob-menu-item" href="/?path=">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        Strona główna
      </a>
      <button class="mob-menu-item" data-mob-action="newFolder">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
        Nowy folder
      </button>
      <button class="mob-menu-item" data-mob-action="upload">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        Prześlij pliki
      </button>
      <div class="mob-menu-sep"></div>
      <form method="POST" action="/logout" style="margin:0">
        <button class="mob-menu-item red" type="submit">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          Wyloguj
        </button>
      </form>
      %%MOB_STATS_BLOCK%%
      %%MOB_TERMINAL_ITEM%%
      %%MOB_RESTART_BTN%%
    </div>
  </div>
</div>

<main>
  <nav class="bc">%%BREADCRUMB%%</nav>

  <div class="dz" id="dz" role="button" tabindex="0" onclick="document.getElementById('fi').click()">
    <input type="file" id="fi" multiple>
    <input type="file" id="fi-dir" webkitdirectory multiple style="display:none">
    <div class="dz-ic">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="36" height="36">
        <defs>
          <linearGradient id="upg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#818cf8"/>
            <stop offset="100%" stop-color="#4f46e5"/>
          </linearGradient>
        </defs>
        <path d="M12 3L12 15" stroke="url(#upg)" stroke-width="2" stroke-linecap="round"/>
        <path d="M7 8L12 3L17 8" stroke="url(#upg)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M4 17v1a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-1" stroke="url(#upg)" stroke-width="2" stroke-linecap="round"/>
      </svg>
    </div>
    <h3>Prześlij pliki</h3>
    <p>Przeciągnij tutaj lub kliknij &mdash; brak limitu rozmiaru</p>
    <button class="btn" style="margin-top:10px;font-size:12px;padding:5px 12px" onclick="event.stopPropagation();document.getElementById('fi-dir').click()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
      Prześlij folder
    </button>
    <div class="pw" id="pw">
      <div class="pt"><div class="pf" id="pf"></div></div>
      <div class="pl" id="pl"></div>
    </div>
  </div>

  <div class="tb">
    <div class="tbl">
      <span class="tl">Pliki</span>
      <span class="cnt">%%TOTAL_ITEMS%% elementów</span>
    </div>
    <div class="tbr">
      <div class="search-wrap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input class="search-inp" id="search-inp" type="text" placeholder="Szukaj..." value="%%SEARCH_VAL%%" oninput="applySearch(this.value)">
      </div>
      <button class="sort-btn %%SORT_NAME_ACTIVE%%" onclick="setSort('name')">Nazwa %%SORT_NAME_ICO%%</button>
      <button class="sort-btn %%SORT_DATE_ACTIVE%%" onclick="setSort('date')">Data %%SORT_DATE_ICO%%</button>
      <button class="sort-btn %%SORT_SIZE_ACTIVE%%" onclick="setSort('size')">Rozmiar %%SORT_SIZE_ICO%%</button>
      <button class="btn" onclick="openModal()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>
        Nowy folder
      </button>
    </div>
  </div>

  <div class="grid">%%FILE_CARDS%%</div>
</main>

<div class="multi-bar" id="multi-bar">
  <span class="multi-cnt" id="multi-cnt">0 zaznaczonych</span>
  <button class="multi-btn multi-btn-acc" onclick="multiZip()">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    Pobierz ZIP
  </button>
  <button class="multi-btn" onclick="multiMove()">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/></svg>
    Przenieś
  </button>
  <button class="multi-btn multi-btn-red" onclick="multiDelete()">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
    Usuń
  </button>
  <button class="multi-btn" onclick="clearSel()" style="padding:6px 10px">&#x2715;</button>
</div>

<div class="mb" id="mb-move" style="display:none" onclick="if(event.target===this)closeMoveModal()">
  <div class="modal">
    <h3>Przenieś do folderu</h3>
    <input type="text" id="move-dst" placeholder="Ścieżka folderu (np. /dokumenty)" style="margin-bottom:8px">
    <div style="font-size:11px;color:var(--muted);margin-bottom:16px">Zostaw puste aby przenieść do głównego folderu</div>
    <div class="mbtns">
      <button class="btn" onclick="closeMoveModal()">Anuluj</button>
      <button class="btn btnp" onclick="confirmMultiMove()">Przenieś</button>
    </div>
  </div>
</div>

<div class="term-overlay" id="term-overlay" onclick="toggleTerm()"></div>
<div class="term-panel" id="term-panel">
  <div class="term-slider-header">
    <div class="term-title">
      <span class="term-dot" style="background:#3fb950"></span>
      <span class="term-dot" style="background:#e3b341"></span>
      <span class="term-dot" style="background:#f85149"></span>
      &nbsp;Terminal admina
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      <a class="btn" href="/console" style="font-size:11px;padding:3px 8px;text-decoration:none">Pełny widok &#x2197;</a>
      <button class="term-slider-close" onclick="toggleTerm()">&#x2715;</button>
    </div>
  </div>
  <div class="term-out" id="term-out"></div>
  <div class="term-bar">
    <span class="term-prefix">$</span>
    <input class="term-input" id="term-input" placeholder="Wpisz komendę..." autocomplete="off" spellcheck="false">
    <button class="term-send" onclick="sendTermCmd()">Wyślij</button>
  </div>
</div>

<div class="mb" id="mb">
  <div class="modal">
    <h3>Nowy folder</h3>
    <input type="text" id="fi2" placeholder="Nazwa folderu..." onkeydown="if(event.key==='Enter')mkDir()">
    <div class="mbtns">
      <button class="btn" onclick="closeModal()">Anuluj</button>
      <button class="btn btnp" onclick="mkDir()">Utwórz</button>
    </div>
  </div>
</div>

<div class="mb" id="mb-rename">
  <div class="modal">
    <h3 id="rename-title">Zmień nazwę</h3>
    <div class="rename-row">
      <input type="text" id="rename-inp" placeholder="Nowa nazwa..." onkeydown="if(event.key==='Enter')doRename()">
      <span class="rename-ext" id="rename-ext"></span>
    </div>
    <div class="mbtns">
      <button class="btn" onclick="closeRename()">Anuluj</button>
      <button class="btn btnp" onclick="doRename()">Zmień</button>
    </div>
  </div>
</div>

<div class="mb" id="mb-share">
  <div class="modal" style="max-width:460px">
    <h3>🔗 Udostępnij plik</h3>
    <p style="font-size:13px;color:var(--muted);margin:6px 0 14px">Wygeneruj jednorazowy link do pobrania pliku <b id="share-fname"></b></p>
    <div style="margin-bottom:14px">
      <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:6px">Czas wygaśnięcia</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="share-ttl-btn active" data-ttl="1">1h</button>
        <button class="share-ttl-btn" data-ttl="6">6h</button>
        <button class="share-ttl-btn" data-ttl="24">24h</button>
        <button class="share-ttl-btn" data-ttl="72">3 dni</button>
        <button class="share-ttl-btn" data-ttl="168">7 dni</button>
        <button class="share-ttl-btn" data-ttl="0">Bez limitu</button>
      </div>
    </div>
    <div id="share-result" style="display:none;margin-bottom:14px">
      <label style="font-size:12px;color:var(--muted);display:block;margin-bottom:6px">Link do udostępnienia</label>
      <div style="display:flex;gap:8px;align-items:center">
        <input id="share-link-inp" type="text" readonly style="flex:1;font-family:'JetBrains Mono',monospace;font-size:11px;background:var(--bg);border:1px solid var(--brd);border-radius:7px;padding:7px 10px;color:var(--txt);outline:none">
        <button class="btn btnp" onclick="copyShareLink()" style="flex-shrink:0">Kopiuj</button>
      </div>
      <p id="share-exp-info" style="font-size:11px;color:var(--muted);margin-top:6px"></p>
    </div>
    <div class="mbtns">
      <button class="btn" onclick="closeShare()">Zamknij</button>
      <button class="btn btnp" id="share-gen-btn" onclick="genShare()">Generuj link</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const CUR="%%CURRENT_PATH%%";
let SORT_BY="%%SORT_BY%%", SORT_DIR="%%SORT_DIR%%";
let _t;
function toast(m,err){const t=document.getElementById("toast");t.textContent=m;t.className="toast show"+(err?" err":"");clearTimeout(_t);_t=setTimeout(()=>t.className="toast",3200)}

// ── Upload ────────────────────────────────────────────
const dz=document.getElementById("dz");
dz.addEventListener("dragover",e=>{e.preventDefault();dz.classList.add("over")});
dz.addEventListener("dragleave",()=>dz.classList.remove("over"));
dz.addEventListener("drop",e=>{e.preventDefault();dz.classList.remove("over");uploadItems(e.dataTransfer)});
// iOS fix: touchend na dz
dz.addEventListener("touchend",e=>{e.preventDefault();document.getElementById('fi').click();});
document.getElementById("fi").addEventListener("change",e=>upload(e.target.files));
document.getElementById("fi-dir").addEventListener("change",e=>upload(e.target.files));
async function uploadItems(dt){
  // obsługa przeciągniętych folderów przez DataTransferItemList
  if(dt.items&&dt.items.length){
    const files=[];
    const readEntry=(entry,path)=>new Promise(res=>{
      if(entry.isFile){
        entry.file(f=>{Object.defineProperty(f,'_relPath',{value:path+f.name});files.push(f);res();});
      } else if(entry.isDirectory){
        const reader=entry.createReader();
        const readAll=(acc=[])=>{
          reader.readEntries(entries=>{
            if(!entries.length){Promise.all(acc.map(e=>readEntry(e,path+entry.name+'/'))).then(res);return;}
            acc.push(...entries);readAll(acc);
          });
        };readAll();
      } else res();
    });
    await Promise.all([...dt.items].map(item=>{
      const e=item.webkitGetAsEntry&&item.webkitGetAsEntry();
      return e?readEntry(e,''):Promise.resolve();
    }));
    if(files.length)return upload(files,true);
  }
  upload(dt.files);
}
async function upload(files,hasRelPath=false){
  if(!files.length)return;
  const pw=document.getElementById("pw"),pf=document.getElementById("pf"),pl=document.getElementById("pl");
  pw.style.display="block";
  const arr=[...files];
  const total=arr.length;
  let done=0,ok=0,fail=0;
  const CONCURRENCY=6;

  function getFilePath(file){
    const rel=file._relPath||(file.webkitRelativePath||'');
    if(!rel)return CUR;
    const parts=rel.split('/');
    const subdir=parts.slice(0,-1).join('/');
    return CUR?(subdir?CUR+'/'+subdir:CUR):(subdir||'');
  }

  async function uploadOne(file){
    const fd=new FormData();
    fd.append("path",getFilePath(file));
    fd.append("file",file);
    try{
      const r=await fetch("/upload",{method:"POST",body:fd});
      const d=await r.json();
      if(d.ok)ok++;else{fail++;toast("Błąd: "+d.error,true);}
    }catch{fail++;toast("Błąd sieci",true);}
    done++;
    pf.style.width=(done/total*100)+"%";
    pl.textContent=`${done} / ${total}${fail?' · ✗ '+fail:''}`;
  }

  // pula – max CONCURRENCY requestów naraz
  const queue=[...arr];
  async function worker(){
    while(queue.length){
      const file=queue.shift();
      if(file)await uploadOne(file);
    }
  }
  await Promise.all(Array.from({length:Math.min(CONCURRENCY,total)},worker));

  pf.style.width="100%";
  if(ok)toast(`✓ Przesłano ${ok} plik${ok===1?"":"ów"}`+(fail?` · ✗ ${fail} błędów`:""));
  setTimeout(()=>{pw.style.display="none";pf.style.width="0";location.reload();},700);
}

// ── Delete ───────────────────────────────────────────
async function del(name,isDir,e){
  e.stopPropagation();e.preventDefault();
  if(!confirm(`Usunac "${name}"?`))return;
  const r=await fetch("/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:CUR,name,isDir})});
  const d=await r.json();
  if(d.ok){toast("Usunieto");setTimeout(()=>location.reload(),500)}else toast("Blad: "+d.error,true);
}

// ── Mkdir ────────────────────────────────────────────
function openModal(){document.getElementById("mb").classList.add("show");document.getElementById("fi2").focus()}
function closeModal(){document.getElementById("mb").classList.remove("show");document.getElementById("fi2").value=""}
document.getElementById("mb").addEventListener("click",e=>{if(e.target===document.getElementById("mb"))closeModal()});
async function mkDir(){
  const name=document.getElementById("fi2").value.trim();if(!name)return;
  const r=await fetch("/mkdir",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:CUR,name})});
  const d=await r.json();closeModal();
  if(d.ok){toast("Folder utworzony");setTimeout(()=>location.reload(),500)}else toast("Blad: "+d.error,true);
}

// ── Rename ───────────────────────────────────────────
let _renameOld="",_renameIsDir=false,_renameExt="";
function renameItem(name,isDir,e){
  e.stopPropagation();e.preventDefault();
  _renameOld=name;_renameIsDir=isDir;
  // wyodrębnij rozszerzenie (tylko dla plików)
  if(!isDir){
    const dot=name.lastIndexOf(".");
    _renameExt=(dot>0)?name.slice(dot):"";
  } else {
    _renameExt="";
  }
  const baseName=_renameExt?name.slice(0,name.length-_renameExt.length):name;
  document.getElementById("rename-title").textContent=isDir?"Zmień nazwę folderu":"Zmień nazwę pliku";
  const inp=document.getElementById("rename-inp");
  const suf=document.getElementById("rename-ext");
  inp.value=baseName;
  suf.textContent=_renameExt;
  document.getElementById("mb-rename").classList.add("show");
  setTimeout(()=>{inp.focus();inp.select();},50);
}
function closeRename(){document.getElementById("mb-rename").classList.remove("show");document.getElementById("rename-inp").value="";}
document.getElementById("mb-rename").addEventListener("click",e=>{if(e.target===document.getElementById("mb-rename"))closeRename()});
async function doRename(){
  const base=document.getElementById("rename-inp").value.trim();
  if(!base){closeRename();return;}
  const newName=base+_renameExt;
  if(newName===_renameOld){closeRename();return;}
  const r=await fetch("/rename",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:CUR,old:_renameOld,new:newName})});
  const d=await r.json();closeRename();
  if(d.ok){toast("✓ Zmieniono nazwę");setTimeout(()=>location.reload(),500)}else toast("✗ "+d.error,true);
}

// ── Udostępnianie pliku ──────────────────────────────
let _shareName = "";
function shareItem(name, e){
  if(e){e.stopPropagation();}
  _shareName = name;
  document.getElementById("share-fname").textContent = name;
  document.getElementById("share-result").style.display = "none";
  document.getElementById("share-gen-btn").style.display = "";
  // reset TTL buttons
  document.querySelectorAll(".share-ttl-btn").forEach(b=>b.classList.remove("active"));
  document.querySelector(".share-ttl-btn[data-ttl='1']").classList.add("active");
  document.getElementById("mb-share").classList.add("show");
}
function closeShare(){
  document.getElementById("mb-share").classList.remove("show");
  _shareName = "";
}
document.getElementById("mb-share").addEventListener("click",e=>{if(e.target===document.getElementById("mb-share"))closeShare()});
document.querySelectorAll(".share-ttl-btn").forEach(btn=>{
  btn.addEventListener("click",()=>{
    document.querySelectorAll(".share-ttl-btn").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");
  });
});
async function genShare(){
  const ttlBtn = document.querySelector(".share-ttl-btn.active");
  const ttl = ttlBtn ? parseInt(ttlBtn.dataset.ttl) : 1;
  const r = await fetch("/share/create", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({path: CUR, name: _shareName, ttl_hours: ttl || null})});
  const d = await r.json();
  if(!d.ok){toast("✗ "+d.error, true); return;}
  const link = location.origin + "/s/" + d.token;
  document.getElementById("share-link-inp").value = link;
  document.getElementById("share-result").style.display = "";
  document.getElementById("share-gen-btn").style.display = "none";
  const exp = ttl ? `Wygasa za ${ttlBtn.textContent}` : "Bez limitu czasowego";
  document.getElementById("share-exp-info").textContent = "⏱ " + exp + " · link jednorazowy po 1 pobraniu";
}
function copyShareLink(){
  const inp = document.getElementById("share-link-inp");
  navigator.clipboard.writeText(inp.value).then(()=>toast("✓ Link skopiowany do schowka")).catch(()=>{
    inp.select(); document.execCommand("copy"); toast("✓ Link skopiowany");
  });
}


function setSort(by){
  if(SORT_BY===by){SORT_DIR=SORT_DIR==="asc"?"desc":"asc";}
  else{SORT_BY=by;SORT_DIR="asc";}
  const url=new URL(location.href);
  url.searchParams.set("sort",SORT_BY);
  url.searchParams.set("dir",SORT_DIR);
  location.href=url.toString();
}

// ── Wyszukiwanie ─────────────────────────────────────
let _searchTimer;
function applySearch(val){
  clearTimeout(_searchTimer);
  _searchTimer=setTimeout(()=>{
    const url=new URL(location.href);
    if(val.trim())url.searchParams.set("q",val.trim());
    else url.searchParams.delete("q");
    url.searchParams.set("path",CUR);
    location.href=url.toString();
  },400);
}

// ── Drag & Drop (przenoszenie do folderów) ────────────
// ── Zaznaczanie wielu plików ──────────────────────────
let _sel=new Set();
function toggleSel(cb,e){
  e.stopPropagation();
  const card=cb.closest('.card');
  const name=card.dataset.name;
  if(_sel.has(name)){_sel.delete(name);card.classList.remove('selected');}
  else{_sel.add(name);card.classList.add('selected');}
  updateMultiBar();
}
function updateMultiBar(){
  const bar=document.getElementById('multi-bar');
  document.getElementById('multi-cnt').textContent=_sel.size+' zaznaczonych';
  bar.classList.toggle('show',_sel.size>0);
}
function clearSel(){
  _sel.clear();
  document.querySelectorAll('.card.selected').forEach(c=>c.classList.remove('selected'));
  updateMultiBar();
}
async function multiDelete(){
  if(!_sel.size)return;
  if(!confirm('Usunąć '+_sel.size+' elementów?'))return;
  for(const name of _sel){
    const card=[...document.querySelectorAll('.card')].find(c=>c.dataset.name===name);
    const isDir=card&&card.dataset.isdir==='true';
    await fetch('/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:CUR.replace(/^\/+/,''),name,isDir})});
  }
  toast('✓ Usunięto '+_sel.size+' elementów');setTimeout(()=>location.reload(),600);
}
function multiMove(){
  if(!_sel.size)return;
  document.getElementById('mb-move').style.display='flex';
  setTimeout(()=>document.getElementById('move-dst').focus(),50);
}
function closeMoveModal(){document.getElementById('mb-move').style.display='none';}
async function confirmMultiMove(){
  const dst=(document.getElementById('move-dst').value||'').trim().replace(/^\/+/,'');
  let ok=0,fail=0;
  for(const name of _sel){
    const src=(CUR+'/'+name).replace(/^\/+/,'');
    const r=await fetch('/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({src,dst_folder:dst})});
    const d=await r.json();
    if(d.ok)ok++;else fail++;
  }
  closeMoveModal();
  toast('✓ Przeniesiono: '+ok+(fail?' ✗ Błędy: '+fail:''));
  setTimeout(()=>location.reload(),700);
}
async function dlFolder(name,e){
  e.stopPropagation();
  toast('Pakowanie: '+name+'...');
  const path=CUR.replace(/^\/+/,'');
  const r=await fetch('/zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,names:[name]})});
  if(!r.ok){toast('✗ Błąd ZIP',true);return;}
  const blob=await r.blob();
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=name+'.zip';a.click();
  URL.revokeObjectURL(url);
  toast('✓ Pobrano: '+name+'.zip');
}
async function multiZip(){
  if(!_sel.size)return;
  const names=[..._sel];
  const path=CUR.replace(/^\/+/,'');
  toast('Pakowanie '+names.length+' plików...');
  const r=await fetch('/zip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,names})});
  if(!r.ok){toast('✗ Błąd ZIP',true);return;}
  const blob=await r.blob();
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='pobrane.zip';a.click();
  URL.revokeObjectURL(url);
  clearSel();
}

// ── Shift+click zaznaczanie ───────────────────────────
document.addEventListener('click',e=>{
  if(!e.shiftKey)return;
  const card=e.target.closest('.card[data-name]');
  if(!card)return;
  // nie blokuj checkboxa
  if(e.target.closest('.card-cb'))return;
  e.preventDefault();e.stopPropagation();
  const name=card.dataset.name;
  if(_sel.has(name)){_sel.delete(name);card.classList.remove('selected');}
  else{_sel.add(name);card.classList.add('selected');}
  updateMultiBar();
},true);

// ── Drag & Drop (multi) ───────────────────────────────
let _dragName=null;

// Ghost element – tworzony dynamicznie
let _ghost=null;
function _makeGhost(names){
  if(_ghost){_ghost.remove();_ghost=null;}
  _ghost=document.createElement('div');
  _ghost.id='drag-ghost';
  const cnt=names.length;
  const label=cnt===1?names[0]:(cnt+' plik\xf3w');
  _ghost.innerHTML=
    '<div class="dg-stack">'+
      (cnt>1?'<div class="dg-card dg-card3"></div><div class="dg-card dg-card2"></div>':'')+
      '<div class="dg-card dg-card1">'+
        '<div class="dg-badge">'+cnt+'</div>'+
        '<span class="dg-label">'+label+'</span>'+
      '</div>'+
    '</div>';
  _ghost.style.cssText='position:fixed;top:-999px;left:-999px;pointer-events:none;z-index:9999';
  document.body.appendChild(_ghost);
  return _ghost;
}

document.addEventListener("dragstart",e=>{
  const card=e.target.closest(".card[data-name]");
  if(!card)return;
  _dragName=card.dataset.name;
  // jeśli przeciągany plik nie jest zaznaczony – zaznacz tylko jego
  if(!_sel.has(_dragName)){
    clearSel();
    _sel.add(_dragName);
    card.classList.add('selected');
    updateMultiBar();
  }
  const names=[..._sel];
  const g=_makeGhost(names);
  e.dataTransfer.setDragImage(g,-40,-20);
  e.dataTransfer.effectAllowed="move";
  e.dataTransfer.setData("text/plain",_dragName);
  // animacja zaznaczonych
  names.forEach(n=>{
    const c=document.querySelector('.card[data-name]');
    document.querySelectorAll('.card').forEach(cc=>{
      if(cc.dataset.name===n)cc.classList.add('dragging-sel');
    });
  });
});

document.addEventListener("dragend",e=>{
  if(_ghost){_ghost.remove();_ghost=null;}
  document.querySelectorAll(".card.dragging-sel").forEach(c=>c.classList.remove("dragging-sel"));
  document.querySelectorAll(".card.drag-over").forEach(c=>c.classList.remove("drag-over"));
});

document.addEventListener("dragover",e=>{
  const card=e.target.closest(".card[data-isdir='true']");
  if(card&&!_sel.has(card.dataset.name)){
    e.preventDefault();
    document.querySelectorAll(".card.drag-over").forEach(c=>{if(c!==card)c.classList.remove("drag-over")});
    card.classList.add("drag-over");
  }
});

document.addEventListener("dragleave",e=>{
  const card=e.target.closest(".card[data-isdir='true']");
  if(card&&!card.contains(e.relatedTarget))card.classList.remove("drag-over");
});

document.addEventListener("drop",e=>{
  const card=e.target.closest(".card[data-isdir='true']");
  if(!card||_sel.has(card.dataset.name))return;
  e.preventDefault();
  card.classList.remove("drag-over");
  const dstFolder=(CUR+"/"+card.dataset.name).replace(/^\/+/,"");
  const names=[..._sel];
  let ok=0,fail=0;
  Promise.all(names.map(name=>{
    const src=(CUR+"/"+name).replace(/^\/+/,"");
    return fetch("/move",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({src,dst_folder:dstFolder})})
      .then(r=>r.json()).then(d=>{if(d.ok)ok++;else fail++;});
  })).then(()=>{
    if(ok)toast("\u2713 Przeniesiono "+ok+(ok>1?" element\xf3w":"")+" \u2192 "+card.dataset.name+(fail?" (\u2717 "+fail+" b\u0142\u0119d\xf3w)":""),fail>0);
    else toast("\u2717 B\u0142\u0105d przenoszenia",true);
    clearSel();
    setTimeout(()=>location.reload(),700);
  });
});

// ── Terminal ─────────────────────────────────────────
async function sendTermCmd(){
  const inp=document.getElementById('term-input');
  const cmd=inp.value.trim();if(!cmd)return;
  inp.value='';termLine('> '+cmd,'cmd');
  try{
    const r=await fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
    const d=await r.json();
    if(d.ok){d.result.split('\n').forEach(l=>{
      if(l==='__CLEAR_LOGS__'){clearTerm();return;}
      termLine(l,l.includes('✓')?'ok':l.includes('✗')?'err':'');
    });}
    else{termLine('Błąd: '+d.error,'err');}
  }catch{termLine('Błąd połączenia','err');}
}
function termLine(txt,cls){const out=document.getElementById('term-out');const d=document.createElement('div');d.className='tline'+(cls?' '+cls:'');d.textContent=txt;out.appendChild(d);out.scrollTop=out.scrollHeight;}
function clearTerm(){document.getElementById('term-out').innerHTML='';}
function toggleTerm(){
  const panel=document.getElementById('term-panel');
  const overlay=document.getElementById('term-overlay');
  const btn=document.getElementById('term-fab-btn');
  const isOpen=panel.classList.toggle('open');
  if(isOpen){panel.style.display='flex';}
  overlay.classList.toggle('open',isOpen);
  if(btn)btn.classList.toggle('open',isOpen);
  const hBtn=document.getElementById('term-header-btn');
  if(hBtn)hBtn.classList.toggle('open',isOpen);
  if(isOpen)setTimeout(()=>document.getElementById('term-input').focus(),200);
  else setTimeout(()=>{if(!panel.classList.contains('open'))panel.style.display='none';},220);
}
document.addEventListener('DOMContentLoaded',()=>{
  const ti=document.getElementById('term-input');
  const termHist=[];let termHistIdx=-1;
  if(ti)ti.addEventListener('keydown',e=>{
    if(e.key==='Enter'){if(ti.value.trim())termHist.unshift(ti.value.trim());termHistIdx=-1;sendTermCmd();}
    else if(e.key==='ArrowUp'){e.preventDefault();if(termHistIdx<termHist.length-1){termHistIdx++;ti.value=termHist[termHistIdx];}}
    else if(e.key==='ArrowDown'){e.preventDefault();if(termHistIdx>0){termHistIdx--;ti.value=termHist[termHistIdx];}else{termHistIdx=-1;ti.value='';}}
  });
});

// ── Lazy loading miniaturek ──────────────────────────
const lazyObs=new IntersectionObserver((entries)=>{
  entries.forEach(entry=>{
    if(entry.isIntersecting){
      const img=entry.target;
      img.src=img.dataset.src;
      img.onload=()=>{
        img.classList.add('loaded');
        img.style.display='';
        // okładka audio — pokaż cover, ukryj ikonę
        const wrap=img.closest('.thumb-audio');
        if(wrap)wrap.classList.add('has-cover');
      };
      img.onerror=()=>{img.style.display='none';};
      lazyObs.unobserve(img);
    }
  });
},{rootMargin:'100px'});
document.querySelectorAll('img.lazy').forEach(img=>lazyObs.observe(img));

// ── HAMBURGER MENU ──
(function(){
  const menu=document.getElementById('mob-menu');
  const btn=document.getElementById('ham-btn');
  const overlay=document.getElementById('mob-overlay');
  if(!menu||!btn)return;

  function openMenu(){
    menu.style.visibility='visible';
    menu.style.pointerEvents='all';
    menu.classList.add('open');
    btn.classList.add('open');
    document.body.style.overflow='hidden';
  }
  window.closeMobMenu=function(){
    menu.classList.remove('open');
    btn.classList.remove('open');
    document.body.style.overflow='';
    const panel=document.querySelector('.mob-menu-panel');
    function onEnd(){
      panel.removeEventListener('transitionend',onEnd);
      menu.style.visibility='hidden';
      menu.style.pointerEvents='none';
    }
    panel.addEventListener('transitionend',onEnd);
  };
  window.toggleMobMenu=function(){
    menu.classList.contains('open')?window.closeMobMenu():openMenu();
  };

  // Obsługa przycisku hamburgera — touch + click
  var _hamTouched=false;
  btn.addEventListener('touchend',function(e){
    e.preventDefault();
    _hamTouched=true;
    window.toggleMobMenu();
    setTimeout(()=>{_hamTouched=false;},400);
  },{passive:false});
  btn.addEventListener('click',function(){
    if(!_hamTouched)window.toggleMobMenu();
  });

  // Zamknięcie przez overlay
  if(overlay){
    var _ovTouched=false;
    overlay.addEventListener('touchend',function(e){
      e.preventDefault();
      _ovTouched=true;
      window.closeMobMenu();
      setTimeout(()=>{_ovTouched=false;},400);
    },{passive:false});
    overlay.addEventListener('click',function(){
      if(!_ovTouched)window.closeMobMenu();
    });
  }

  // Zamknij przy obróceniu/powiększeniu do desktop
  window.addEventListener('resize',()=>{if(window.innerWidth>600)window.closeMobMenu();});

  // Obsługa akcji w menu przez event delegation (działa na iOS)
  const panel=document.querySelector('.mob-menu-panel');
  if(panel){
    function handleMobAction(target){
      const btn=target.closest('[data-mob-action]');
      if(!btn)return;
      const action=btn.dataset.mobAction;
      window.closeMobMenu();
      setTimeout(()=>{
        if(action==='newFolder')openModal();
        else if(action==='upload')document.getElementById('fi').click();
      },50);
    }
    var _panTouched=false;
    panel.addEventListener('touchend',function(e){
      const t=e.target.closest('[data-mob-action]');
      if(!t)return;
      e.preventDefault();
      _panTouched=true;
      handleMobAction(t);
      setTimeout(()=>{_panTouched=false;},400);
    },{passive:false});
    panel.addEventListener('click',function(e){
      if(!_panTouched)handleMobAction(e.target);
    });
  }
})();
%%STATS_JS%%
async function mobRestart(){
  const btn=document.getElementById('mob-restart-btn');
  if(!btn)return;
  if(!confirm('Zrestartować serwer?'))return;
  btn.disabled=true;btn.style.opacity='0.5';
  try{await fetch('/restart',{method:'POST'});}catch(e){}
  btn.textContent='Restartuję... odśwież za chwilę';
  setTimeout(()=>location.reload(),4000);
}
</script>
</body>
</html>"""



def build_viewer(fname, fsize, fenc, vtype, text_content, parent_enc, fraw=None):
    if fraw is None:
        fraw = fenc
    if vtype == "image":
        inner = f'''<div class="vimg-wrap"><img src="/file?path={fenc}" alt="{fname}" id="vimg"></div>
        <div class="vimg-controls">
          <button onclick="zoom(-0.2)">&#x2212;</button>
          <span id="zpct">100%</span>
          <button onclick="zoom(0.2)">&#x2B;</button>
          <button onclick="resetZoom()">Reset</button>
        </div>'''
    elif vtype == "svg":
        inner = f'''<div class="vimg-wrap"><img src="/file?path={fenc}" alt="{fname}" id="vimg" style="max-width:90%;max-height:75vh;object-fit:contain"></div>'''
    elif vtype == "video":
        inner = f'''<div class="vmedia-wrap">
          <video id="vvid" controls preload="metadata" style="max-width:100%;max-height:75vh;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.6)">
            <source src="/file?path={fenc}">
            Twoja przeglądarka nie obsługuje video.
          </video>
        </div>'''
    elif vtype == "audio":
        inner = f'''<div class="vaudio-wrap">
          <div class="vaudio-card">
            <div class="vaudio-art">
              <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" class="vaudio-vinyl">
                <circle cx="40" cy="40" r="38" fill="#1a1f2e" stroke="#2d3a52" stroke-width="1.5"/>
                <circle cx="40" cy="40" r="28" fill="#111827" stroke="#2d3a52" stroke-width="1"/>
                <circle cx="40" cy="40" r="18" fill="#0d1117" stroke="#2d3a52" stroke-width="1"/>
                <circle cx="40" cy="40" r="4" fill="#818cf8"/>
              </svg>
              <img src="/thumb?path={fenc}" id="vaudio-cover-img" alt="cover" class="vaudio-cover-img">
              <div class="vaudio-note" id="vaudio-note-ico">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="32" height="32"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
              </div>
            </div>
            <div class="vaudio-title">{fname}</div>
            <audio id="ap" preload="metadata"><source src="/file?path={fenc}"></audio>
            <div class="vaudio-progress-wrap" id="prog-wrap">
              <div class="vaudio-progress-bar" id="prog-bar">
                <div class="vaudio-progress-fill" id="prog-fill"></div>
                <div class="vaudio-progress-thumb" id="prog-thumb"></div>
              </div>
            </div>
            <div class="vaudio-times">
              <span id="ap-cur">0:00</span>
              <span id="ap-dur">0:00</span>
            </div>
            <div class="vaudio-controls">

              <button type="button" class="vaudio-btn vaudio-btn-play" id="ap-play" onclick="apToggle()">
                <svg id="ap-play-ico" viewBox="0 0 24 24" fill="currentColor" width="28" height="28"><polygon points="5,3 19,12 5,21"/></svg>
              </button>

            </div>
            <div class="vaudio-vol-row">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/></svg>
              <input type="range" id="ap-vol" min="0" max="1" step="0.01" value="1" class="vaudio-vol">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
            </div>
          </div>
        </div>'''
    elif vtype == "pdf":
        inner = f'''<div class="vpdf-wrap"><iframe src="/file?path={fenc}" width="100%" height="100%" style="border:none;border-radius:8px"></iframe></div>'''
    elif vtype == "text":
        inner = f'''<div class="vtext-wrap"><pre id="vtext">{text_content}</pre></div>'''
    elif vtype == "archive":
        inner = f'''<div class="varchive-wrap">
          <div class="varchive-toolbar">
            <div class="varchive-info" id="arc-info">Ładowanie...</div>
            <input class="arc-search" id="arc-search" placeholder="Szukaj w archiwum..." oninput="arcFilter(this.value)">
          </div>
          <div class="varchive-list" id="arc-list">
            <div class="arc-loading">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
              Wczytywanie zawartości...
            </div>
          </div>
        </div>
        <script>
        let _arcEntries=[];
        async function loadArchive(){{
          const r=await fetch('/zip-list?path={fenc}');
          const d=await r.json();
          if(!d.ok){{document.getElementById('arc-list').innerHTML='<div class="arc-err">'+d.error+'</div>';return;}}
          _arcEntries=d.entries;
          document.getElementById('arc-info').textContent=d.entries.length+' plików · '+d.total_size;
          renderEntries(d.entries);
        }}
        function renderEntries(entries){{
          const list=document.getElementById('arc-list');
          if(!entries.length){{list.innerHTML='<div class="arc-empty">Brak wyników</div>';return;}}
          list.innerHTML=entries.map(e=>`
            <div class="arc-row ${{e.is_dir?'arc-dir':''}}">
              <div class="arc-icon">${{e.is_dir?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" fill="rgba(227,179,65,.15)" stroke="#e3b341"/></svg>':'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z" fill="rgba(129,140,248,.12)" stroke="#818cf8"/><polyline points="13 2 13 9 20 9" stroke="#818cf8"/></svg>'}}</div>
              <div class="arc-name" title="${{e.name}}">${{e.name}}</div>
              <div class="arc-size">${{e.size}}</div>
              ${{!e.is_dir?`<a class="arc-dl" href="/zip-extract?path={fenc}&entry=${{encodeURIComponent(e.full)}}" download="${{e.name}}">&#x2193;</a>`:'<div></div>'}}
            </div>`).join('');
        }}
        function arcFilter(q){{
          if(!q)return renderEntries(_arcEntries);
          const lq=q.toLowerCase();
          renderEntries(_arcEntries.filter(e=>e.full.toLowerCase().includes(lq)));
        }}
        loadArchive();
        </script>'''
    else:
        inner = '<div class="vunsupported">Ten typ pliku nie może być podglądany.</div>'

    return f'''<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>{fname}</title>
<link rel="icon" type="image/svg+xml" href="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0a0c14;--sur:#111827;--brd:#1e2535;--txt:#e6edf3;--muted:#7d8590;--acc:#818cf8;--r:10px}}
body{{
  font-family:"Inter",system-ui,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;flex-direction:column;
  background-image:
    radial-gradient(ellipse 160% 120% at 50% -10%, rgba(79,70,229,.55)  0%, rgba(109,40,217,.30) 38%, transparent 65%),
    radial-gradient(ellipse 60%  50% at 90% 100%,  rgba(67,56,202,.28)  0%, transparent 55%),
    radial-gradient(ellipse 45%  40% at 0%   70%,  rgba(124,58,237,.20) 0%, transparent 50%);
}}
.topbar{{background:rgba(10,12,20,.90);backdrop-filter:blur(12px);border-bottom:1px solid var(--brd);padding:0 20px;height:52px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:50;flex-shrink:0}}
.back{{display:flex;align-items:center;gap:6px;color:var(--muted);text-decoration:none;font-size:13px;font-weight:500;padding:5px 10px;border-radius:7px;border:1px solid transparent;transition:all .15s;white-space:nowrap}}
.back:hover{{color:var(--txt);border-color:var(--brd);background:var(--sur)}}
.topbar-name{{font-size:14px;font-weight:600;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}}
.topbar-meta{{font-size:12px;color:var(--muted);white-space:nowrap}}
.dl-btn{{display:flex;align-items:center;gap:6px;color:#e0e7ff;background:#4f46e5;border:none;border-radius:7px;padding:6px 12px;font-family:inherit;font-size:13px;font-weight:500;cursor:pointer;text-decoration:none;white-space:nowrap;transition:opacity .15s}}
.dl-btn:hover{{opacity:.85}}
.viewer{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.vimg-wrap{{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:24px;cursor:grab}}
.vimg-wrap:active{{cursor:grabbing}}
.vimg-wrap img{{max-width:100%;max-height:75vh;object-fit:contain;transition:transform .2s;border-radius:6px;user-select:none}}
.vimg-controls{{display:flex;align-items:center;justify-content:center;gap:8px;padding:12px 20px;border-top:1px solid var(--brd);background:var(--sur);flex-shrink:0}}
.vimg-controls button{{background:var(--bg);border:1px solid var(--brd);color:var(--txt);padding:5px 14px;border-radius:6px;cursor:pointer;font-size:16px;font-family:inherit;transition:background .15s}}
.vimg-controls button:hover{{background:#1e2535}}
.vimg-controls span{{font-size:13px;color:var(--muted);min-width:44px;text-align:center}}
.vmedia-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:24px}}
.vaudio-wrap{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:24px;padding:40px 20px}}
.vaudio-card{{background:rgba(17,24,39,.85);border:1px solid #2d3a52;border-radius:24px;padding:36px 32px;width:100%;max-width:360px;display:flex;flex-direction:column;align-items:center;gap:20px;box-shadow:0 24px 64px rgba(0,0,0,.6),0 0 0 1px rgba(129,140,248,.08);backdrop-filter:blur(16px)}}
.vaudio-art{{position:relative;width:160px;height:160px;display:flex;align-items:center;justify-content:center;margin-bottom:4px}}
.vaudio-vinyl{{width:160px;height:160px;animation:spin 8s linear infinite;animation-play-state:paused;filter:drop-shadow(0 8px 24px rgba(79,70,229,.4))}}
.vaudio-vinyl.playing{{animation-play-state:running}}
@keyframes spin{{from{{transform:rotate(0deg)}}to{{transform:rotate(360deg)}}}}
.vaudio-note{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--acc);opacity:.7;pointer-events:none}}
.vaudio-cover-img{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;border-radius:50%;display:none;animation:spin 8s linear infinite;animation-play-state:paused;box-shadow:0 8px 32px rgba(79,70,229,.5)}}
.vaudio-cover-img.loaded{{display:block}}
.vaudio-cover-img.playing{{animation-play-state:running}}
.vaudio-title{{font-size:15px;font-weight:600;color:var(--txt);text-align:center;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;width:100%}}
.vaudio-progress-wrap{{width:100%;padding:4px 0 0}}
.vaudio-progress-bar{{position:relative;height:4px;border-radius:2px;background:rgba(255,255,255,.1);cursor:pointer;transition:height .15s}}
.vaudio-progress-bar:hover{{height:6px}}
.vaudio-progress-fill{{position:absolute;left:0;top:0;height:100%;border-radius:2px;background:linear-gradient(90deg,#4f46e5,#818cf8);pointer-events:none;transition:width .1s linear}}
.vaudio-progress-thumb{{position:absolute;top:50%;width:14px;height:14px;border-radius:50%;background:#818cf8;transform:translate(-50%,-50%) scale(0);transition:transform .15s;box-shadow:0 0 6px rgba(129,140,248,.6);pointer-events:none}}
.vaudio-progress-bar:hover .vaudio-progress-thumb{{transform:translate(-50%,-50%) scale(1)}}
.vaudio-times{{display:flex;justify-content:space-between;width:100%;font-size:11px;color:var(--muted);padding:2px 0}}
.vaudio-controls{{display:flex;align-items:center;gap:16px;margin:4px 0}}
.vaudio-btn{{background:none;border:none;cursor:pointer;color:var(--muted);transition:color .15s,transform .1s;display:flex;align-items:center;justify-content:center;padding:6px;border-radius:50%}}
.vaudio-btn:hover{{color:var(--txt);transform:scale(1.1)}}
.vaudio-btn-play{{width:56px;height:56px;background:linear-gradient(135deg,#4f46e5,#818cf8);color:#fff !important;border-radius:50%;box-shadow:0 4px 20px rgba(79,70,229,.5);transition:transform .1s,box-shadow .15s}}
.vaudio-btn-play:hover{{transform:scale(1.07)!important;box-shadow:0 6px 28px rgba(79,70,229,.7)}}
.vaudio-vol-row{{display:flex;align-items:center;gap:8px;width:100%;color:var(--muted)}}
.vaudio-vol{{flex:1;-webkit-appearance:none;appearance:none;height:3px;border-radius:2px;background:rgba(255,255,255,.1);outline:none;cursor:pointer}}
.vaudio-vol::-webkit-slider-thumb{{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:#818cf8;cursor:pointer}}
audio{{display:none}}
.vpdf-wrap{{flex:1;padding:0;display:flex}}
.vpdf-wrap iframe{{flex:1}}
.vtext-wrap{{flex:1;overflow:auto;padding:0}}
pre#vtext{{font-family:"JetBrains Mono","Fira Code",monospace;font-size:13px;line-height:1.65;color:#e6edf3;padding:24px 28px;white-space:pre-wrap;word-break:break-word;tab-size:2;min-height:100%}}
.vunsupported{{flex:1;display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:14px}}
.varchive-wrap{{flex:1;display:flex;flex-direction:column;overflow:hidden}}
.varchive-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 20px;border-bottom:1px solid var(--brd);background:var(--sur);flex-shrink:0;flex-wrap:wrap}}
.varchive-info{{font-size:13px;color:var(--muted);font-weight:500}}
.arc-search{{font-family:inherit;font-size:13px;padding:6px 12px;border-radius:8px;border:1px solid var(--brd);background:var(--bg);color:var(--txt);outline:none;width:220px;transition:border-color .15s}}
.arc-search:focus{{border-color:var(--acc)}}
.arc-search::placeholder{{color:var(--muted)}}
.varchive-list{{flex:1;overflow-y:auto;padding:8px 12px;scrollbar-width:none}}
.varchive-list::-webkit-scrollbar{{display:none}}
.arc-row{{display:grid;grid-template-columns:20px 1fr auto 28px;align-items:center;gap:8px;padding:7px 10px;border-radius:8px;transition:background .12s;font-size:13px}}
.arc-row:hover{{background:rgba(129,140,248,.07)}}
.arc-dir .arc-name{{color:#e3b341;font-weight:500}}
.arc-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt)}}
.arc-size{{font-size:11px;color:var(--muted);white-space:nowrap;text-align:right}}
.arc-dl{{color:var(--acc);text-decoration:none;font-size:15px;display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;transition:background .12s;border:1px solid transparent}}
.arc-dl:hover{{background:rgba(129,140,248,.15);border-color:var(--acc)}}
.arc-loading,.arc-err,.arc-empty{{display:flex;align-items:center;justify-content:center;gap:10px;padding:60px 20px;color:var(--muted);font-size:14px}}
.arc-err{{color:#f85149}}
@keyframes spin{{from{{transform:rotate(0deg)}}to{{transform:rotate(360deg)}}}}
@media(max-width:480px){{.topbar-meta{{display:none}}.topbar{{padding:0 12px;gap:8px}}pre#vtext{{padding:16px;font-size:12px}}.arc-search{{width:140px}}}}
</style>
</head>
<body>
<div class="topbar">
  <a class="back" href="/?path={parent_enc}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
    Wróć
  </a>
  <span class="topbar-name">{fname}</span>
  <span class="topbar-meta">{fsize}</span>
  <a class="dl-btn" href="/file?path={fenc}" download="{fname}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
    Pobierz
  </a>
</div>
<div class="viewer">
  {inner}
</div>
<script>
// ── Custom Audio Player ──────────────────────────────
var ap=document.getElementById('ap');
if(ap){{
  var apPlaying=false;
  var apDragging=false;
  function apFmt(s){{s=Math.floor(s||0);return Math.floor(s/60)+':'+(s%60<10?'0':'')+s%60}}
  function apUpdateProg(){{
    if(!ap.duration||apDragging)return;
    var pct=(ap.currentTime/ap.duration)*100;
    document.getElementById('prog-fill').style.width=pct+'%';
    document.getElementById('prog-thumb').style.left=pct+'%';
    document.getElementById('ap-cur').textContent=apFmt(ap.currentTime);
  }}
  window.apToggle=function(){{
    if(ap.paused){{ap.play();apPlaying=true;}}
    else{{ap.pause();apPlaying=false;}}
  }}
  window.apSeek=function(d){{
    if(!ap.duration)return;
    ap.currentTime=Math.max(0,Math.min(ap.duration,ap.currentTime+d));
    apUpdateProg();
  }}
  ap.addEventListener('timeupdate',apUpdateProg);
  ap.addEventListener('loadedmetadata',function(){{document.getElementById('ap-dur').textContent=apFmt(ap.duration);}});
  // obsługa okładki
  var coverImg=document.getElementById('vaudio-cover-img');
  if(coverImg){{
    coverImg.onload=function(){{
      coverImg.classList.add('loaded');
      var vinyl=document.querySelector('.vaudio-vinyl');
      var note=document.getElementById('vaudio-note-ico');
      if(vinyl)vinyl.style.display='none';
      if(note)note.style.display='none';
    }};
    coverImg.onerror=function(){{coverImg.style.display='none';}};
  }}
  ap.addEventListener('play',function(){{
    document.getElementById('ap-play-ico').innerHTML='<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>';
    var v=document.querySelector('.vaudio-vinyl');if(v)v.classList.add('playing');
    var c=document.getElementById('vaudio-cover-img');if(c&&c.classList.contains('loaded'))c.classList.add('playing');
  }});
  ap.addEventListener('pause',function(){{
    document.getElementById('ap-play-ico').innerHTML='<polygon points="5,3 19,12 5,21"/>';
    var v=document.querySelector('.vaudio-vinyl');if(v)v.classList.remove('playing');
    var c=document.getElementById('vaudio-cover-img');if(c)c.classList.remove('playing');
  }});
  ap.addEventListener('ended',function(){{
    document.getElementById('ap-play-ico').innerHTML='<polygon points="5,3 19,12 5,21"/>';
    var v=document.querySelector('.vaudio-vinyl');if(v)v.classList.remove('playing');
    var c=document.getElementById('vaudio-cover-img');if(c)c.classList.remove('playing');
    document.getElementById('prog-fill').style.width='0%';
    document.getElementById('prog-thumb').style.left='0%';
    document.getElementById('ap-cur').textContent='0:00';
  }});
  var vol=document.getElementById('ap-vol');
  if(vol)vol.addEventListener('input',function(){{ap.volume=this.value;}});
  var pb=document.getElementById('prog-bar');
  if(pb){{
    function pbSeek(e){{
      var r=pb.getBoundingClientRect();
      var pct=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
      ap.currentTime=pct*(ap.duration||0);
      document.getElementById('prog-fill').style.width=(pct*100)+'%';
      document.getElementById('prog-thumb').style.left=(pct*100)+'%';
    }}
    pb.addEventListener('mousedown',function(e){{apDragging=true;pbSeek(e);}});
    document.addEventListener('mousemove',function(e){{if(apDragging)pbSeek(e);}});
    document.addEventListener('mouseup',function(){{apDragging=false;}});
    pb.addEventListener('touchstart',function(e){{apDragging=true;pbSeek(e.touches[0]);}},{{passive:true}});
    document.addEventListener('touchmove',function(e){{if(apDragging)pbSeek(e.touches[0]);}},{{passive:true}});
    document.addEventListener('touchend',function(){{apDragging=false;}});
  }}
}}
// ── Image zoom ───────────────────────────────────────
var scale=1;
function zoom(d){{scale=Math.max(0.1,Math.min(8,scale+d));apply()}}
function resetZoom(){{scale=1;apply()}}
function apply(){{
  var img=document.getElementById("vimg");
  var pct=document.getElementById("zpct");
  if(img)img.style.transform="scale("+scale+")";
  if(pct)pct.textContent=Math.round(scale*100)+"%";
}}
var img=document.getElementById("vimg");
if(img){{
  img.parentElement.addEventListener("wheel",function(e){{
    e.preventDefault();
    zoom(e.deltaY<0?0.15:-0.15);
  }},{{passive:false}});
}}
</script>
</body>
</html>'''


def parse_form_body(body):
    data = {}
    for pair in body.decode("utf-8", errors="replace").split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            data[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
    return data


def redirect(handler, location, cookie=None):
    handler.send_response(302)
    handler.send_header("Location", location)
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()


def build_ban_page(username, ban_data):
    reason  = html.escape(ban_data.get("reason", "Brak powodu."))
    expires = ban_data.get("expires")
    human   = html.escape(ban_data.get("human", ""))
    if expires:
        remaining_js = f"var expires={int(expires)};"
        timer_html   = '<div class="countdown" id="cd">Obliczanie...</div>'
        perm_html    = ""
    else:
        remaining_js = "var expires=null;"
        timer_html   = ""
        perm_html    = '<div class="perm">BAN PERMANENTNY</div>'

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zbanowany – SAFE CLOUD</title>
<link rel="icon" type="image/svg+xml" href="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0a0c14;--sur:#111827;--brd:#1e2535;--txt:#e6edf3;--muted:#7d8590;--red:#f85149;--red2:#6e3535}}
body{{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background-image:
    radial-gradient(ellipse 160% 120% at 50% -10%, rgba(180,30,30,.45) 0%, rgba(120,20,20,.25) 38%, transparent 65%),
    radial-gradient(ellipse 60%  50% at 90% 100%, rgba(110,53,53,.25) 0%, transparent 55%),
    radial-gradient(ellipse 45%  40% at 0%  70%,  rgba(130,40,40,.20) 0%, transparent 50%);
}}
.card{{
  background:var(--sur);border:1px solid var(--red2);border-radius:20px;
  padding:48px 40px;width:100%;max-width:480px;text-align:center;
  box-shadow:0 0 60px rgba(248,81,73,.15),0 20px 60px rgba(0,0,0,.5);
}}
.icon{{display:flex;align-items:center;justify-content:center;margin-bottom:20px}}
h1{{font-size:22px;font-weight:700;color:var(--red);margin-bottom:8px;letter-spacing:.04em;font-family:'Audiowide',sans-serif}}
.user{{font-size:13px;color:var(--muted);margin-bottom:28px}}
.user b{{color:var(--txt)}}
.reason-box{{
  background:rgba(248,81,73,.07);border:1px solid var(--red2);
  border-radius:10px;padding:14px 18px;margin-bottom:28px;text-align:left;
}}
.reason-label{{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}}
.reason-text{{font-size:14px;color:var(--txt);line-height:1.5}}
.countdown{{
  font-size:13px;color:var(--muted);
  background:var(--bg);border:1px solid var(--brd);
  border-radius:10px;padding:14px 18px;
}}
.countdown b{{color:var(--txt);font-variant-numeric:tabular-nums}}
.perm{{
  font-size:13px;font-weight:700;color:var(--red);
  background:rgba(248,81,73,.1);border:1px solid var(--red2);
  border-radius:10px;padding:14px 18px;letter-spacing:.08em;
}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">
    <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg" width="80" height="80">
      <defs>
        <radialGradient id="glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#f85149" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="#f85149" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="body" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#3a1a1a"/>
          <stop offset="100%" stop-color="#2a1010"/>
        </linearGradient>
        <linearGradient id="shine" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#f85149" stop-opacity="0.6"/>
          <stop offset="100%" stop-color="#c0392b" stop-opacity="0.2"/>
        </linearGradient>
      </defs>
      <!-- glow -->
      <circle cx="40" cy="48" r="30" fill="url(#glow)"/>
      <!-- shackle (pałąk) -->
      <path d="M27 36V26a13 13 0 0 1 26 0v10" stroke="#f85149" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.85"/>
      <!-- body -->
      <rect x="18" y="36" width="44" height="32" rx="8" fill="url(#body)" stroke="#f85149" stroke-width="1.5" stroke-opacity="0.6"/>
      <!-- shine line top of body -->
      <rect x="18" y="36" width="44" height="6" rx="8" fill="url(#shine)" opacity="0.3"/>
      <!-- keyhole circle -->
      <circle cx="40" cy="52" r="6" fill="none" stroke="#f85149" stroke-width="2" opacity="0.9"/>
      <!-- keyhole pin -->
      <line x1="40" y1="57" x2="40" y2="63" stroke="#f85149" stroke-width="2.5" stroke-linecap="round" opacity="0.9"/>
    </svg>
  </div>
  <h1>Zostałeś zbanowany</h1>
  <p class="user">Konto: <b>{html.escape(username)}</b> &nbsp;·&nbsp; Czas bana: <b>{human if human != "permanentny" else "Permanentny"}</b></p>
  <div class="reason-box">
    <div class="reason-label">Powód</div>
    <div class="reason-text">{reason}</div>
  </div>
  {timer_html}
  {perm_html}
</div>
<script>
{remaining_js}
function fmt(s){{
  if(s<=0)return'Ban wygasł – <b>odśwież stronę</b>';
  var d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60),sec=s%60;
  var parts=[];
  if(d)parts.push('<b>'+d+'</b> d');
  if(h)parts.push('<b>'+h+'</b> h');
  if(m)parts.push('<b>'+m+'</b> min');
  parts.push('<b>'+sec+'</b> s');
  return'Pozostało: '+parts.join(' ');
}}
if(expires){{
  var cd=document.getElementById('cd');
  function tick(){{
    var left=Math.max(0,Math.floor(expires-Date.now()/1000));
    cd.innerHTML=fmt(left);
    if(left>0)setTimeout(tick,1000);
  }}
  tick();
}}
</script>
</body>
</html>"""


class Handler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {datetime.now().strftime('%H:%M:%S')}  {fmt % args}")

    def send_html(self, content, code=200):
        b = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("ngrok-skip-browser-warning", "true")
        # Odśwież cookie sesji przy każdej odpowiedzi HTML
        token = get_token_from_request(self)
        if token and get_session(token):
            self.send_header("Set-Cookie",
                f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}")
        self.end_headers()
        self.wfile.write(b)

    def send_json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def auth_page(self, error="", tab="login"):
        page = (AUTH_HTML
            .replace("%%ERR_DISPLAY%%",  "block" if error else "none")
            .replace("%%ERROR_MSG%%",    html.escape(error))
            .replace("%%TAB_LOGIN%%",    "active" if tab == "login" else "")
            .replace("%%TAB_REG%%",      "active" if tab == "reg" else "")
            .replace("%%SHOW_LOGIN%%",   "block" if tab == "login" else "none")
            .replace("%%SHOW_REG%%",     "block" if tab == "reg" else "none")
            .replace("%%APP_VERSION%%",  (lambda v: f"v{v['version']} {v['stage']}")(load_version()))
        )
        return page

    def refresh_session_cookie(self, token):
        """Odświeża cookie sesji — wysyła Set-Cookie z nowym Max-Age."""
        cookie = f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
        self.send_header("Set-Cookie", cookie)

    def require_auth(self):
        token    = get_token_from_request(self)
        username = get_session(token)
        if not username:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return None
        b = get_ban(username)
        if b:
            self.send_html(build_ban_page(username, b))
            return None
        return username

    def build_main_page(self, username, sub, target, udir, sort_by="name", sort_dir="asc", search=""):
        admin = is_admin(username)
        owner = is_owner(username)
        fc, fb = dir_stats(udir)
        try: ti = len(list(target.iterdir()))
        except: ti = 0

        if admin:
            admin_title        = " – ADMIN"
            admin_header_style = ".admin-header{border-bottom-color:#3730a3!important;}"
            admin_header_attr  = ' class="admin-header"'
            admin_lm           = " lm-admin"
            admin_avatar       = " avatar-admin"
            admin_badge        = '<span class="admin-badge">ADMIN</span>'
            header_title       = "&#x1F6E1; Admin Panel"
        elif owner:
            admin_title        = " – OWNER"
            admin_header_style = ""
            admin_header_attr  = ""
            admin_lm           = ""
            admin_avatar       = " avatar-owner"
            admin_badge        = '<span class="owner-badge">&#x1F451; OWNER</span>'
            header_title       = "SAFE CLOUD"
        else:
            admin_title        = ""
            admin_header_style = ""
            admin_header_attr  = ""
            admin_lm           = ""
            admin_avatar       = ""
            admin_badge        = ""
            header_title       = "SAFE CLOUD"

        # rola niestandardowa (nadpisuje badge jeśli nie admin/owner)
        if not admin and not owner:
            users = load_users()
            r = get_user_role(users, username)
            if r:
                rc = r["color"]
                rn = html.escape(r["name"])
                admin_badge = f'<span class="role-badge" style="color:{rc};border-color:{rc}55;background:{rc}18">{rn}</span>'

        def sort_ico(by):
            if sort_by != by: return ""
            return "↑" if sort_dir == "asc" else "↓"

        page = (MAIN_HTML
            .replace("%%ADMIN_TITLE%%",        admin_title)
            .replace("%%ADMIN_HEADER_STYLE%%", admin_header_style)
            .replace("%%ADMIN_HEADER_ATTR%%",  admin_header_attr)
            .replace("%%ADMIN_LM%%",           admin_lm)
            .replace("%%ADMIN_AVATAR%%",       admin_avatar)
            .replace("%%ADMIN_BADGE%%",        admin_badge)
            .replace("%%HEADER_TITLE%%",       header_title)
            .replace("%%FILE_COUNT%%",         str(fc))
            .replace("%%TOTAL_SIZE%%",         human_size(fb))
            .replace("%%USERNAME%%",           html.escape(username))
            .replace("%%USER_INITIAL%%",       html.escape(username[0].upper()))
            .replace("%%BREADCRUMB%%",         breadcrumb_html(sub, username))
            .replace("%%TOTAL_ITEMS%%",        str(ti))
            .replace("%%FILE_CARDS%%",         build_cards(target, "/" + sub, sort_by, sort_dir, search))
            .replace("%%CURRENT_PATH%%",       "/" + sub)
            .replace("%%APP_VERSION%%",        (lambda v: f"v{v['version']} {v['stage']}")(load_version()))
            .replace("%%TERMINAL_DISPLAY%%",   "%%TERMINAL_DISPLAY%%")  # unused, panel hidden via CSS
            .replace("%%TERMINAL_BTN%%",       '<button class="term-header-btn" id="term-header-btn" onclick="toggleTerm()" title="Terminal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>Terminal</button>' if (admin or owner) else "")
            .replace("%%MOB_TERMINAL_ITEM%%",  '<div class="mob-menu-sep"></div><button class="mob-menu-item" onclick="closeMobMenu();toggleTerm()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>Terminal admina</button>' if (admin or owner) else "")
            .replace("%%MOB_RESTART_BTN%%",    '''<button class="mob-menu-item red" id="mob-restart-btn" onclick="mobRestart()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Restartuj serwer
      </button>''' if (admin or owner) else "")
            .replace("%%MOB_STATS_BLOCK%%",    '''<div class="mob-menu-sep"></div>
      <div class="mob-stats-block">
        <div class="msb-title">Serwer</div>
        <div class="mob-stats-grid">
          <div class="msb-row"><span class="msb-lbl">RAM</span><span class="msb-val" id="msb-ram">—</span></div>
          <div class="msb-row"><span class="msb-lbl">CPU</span><span class="msb-val" id="msb-cpu">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Wątki</span><span class="msb-val" id="msb-thr">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Połączenia</span><span class="msb-val" id="msb-con">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Ping</span><span class="msb-val" id="msb-ping">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Cache</span><span class="msb-val" id="msb-cache">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Dysk R</span><span class="msb-val" id="msb-dr">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Dysk W</span><span class="msb-val" id="msb-dw">—</span></div>
        </div>
      </div>''' if (admin or owner) else "")
            .replace("%%STATS_JS%%",           '''(function(){
  async function refreshStats(){
    try{
      const r=await fetch('/stats');
      if(!r.ok)return;
      const d=await r.json();
      if(!d.ok)return;
      function sv(id,val,warn,over){
        const el=document.getElementById(id);
        if(!el)return;
        el.textContent=val;
        el.className=el.className.replace(/ ?(warn|over)/g,'')+(over?' over':warn?' warn':'');
      }
      sv('sb-ram',d.ram_rss,d.ram_warn,d.ram_over);
      sv('msb-ram',d.ram_rss,d.ram_warn,d.ram_over);
      const dot=document.getElementById('sb-dot');
      if(dot)dot.className='sbar-dot'+(d.ram_over?' over':d.ram_warn?' warn':'');
      sv('sb-cpu',d.cpu+'%',d.cpu>60,d.cpu>80);
      sv('msb-cpu',d.cpu+'%',d.cpu>60,d.cpu>80);
      ['thr','con','cache'].forEach(k=>{
        const el=document.getElementById('sb-'+k);if(el)el.textContent=d[k==='thr'?'threads':k==='con'?'conns':'cache'];
        const mel=document.getElementById('msb-'+k);if(mel)mel.textContent=d[k==='thr'?'threads':k==='con'?'conns':'cache'];
      });
      ['dr','dw'].forEach(k=>{
        const v=d['disk_'+k.slice(1)]||'—';
        const el=document.getElementById('sb-'+k);if(el)el.textContent=v;
        const mel=document.getElementById('msb-'+k);if(mel)mel.textContent=v;
      });
      // ping
      const t0=performance.now();
      fetch('/stats').then(()=>{
        const ping=Math.round(performance.now()-t0);
        const mp=document.getElementById('msb-ping');
        if(mp){mp.textContent=ping+'ms';mp.className='msb-val'+(ping>200?' over':ping>80?' warn':'');}
      }).catch(()=>{});
    }catch(e){}
  }
  refreshStats();
  setInterval(refreshStats,30000);
})();''' if (admin or owner) else "")
            .replace("%%SORT_BY%%",            sort_by)
            .replace("%%SORT_DIR%%",           sort_dir)
            .replace("%%SEARCH_VAL%%",         html.escape(search))
            .replace("%%SORT_NAME_ACTIVE%%",   "active" if sort_by == "name" else "")
            .replace("%%SORT_DATE_ACTIVE%%",   "active" if sort_by == "date" else "")
            .replace("%%SORT_SIZE_ACTIVE%%",   "active" if sort_by == "size" else "")
            .replace("%%SORT_NAME_ICO%%",      sort_ico("name"))
            .replace("%%SORT_DATE_ICO%%",      sort_ico("date"))
            .replace("%%SORT_SIZE_ICO%%",      sort_ico("size"))
        )
        return page

    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(p.query)

            if p.path == "/login":
                self.send_html(self.auth_page())
                return
            if p.path == "/register":
                self.send_html(self.auth_page(tab="reg"))
                return

            # ── Publiczny link do pobrania pliku ─────────
            if p.path.startswith("/s/"):
                token = p.path[3:]
                share = get_share(token)
                if not share:
                    self.send_html("<html><body style='font-family:sans-serif;background:#0a0c14;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>❌ Link wygasł lub nie istnieje</h2><p style='color:#7d8590'>Ten link został już użyty lub minął jego termin ważności.</p></div></body></html>", 410)
                    return
                owner_dir = user_storage(share["owner"])
                fpath = safe_path(owner_dir, share["path"])
                if not fpath or not fpath.is_file():
                    self.send_html("<html><body style='font-family:sans-serif;background:#0a0c14;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>❌ Plik nie istnieje</h2><p style='color:#7d8590'>Plik mógł zostać usunięty.</p></div></body></html>", 404)
                    return
                # zarejestruj pobranie i usuń token (jednorazowy)
                delete_share(token)
                print(f"[SHARE] Pobrano: {share['name']} (właściciel: {share['owner']}, IP: {self.client_address[0]})")
                mime, _ = mimetypes.guess_type(str(fpath))
                mime = mime or "application/octet-stream"
                size = fpath.stat().st_size
                fname_enc = urllib.parse.quote(share["name"])
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f'attachment; filename="{share["name"]}"; filename*=UTF-8\'\'{fname_enc}')
                self.send_header("ngrok-skip-browser-warning", "true")
                self.end_headers()
                with open(fpath, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
                return

            username = self.require_auth()
            if username is None:
                return

            udir = user_storage(username)

            if p.path == "/stats":
                if not (is_admin(username) or is_owner(username)):
                    self.send_response(403); self.end_headers(); return
                data = json.dumps(get_stats()).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if p.path in ("/", ""):
                sub    = q.get("path", [""])[0].strip("/")
                sort_by  = q.get("sort", ["name"])[0]
                sort_dir = q.get("dir",  ["asc"])[0]
                search   = q.get("q",    [""])[0].strip()
                if sort_by  not in ("name","size","date"): sort_by  = "name"
                if sort_dir not in ("asc","desc"):         sort_dir = "asc"
                target = safe_path(udir, sub)
                if not target or not target.is_dir():
                    self.send_response(302)
                    self.send_header("Location", "/?path=")
                    self.end_headers()
                    return
                self.send_html(self.build_main_page(username, sub, target, udir, sort_by, sort_dir, search))

            elif p.path == "/file":
                sub    = q.get("path", [""])[0].strip("/")
                target = safe_path(udir, sub)
                if not target or not target.is_file():
                    self.send_response(404); self.end_headers(); return
                mime, _ = mimetypes.guess_type(str(target))
                mime = mime or "application/octet-stream"
                size = target.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
                self.end_headers()
                with open(target, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)

            elif p.path == "/thumb":
                sub    = q.get("path", [""])[0].strip("/")
                target = safe_path(udir, sub)
                if not target or not target.is_file():
                    self.send_response(404); self.end_headers(); return
                data = get_thumbnail(target)
                if not data:
                    # fallback — wyślij oryginał
                    mime, _ = mimetypes.guess_type(str(target))
                    mime = mime or "application/octet-stream"
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(target.stat().st_size))
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    with open(target, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)

            elif p.path == "/console":
                if not (is_admin(username) or is_owner(username)):
                    self.send_response(403); self.end_headers(); return
                page = (CONSOLE_HTML
                    .replace("PORT_MAIN", str(PORT))
                    .replace("PORT_WS",   str(CONSOLE_PORT))
                )
                self.send_html(page)

            elif p.path == "/view":
                sub    = q.get("path", [""])[0].strip("/")
                target = safe_path(udir, sub)
                if not target or not target.is_file():
                    self.send_response(404); self.end_headers(); return
                vt         = viewer_type(target.name)
                fenc       = html.escape(urllib.parse.quote("/" + sub))
                fname      = html.escape(target.name)
                fsize      = human_size(target.stat().st_size)
                parts      = sub.rsplit("/", 1)
                parent     = parts[0] if len(parts) > 1 else ""
                parent_enc = html.escape(urllib.parse.quote("/" + parent))
                if vt == "text":
                    try:
                        raw = target.read_text(encoding="utf-8", errors="replace")
                        text_content = html.escape(raw)
                    except:
                        text_content = "(nie można odczytać pliku)"
                else:
                    text_content = ""
                self.send_html(build_viewer(fname, fsize, fenc, vt, text_content, parent_enc, "/" + sub))



            elif p.path == "/zip-list":
                import zipfile, tarfile as _tarfile
                fpath_s = q.get("path", [""])[0]
                fpath = safe_path(udir, urllib.parse.unquote(fpath_s).strip("/"))
                if not fpath or not fpath.exists():
                    return self.send_json({"ok": False, "error": "Plik nie istnieje"})
                ext = fpath.suffix.lower()
                entries = []
                total_bytes = 0
                try:
                    if ext == ".zip":
                        with zipfile.ZipFile(fpath) as zf:
                            for info in zf.infolist():
                                is_dir = info.filename.endswith("/")
                                entries.append({
                                    "full": info.filename,
                                    "name": Path(info.filename).name or info.filename.rstrip("/").split("/")[-1],
                                    "size": human_size(info.file_size) if not is_dir else "",
                                    "is_dir": is_dir
                                })
                                total_bytes += info.file_size
                    elif ext in {".tar", ".gz", ".bz2", ".xz"} or fpath.name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
                        with _tarfile.open(fpath) as tf:
                            for member in tf.getmembers():
                                entries.append({
                                    "full": member.name,
                                    "name": Path(member.name).name or member.name,
                                    "size": human_size(member.size) if not member.isdir() else "",
                                    "is_dir": member.isdir()
                                })
                                total_bytes += member.size
                    else:
                        return self.send_json({"ok": False, "error": "Nieobsługiwany format archiwum"})
                except Exception as ex:
                    return self.send_json({"ok": False, "error": str(ex)})
                self.send_json({"ok": True, "entries": entries, "total_size": human_size(total_bytes)})

            elif p.path == "/zip-extract":
                import zipfile, tarfile as _tarfile
                fpath_s = q.get("path", [""])[0]
                entry_name = q.get("entry", [""])[0]
                fpath = safe_path(udir, urllib.parse.unquote(fpath_s).strip("/"))
                if not fpath or not fpath.exists() or not entry_name:
                    self.send_response(400); self.end_headers(); return
                ext = fpath.suffix.lower()
                data = None
                fname_dl = Path(entry_name).name or "plik"
                try:
                    if ext == ".zip":
                        with zipfile.ZipFile(fpath) as zf:
                            data = zf.read(entry_name)
                    elif ext in {".tar", ".gz", ".bz2", ".xz"} or fpath.name.endswith((".tar.gz", ".tar.bz2")):
                        with _tarfile.open(fpath) as tf:
                            member = tf.getmember(entry_name)
                            f = tf.extractfile(member)
                            data = f.read() if f else b""
                except Exception:
                    self.send_response(400); self.end_headers(); return
                mt = mimetypes.guess_type(fname_dl)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mt)
                self.send_header("Content-Disposition", f'attachment; filename="{fname_dl}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            else:
                self.send_response(404); self.end_headers()

        except Exception as ex:
            print(f"  [ERR GET] {ex}")
            try: self.send_response(500); self.end_headers()
            except: pass

    def do_POST(self):
        try:
            p = urllib.parse.urlparse(self.path)

            if p.path == "/restart":
                username = self.require_auth()
                if username is None: return
                if not (is_admin(username) or is_owner(username)):
                    self.send_response(403); self.end_headers(); return
                resp = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                handle_command("restart")
                return

            if p.path == "/login":
                client_ip = self.client_address[0]
                if check_login_rate_limit(client_ip):
                    self.send_html(self.auth_page(
                        f"Zbyt wiele prób logowania. Poczekaj chwilę i spróbuj ponownie.", "login"))
                    return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                uname = data.get("username", "").strip()
                pw    = data.get("password", "")
                users = load_users()
                if uname in users and get_user_password(users, uname) == hash_password(pw):
                    ban = get_ban(uname)
                    if ban:
                        reason = ban.get("reason", "Brak powodu.")
                        human  = ban.get("human", "")
                        msg = f"Twoje konto jest zablokowane ({human}). Powód: {reason}"
                        self.send_html(self.auth_page(msg, "login"))
                        return
                    token  = create_session(uname)
                    cookie = f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                    redirect(self, "/", cookie)
                else:
                    record_login_attempt(client_ip)
                    remaining = LOGIN_MAX_ATTEMPTS - len(login_attempts.get(client_ip, []))
                    self.send_html(self.auth_page(
                        f"Nieprawidłowa nazwa użytkownika lub hasło. (Pozostałe próby: {remaining})", "login"))
                return

            if p.path == "/register":
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                uname = data.get("username", "").strip()
                pw    = data.get("password", "")
                pw2   = data.get("password2", "")
                users = load_users()
                if uname.lower() == ADMIN_USER.lower() or uname.lower() == OWNER_USER.lower():
                    self.send_html(self.auth_page("Ta nazwa użytkownika jest zarezerwowana.", "reg")); return
                if not uname or not all(c.isalnum() or c in "_-" for c in uname):
                    self.send_html(self.auth_page("Nieprawidłowa nazwa użytkownika (tylko litery, cyfry, _ i -).", "reg")); return
                if len(uname) > 32:
                    self.send_html(self.auth_page("Nazwa użytkownika może mieć max 32 znaki.", "reg")); return
                if uname in users:
                    self.send_html(self.auth_page("Taka nazwa użytkownika już istnieje.", "reg")); return
                if len(pw) < 4:
                    self.send_html(self.auth_page("Hasło musi mieć co najmniej 4 znaki.", "reg")); return
                if pw != pw2:
                    self.send_html(self.auth_page("Hasła nie są identyczne.", "reg")); return
                users[uname] = {"password": hash_password(pw), "role": None}
                save_users(users)
                user_storage(uname)
                token  = create_session(uname)
                cookie = f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                redirect(self, "/", cookie)
                return

            if p.path == "/logout":
                token = get_token_from_request(self)
                if token and token in sessions:
                    del sessions[token]
                cookie = "session=; Path=/; Max-Age=0"
                redirect(self, "/login", cookie)
                return

            username = self.require_auth()
            if username is None:
                return
            udir = user_storage(username)

            if p.path == "/upload":
                ct = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ct:
                    return self.send_json({"ok": False, "error": "Zly content-type"})
                boundary = None
                for tok in ct.split(";"):
                    tok = tok.strip()
                    if tok.startswith("boundary="):
                        boundary = tok[9:].strip('"\'')
                        break
                if not boundary:
                    return self.send_json({"ok": False, "error": "Brak boundary"})
                length = int(self.headers.get("Content-Length", 0))
                body   = self.rfile.read(length)

                sub_path = ""
                fname    = None
                fdata    = None

                delim = b"--" + boundary.encode()
                raw_parts = body.split(delim)
                for i, part in enumerate(raw_parts[1:]):
                    if part in (b"--", b"--\r\n", b"\r\n--", b""):
                        continue
                    if part.startswith(b"--"):
                        continue
                    if part.startswith(b"\r\n"):
                        part = part[2:]
                    if part.endswith(b"\r\n"):
                        part = part[:-2]
                    sep = part.find(b"\r\n\r\n")
                    if sep == -1:
                        continue
                    headers_raw = part[:sep].decode("utf-8", errors="replace")
                    content     = part[sep + 4:]

                    disp = ""
                    for hline in headers_raw.splitlines():
                        if hline.lower().startswith("content-disposition"):
                            disp = hline
                            break

                    field    = ""
                    filename = ""
                    for tok in disp.split(";"):
                        tok = tok.strip()
                        if tok.lower().startswith("name="):
                            field = tok[5:].strip('"\'')
                        elif tok.lower().startswith("filename="):
                            filename = tok[9:].strip('"\'')

                    if field == "path":
                        sub_path = content.decode("utf-8", errors="replace").strip("/")
                    elif field == "file" and filename:
                        fname = Path(filename).name
                        fdata = content
                if not fname or fdata is None:
                    return self.send_json({"ok": False, "error": "Brak pliku w zadaniu"})
                tdir = safe_path(udir, sub_path)
                if not tdir:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                tdir.mkdir(parents=True, exist_ok=True)
                # jeśli plik już istnieje, dodaj (1), (2) itd.
                stem = Path(fname).stem
                suffix = Path(fname).suffix
                out = tdir / fname
                counter = 1
                while out.exists():
                    out = tdir / f"{stem} ({counter}){suffix}"
                    counter += 1
                out.write_bytes(fdata)
                print(f"[UPLOAD] saved: {out}")
                self.send_json({"ok": True, "name": out.name})
                ct = self.headers.get("Content-Type", "")
                if "multipart/form-data" not in ct:
                    return self.send_json({"ok": False, "error": "Zly content-type"})
                boundary = None
                for tok in ct.split(";"):
                    tok = tok.strip()
                    if tok.startswith("boundary="):
                        boundary = tok[9:].strip('"\'')
                        break
                if not boundary:
                    return self.send_json({"ok": False, "error": "Brak boundary"})
                length = int(self.headers.get("Content-Length", 0))
                body   = self.rfile.read(length)

                sub_path = ""
                fname    = None
                fdata    = None

                delim = b"--" + boundary.encode()
                # dzielimy po delimitach, pomijamy pierwszy pusty i ostatni (--)
                raw_parts = body.split(delim)
                for part in raw_parts[1:]:
                    # każda część zaczyna się od \r\n, kończy \r\n
                    if part in (b"--", b"--\r\n", b"\r\n--", b""):
                        continue
                    if part.startswith(b"--"):
                        continue
                    # odetnij wiodący \r\n
                    if part.startswith(b"\r\n"):
                        part = part[2:]
                    # odetnij końcowy \r\n
                    if part.endswith(b"\r\n"):
                        part = part[:-2]
                    # znajdź koniec nagłówków
                    sep = part.find(b"\r\n\r\n")
                    if sep == -1:
                        continue
                    headers_raw = part[:sep].decode("utf-8", errors="replace")
                    content     = part[sep + 4:]

                    # parsuj Content-Disposition
                    disp = ""
                    for hline in headers_raw.splitlines():
                        if hline.lower().startswith("content-disposition"):
                            disp = hline
                            break

                    field    = ""
                    filename = ""
                    for tok in disp.split(";"):
                        tok = tok.strip()
                        if tok.lower().startswith("name="):
                            field = tok[5:].strip('"\'')
                        elif tok.lower().startswith("filename="):
                            filename = tok[9:].strip('"\'')

                    if field == "path":
                        sub_path = content.decode("utf-8", errors="replace").strip("/")
                    elif field == "file" and filename:
                        fname = Path(filename).name
                        fdata = content

                if not fname or fdata is None:
                    return self.send_json({"ok": False, "error": "Brak pliku w zadaniu"})
                tdir = safe_path(udir, sub_path)
                if not tdir:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                tdir.mkdir(parents=True, exist_ok=True)
                # jeśli plik już istnieje, dodaj (1), (2) itd.
                stem = Path(fname).stem
                suffix = Path(fname).suffix
                out = tdir / fname
                counter = 1
                while out.exists():
                    out = tdir / f"{stem} ({counter}){suffix}"
                    counter += 1
                out.write_bytes(fdata)
                self.send_json({"ok": True, "name": out.name})

            elif p.path == "/delete":
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                sub  = data.get("path", "").strip("/")
                name = Path(data.get("name", "")).name
                t    = safe_path(udir, sub + "/" + name)
                if not t:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                if data.get("isDir"):
                    shutil.rmtree(t)
                else:
                    t.unlink()
                self.send_json({"ok": True})

            elif p.path == "/rename":
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                sub     = data.get("path", "").strip("/")
                old_name = Path(data.get("old", "")).name
                new_name = Path(data.get("new", "")).name
                if not old_name or not new_name:
                    return self.send_json({"ok": False, "error": "Brak nazwy"})
                src = safe_path(udir, sub + "/" + old_name)
                dst = safe_path(udir, sub + "/" + new_name)
                if not src or not dst:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                if not src.exists():
                    return self.send_json({"ok": False, "error": "Plik nie istnieje"})
                if dst.exists():
                    return self.send_json({"ok": False, "error": "Plik o tej nazwie już istnieje"})
                src.rename(dst)
                self.send_json({"ok": True})

            elif p.path == "/move":
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                src_path  = data.get("src", "").strip("/")
                dst_folder = data.get("dst_folder", "").strip("/")
                name = Path(src_path).name
                src = safe_path(udir, src_path)
                dst_dir = safe_path(udir, dst_folder)
                if not src or not dst_dir:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                if not src.exists():
                    return self.send_json({"ok": False, "error": "Źródło nie istnieje"})
                if not dst_dir.is_dir():
                    return self.send_json({"ok": False, "error": "Cel nie jest folderem"})
                dst = dst_dir / name
                if dst.exists():
                    return self.send_json({"ok": False, "error": "Plik o tej nazwie już istnieje w docelowym folderze"})
                shutil.move(str(src), str(dst))
                self.send_json({"ok": True})

            elif p.path == "/zip":
                import zipfile, io as _io
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                sub   = data.get("path", "").strip("/")
                names = data.get("names", [])
                tdir  = safe_path(udir, sub)
                if not tdir:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                buf = _io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for name in names:
                        name = Path(name).name
                        fpath = safe_path(udir, sub + "/" + name)
                        if not fpath or not fpath.exists():
                            continue
                        if fpath.is_dir():
                            for fp in fpath.rglob("*"):
                                if fp.is_file():
                                    zf.write(fp, fp.relative_to(tdir))
                        else:
                            zf.write(fpath, name)
                zdata = buf.getvalue()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="pobrane.zip"')
                self.send_header("Content-Length", str(len(zdata)))
                self.end_headers()
                self.wfile.write(zdata)

            elif p.path == "/mkdir":
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                sub  = data.get("path", "").strip("/")
                name = Path(data.get("name", "")).name
                if not name:
                    return self.send_json({"ok": False, "error": "Brak nazwy"})
                t = safe_path(udir, sub + "/" + name)
                if not t:
                    return self.send_json({"ok": False, "error": "Zla sciezka"})
                t.mkdir(parents=True, exist_ok=False)
                self.send_json({"ok": True})

            elif p.path == "/cmd":
                if not is_admin(username) and not is_owner(username):
                    return self.send_json({"ok": False, "error": "Brak uprawnień."})
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                cmd  = data.get("cmd", "").strip()
                result = handle_command(cmd) or ""
                self.send_json({"ok": True, "result": result})

            elif p.path == "/share/create":
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                sub  = data.get("path", "").strip("/")
                name = Path(data.get("name", "")).name
                ttl  = data.get("ttl_hours", None)
                if ttl is not None:
                    try: ttl = float(ttl)
                    except: ttl = None
                t = safe_path(udir, sub + "/" + name)
                if not t or not t.is_file():
                    return self.send_json({"ok": False, "error": "Plik nie istnieje."})
                rel = (sub + "/" + name).lstrip("/")
                token = create_share(username, rel, name, ttl)
                print(f"[SHARE] Utworzono link: {name} ({username}) TTL={ttl}h token={token[:8]}...")
                self.send_json({"ok": True, "token": token})

            else:
                self.send_response(404); self.end_headers()

        except Exception as ex:
            print(f"  [ERR POST] {ex}")
            try: self.send_json({"ok": False, "error": str(ex)})
            except: pass


# ── KONSOLA PRZEGLADARKOWA (port 8081) ───────────────
import threading, queue, struct

CONSOLE_PORT  = 8081
log_queue     = queue.Queue()
ws_clients    = []
ws_lock       = threading.Lock()
_current_admin_pass = ""   # przechowuje aktualne haslo admina

_orig_print = print
def print(*args, **kwargs):
    _orig_print(*args, **kwargs)
    import io
    buf = io.StringIO()
    _orig_print(*args, **kwargs, file=buf)
    msg = buf.getvalue().rstrip("\n")
    if msg:
        ts = datetime.now().strftime("%H:%M:%S")
        log_queue.put(f"[{ts}] {msg}")

def broadcast_logs():
    while True:
        msg = log_queue.get()
        with ws_lock:
            dead = []
            for client in ws_clients:
                try:
                    ws_send(client, msg)
                except:
                    dead.append(client)
            for d in dead:
                ws_clients.remove(d)

def _fmt_bytes(n):
    for u in ["B","KB","MB","GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"

_ngrok_proc_cache = None
_disk_io_prev = None   # (timestamp, read_bytes, write_bytes)

def get_stats():
    """Zwraca slownik z aktualnymi statystykami procesu."""
    result = {"ok": False}
    try:
        import psutil, os as _os
        proc = psutil.Process(_os.getpid())
        mem = proc.memory_info()
        try:    conns = len(proc.connections())
        except: conns = 0
        try:
            global _disk_io_prev
            dio = proc.io_counters()
            now_io = time.time()
            if _disk_io_prev is not None:
                prev_t, prev_r, prev_w = _disk_io_prev
                dt = now_io - prev_t
                if dt > 0:
                    rate_r = (dio.read_bytes  - prev_r) / dt
                    rate_w = (dio.write_bytes - prev_w) / dt
                    disk_r = _fmt_bytes(rate_r) + "/s" if rate_r > 0 else None
                    disk_w = _fmt_bytes(rate_w) + "/s" if rate_w > 0 else None
                else:
                    disk_r = disk_w = None
            else:
                disk_r = disk_w = None
            _disk_io_prev = (now_io, dio.read_bytes, dio.write_bytes)
        except:
            disk_r = disk_w = None
        now_t = time.time()
        ram_mb = mem.rss / (1024 * 1024)
        # RAM ngrok – zsumuj z RAM serwera (cache procesu)
        ngrok_rss = 0
        try:
            global _ngrok_proc_cache
            proc_ok = False
            if _ngrok_proc_cache:
                try:
                    if _ngrok_proc_cache.is_running():
                        ngrok_rss = _ngrok_proc_cache.memory_info().rss
                        proc_ok = True
                except: _ngrok_proc_cache = None
            if not proc_ok:
                for p in psutil.process_iter(['name', 'memory_info']):
                    if 'ngrok' in p.info['name'].lower():
                        _ngrok_proc_cache = p
                        ngrok_rss = p.info['memory_info'].rss
                        break
        except: pass
        total_rss = mem.rss + ngrok_rss
        total_mb  = total_rss / (1024 * 1024)
        result = {
            "ok":        True,
            "ram_rss":   _fmt_bytes(total_rss),
            "ram_vms":   _fmt_bytes(mem.vms),
            "ram_rss_raw": total_rss,
            "ram_warn":  total_mb >= 250,
            "ram_over":  total_mb >= 300,
            "cpu":       round(proc.cpu_percent(interval=None), 1),
            "threads":   proc.num_threads(),
            "conns":     conns,
            "disk_r":    disk_r,
            "disk_w":    disk_w,
            "cache":     len(thumb_cache),
            "sessions":  sum(1 for s in sessions.values() if s["expires"] > now_t),
        }
    except ImportError:
        result = {"ok": False, "error": "psutil niedostepny"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    return result

RAM_WARN_MB    = 150   # poziom ostrzeżenia
RAM_CLEAN_MB   = 200   # agresywne czyszczenie
RAM_RESTART_MB = 280   # restart serwera

def cleanup_memory(ram_mb, ts):
    """Wielopoziomowe zwalnianie pamięci. Zwraca opis wykonanych akcji."""
    actions = []

    # 1. Zawsze: wyczyść wygasłe sesje
    expired = [t for t, s in list(sessions.items()) if s["expires"] <= time.time()]
    for t in expired:
        sessions.pop(t, None)
    if expired:
        actions.append(f"sesje wygasłe: -{len(expired)}")

    # 2. Zawsze: ogranicz login_attempts
    now = time.time()
    old_ips = [ip for ip, attempts in list(login_attempts.items())
               if not attempts or now - max(attempts) > LOGIN_WINDOW_SEC * 2]
    for ip in old_ips:
        login_attempts.pop(ip, None)
    if old_ips:
        actions.append(f"stare IP: -{len(old_ips)}")

    # 3. Zawsze: ogranicz bans wygasłe
    expired_bans = [u for u in list(bans.keys()) if get_ban(u) is None]
    if expired_bans:
        actions.append(f"bany wygasłe: -{len(expired_bans)}")

    # 4. Przy RAM_CLEAN_MB: wyczyść część cache miniaturek (najstarsze 50%)
    if ram_mb >= RAM_CLEAN_MB and thumb_cache:
        before = len(thumb_cache)
        keys = list(thumb_cache.keys())
        for k in keys[:len(keys)//2]:
            del thumb_cache[k]
        actions.append(f"cache thumb: -{before - len(thumb_cache)}")

    # 5. Przy RAM_RESTART_MB: wyczyść cały cache
    if ram_mb >= RAM_RESTART_MB and thumb_cache:
        before = len(thumb_cache)
        thumb_cache.clear()
        actions.append(f"cache thumb wyczyszczony: -{before}")

    return ", ".join(actions) if actions else "brak akcji"

def ram_limiter():
    """Co 15s sprawdza RAM i wykonuje wielopoziomowe czyszczenie."""
    try:
        import psutil, os as _os
        proc = psutil.Process(_os.getpid())
        last_warn_mb = 0
        while True:
            time.sleep(15)
            try:
                ram_mb = proc.memory_info().rss / (1024 * 1024)
                ts = datetime.now().strftime("%H:%M:%S")

                if ram_mb >= RAM_RESTART_MB:
                    desc = cleanup_memory(ram_mb, ts)
                    log_queue.put(f"[{ts}] [WARN] RAM {ram_mb:.1f} MB >= {RAM_RESTART_MB} MB — {desc} — restartuję serwer...")
                    time.sleep(1)
                    import sys, os as _os2
                    _os2.execv(sys.executable, [sys.executable] + sys.argv)

                elif ram_mb >= RAM_CLEAN_MB:
                    desc = cleanup_memory(ram_mb, ts)
                    log_queue.put(f"[{ts}] [WARN] RAM {ram_mb:.1f} MB >= {RAM_CLEAN_MB} MB — czyszczę: {desc}")
                    last_warn_mb = ram_mb

                elif ram_mb >= RAM_WARN_MB:
                    desc = cleanup_memory(ram_mb, ts)
                    # loguj tylko jeśli wzrósł o >10MB od ostatniego loga
                    if ram_mb > last_warn_mb + 10:
                        log_queue.put(f"[{ts}] [WARN] RAM {ram_mb:.1f} MB — {desc}")
                        last_warn_mb = ram_mb

                else:
                    # normalny poziom — tylko rutynowe czyszczenie co jakiś czas
                    cleanup_memory(ram_mb, ts)
                    last_warn_mb = 0

            except Exception as e:
                ts = datetime.now().strftime("%H:%M:%S")
                log_queue.put(f"[{ts}] [WARN] ram_limiter blad: {e}")
    except ImportError:
        pass

def ws_handshake(handler):
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if not key:
        return False
    import base64, hashlib as hl
    magic  = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = base64.b64encode(hl.sha1((key + magic).encode()).digest()).decode()
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    return True

def ws_send(sock, text):
    payload = text.encode("utf-8")
    n = len(payload)
    if n <= 125:
        header = bytes([0x81, n])
    elif n <= 65535:
        header = struct.pack("!BBH", 0x81, 126, n)
    else:
        header = struct.pack("!BBQ", 0x81, 127, n)
    sock.wfile.write(header + payload)
    sock.wfile.flush()

def ws_recv(sock):
    try:
        raw = sock.rfile.read(2)
        if len(raw) < 2:
            return None
        b1, b2 = raw[0], raw[1]
        masked = b2 & 0x80
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", sock.rfile.read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", sock.rfile.read(8))[0]
        mask = sock.rfile.read(4) if masked else b""
        data = bytearray(sock.rfile.read(length))
        if masked:
            for i in range(len(data)):
                data[i] ^= mask[i % 4]
        return data.decode("utf-8", errors="replace")
    except:
        return None

CONSOLE_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Konsola – SAFE CLOUD</title>
<link rel="icon" type="image/svg+xml" href="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0a0c14;--sur:#111827;--brd:#1e2535;--txt:#e6edf3;--muted:#7d8590;--acc:#818cf8;--green:#3fb950;--yellow:#e3b341;--red:#f85149}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{background:rgba(17,24,39,.95);border-bottom:1px solid var(--brd);padding:0 20px;height:52px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.logo{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px;font-family:'Audiowide',sans-serif;letter-spacing:.04em}
.lm{width:28px;height:28px;border-radius:7px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.hright{display:flex;align-items:center;gap:12px}
.status{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--red);transition:background .3s}
.dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}
.btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 12px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s}
.btn:hover{background:#161d2e;border-color:#2d3a52}
.btn-red{border-color:#6e3535;color:var(--red)}
.btn-red:hover{background:rgba(248,81,73,.1)}
.toolbar{display:flex;align-items:center;gap:8px;padding:8px 16px;background:var(--sur);border-bottom:1px solid var(--brd);flex-shrink:0}
.tl{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-right:4px}
.filter-btn{font-family:inherit;font-size:11px;font-weight:500;padding:3px 10px;border-radius:5px;cursor:pointer;border:1px solid var(--brd);background:transparent;color:var(--muted);transition:all .15s}
.filter-btn.active{background:var(--bg);color:var(--txt);border-color:#2d3a52}
.filter-btn:hover{color:var(--txt)}
#console{flex:1;overflow-y:auto;padding:12px 0;font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--bg)}
.line{padding:1px 16px;display:flex;gap:12px;align-items:flex-start;border-left:2px solid transparent;transition:background .1s}
.line:hover{background:rgba(255,255,255,.03)}
.ts{color:var(--muted);flex-shrink:0;font-size:11px;padding-top:2px}
.msg{flex:1;white-space:pre-wrap;word-break:break-all;color:var(--txt)}
.line.err .msg{color:var(--red)}.line.err{border-left-color:var(--red)}
.line.warn .msg{color:var(--yellow)}.line.warn{border-left-color:var(--yellow)}
.line.ok .msg{color:var(--green)}.line.ok{border-left-color:var(--green)}
.line.info .msg{color:var(--acc)}
.footer{padding:8px 16px;border-top:1px solid var(--brd);font-size:11px;color:var(--muted);background:var(--sur);flex-shrink:0;display:flex;justify-content:space-between}
.cmd-bar{display:flex;align-items:center;gap:8px;padding:8px 16px;background:#0d1117;border-top:1px solid var(--brd);flex-shrink:0}
.cmd-prefix{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--acc);flex-shrink:0}
.cmd-input{flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;background:transparent;border:none;outline:none;color:var(--txt);caret-color:var(--acc)}
.cmd-input::placeholder{color:#3d4a5c}
.cmd-send{font-family:inherit;font-size:12px;font-weight:500;padding:4px 12px;border-radius:6px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s;flex-shrink:0}
.cmd-send:hover{background:#4f46e5;border-color:#4f46e5;color:#e0e7ff}
.stats-bar{display:flex;align-items:center;gap:0;flex:1;justify-content:center}
.stat-group{display:flex;align-items:center;gap:10px;padding:0 24px;border-right:1px solid #2d3a52}
.stat-group:last-child{border-right:none}
.stat{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--muted);white-space:nowrap}
.stat-val{color:var(--txt);font-family:'JetBrains Mono',monospace;font-size:11px}
.stat-inner-sep{color:#3d4a5c;font-size:11px;line-height:1;flex-shrink:0}
.stat-warn{color:var(--yellow)}
.stat-over{color:var(--red)}
</style>
</head>
<body>
<header>
  <div class="logo"><div class="lm"><img src="https://media.lordicon.com/icons/wired/gradient/53-location-pin-on-round-map.svg" width="28" height="28" style="object-fit:contain"></div>Konsola – SAFE CLOUD</div>
  <div class="stats-bar">
    <div class="stat-group">
      <div class="stat">RAM &ndash; <span class="stat-val" id="st-ram">&mdash;</span></div>
    </div>
    <div class="stat-group">
      <div class="stat">CPU &ndash; <span class="stat-val" id="st-cpu">&mdash;</span></div>
      <span class="stat-inner-sep">&middot;</span>
      <div class="stat">Wątki &ndash; <span class="stat-val" id="st-thr">&mdash;</span></div>
      <span class="stat-inner-sep">&middot;</span>
      <div class="stat">Połączenia &ndash; <span class="stat-val" id="st-con">&mdash;</span></div>
    </div>
    <div class="stat-group">
      <div class="stat">Dysk In &ndash; <span class="stat-val" id="st-dr">&mdash;</span></div>
      <span class="stat-inner-sep">&middot;</span>
      <div class="stat">Dysk Out &ndash; <span class="stat-val" id="st-dw">&mdash;</span></div>
    </div>
    <div class="stat-group">
      <div class="stat">Cache &ndash; <span class="stat-val" id="st-cache">&mdash;</span></div>
      <span class="stat-inner-sep">&middot;</span>
      <div class="stat">Sesje &ndash; <span class="stat-val" id="st-ses">&mdash;</span></div>
    </div>
  </div>
  <div class="hright">
    <div class="status"><div class="dot" id="dot"></div><span id="stext">Łączenie...</span></div>
    <button class="btn btn-red" onclick="clearConsole()">Wyczyść</button>
    <a class="btn" href="https://kerrie-nonconspiratorial-cynthia.ngrok-free.dev/">Otwórz SAFE CLOUD ↗</a>
  </div>
</header>
<div class="toolbar">
  <span class="tl">Filtr:</span>
  <button class="filter-btn active" onclick="setFilter('all',this)">Wszystko</button>
  <button class="filter-btn" onclick="setFilter('err',this)">Błędy</button>
  <button class="filter-btn" onclick="setFilter('warn',this)">Ostrzeżenia</button>
  <button class="filter-btn" onclick="setFilter('ok',this)">OK</button>
</div>
<div id="console"></div>
<div class="cmd-bar">
  <span class="cmd-prefix">$</span>
  <input class="cmd-input" id="cmd-input" placeholder="Wpisz komendę... (help aby zobaczyć listę)" autocomplete="off" spellcheck="false">
  <button class="cmd-send" onclick="sendCmd()">Wyślij</button>
</div>
<div class="footer">
  <span id="cnt">0 linii</span>
  <span id="ftime"></span>
</div>
<style>
.line-stack{cursor:pointer;user-select:none;}
.line-stack:hover{background:rgba(255,255,255,.05)!important;}
.stack-badge{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:16px;padding:0 5px;border-radius:99px;background:rgba(129,140,248,.25);color:#a5b4fc;font-size:10px;font-weight:700;margin-left:6px;font-family:'JetBrains Mono',monospace;flex-shrink:0;}
.stack-arrow{font-size:10px;margin-left:4px;color:var(--muted);transition:transform .15s;display:inline-block;}
.stack-arrow.open{transform:rotate(90deg);}
.stack-children{display:none;border-left:2px solid rgba(129,140,248,.2);margin-left:28px;}
.stack-children.open{display:block;}
.stack-children .line{border-left:none;padding-left:8px;}
</style>
<script>
const con=document.getElementById('console');
const LOG_TTL=10*60*1000; // 10 minut w ms
let groups=[],filter='all',ws,reconnectTimer;

function classify(msg){
  const m=msg.toLowerCase();
  if(m.includes('[err')||m.includes('error')||m.includes('traceback')||m.includes('exception')) return 'err';
  if(m.includes('warn')||m.includes('uwaga')) return 'warn';
  if(m.includes('ok')||m.includes('✓')||m.includes('start')||m.includes('uruch')) return 'ok';
  if(m.includes('info')||m.includes('[admin]')||m.includes('[cmd]')) return 'info';
  return '';
}
function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function tsToMs(ts){
  // ts = "HH:MM:SS", zwraca ms od północy
  if(!ts) return Date.now();
  const[h,mi,s]=ts.split(':').map(Number);
  return(h*3600+mi*60+s)*1000;
}

function addLine(raw){
  if(raw.includes('__CLEAR_LOGS__')){groups=[];rebuildDOM();return;}
  const m=raw.replace(/^\\[\\d{2}:\\d{2}:\\d{2}\\]\\s*/,'');
  const ts=raw.match(/^\\[(\\d{2}:\\d{2}:\\d{2})\\]/)?.[1]||'';
  const cls=classify(raw);
  const now=Date.now();

  // stackowanie: szukaj pasującej grupy gdziekolwiek na liście
  const existing=groups.find(g=>g.m===m&&g.cls===cls);
  if(existing){
    existing.count++;
    existing.ts=ts;
    existing.times.push(ts);
    existing.addedAt=now;
    updateGroup(existing);
  } else {
    groups.push({m,ts,cls,count:1,times:[ts],addedAt:now,expanded:false,id:'g'+(Date.now()+Math.random())});
    if(filter==='all'||cls===filter) appendGroupDOM(groups[groups.length-1],true);
  }
  updateFooter();
}

function appendGroupDOM(g,scroll){
  const wrap=document.createElement('div');
  wrap.id=g.id;
  wrap.className='line'+(g.cls?' '+g.cls:'')+(g.count>1?' line-stack':'');
  wrap.innerHTML=buildGroupHTML(g);
  if(g.count>1) wrap.onclick=()=>toggleStack(g.id);
  con.appendChild(wrap);
  if(scroll)con.scrollTop=con.scrollHeight;
}

function buildGroupHTML(g){
  const badge=g.count>1?`<span class="stack-badge">×${g.count}</span><span class="stack-arrow${g.expanded?' open':''}">&#9658;</span>`:'';
  const childrenHTML=g.count>1?`<div class="stack-children${g.expanded?' open':''}" id="${g.id}_ch">${
    g.times.map((t,i)=>`<div class="line ${g.cls}"><span class="ts">${t}</span><span class="msg">${escHtml(g.m)}</span></div>`).join('')
  }</div>`:'';
  return `<span class="ts">${g.ts}</span><span class="msg">${escHtml(g.m)}${badge}</span>${childrenHTML}`;
}

function updateGroup(g){
  if(filter!=='all'&&g.cls!==filter) return;
  const el=document.getElementById(g.id);
  if(!el) return;
  el.className='line'+(g.cls?' '+g.cls:'')+(g.count>1?' line-stack':'');
  el.innerHTML=buildGroupHTML(g);
  if(g.count>1) el.onclick=()=>toggleStack(g.id);
}

function toggleStack(id){
  const g=groups.find(x=>x.id===id);
  if(!g) return;
  g.expanded=!g.expanded;
  const el=document.getElementById(id);
  if(!el) return;
  el.innerHTML=buildGroupHTML(g);
  el.onclick=()=>toggleStack(id);
  if(g.expanded) con.scrollTop=con.scrollHeight;
}

function rebuildDOM(){
  con.innerHTML='';
  const visible=groups.filter(g=>filter==='all'||g.cls===filter);
  visible.forEach(g=>appendGroupDOM(g,false));
  con.scrollTop=con.scrollHeight;
  updateFooter();
}

function updateFooter(){
  const total=groups.reduce((s,g)=>s+g.count,0);
  document.getElementById('cnt').textContent=total+' linii ('+groups.length+' grup)';
  const last=groups[groups.length-1];
  if(last) document.getElementById('ftime').textContent='ostatnia: '+last.ts;
}

function setFilter(f,btn){
  filter=f;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  rebuildDOM();
}
function clearConsole(){groups=[];con.innerHTML='';document.getElementById('cnt').textContent='0 linii';}
function setStatus(on,txt){
  document.getElementById('dot').className='dot'+(on?' on':'');
  document.getElementById('stext').textContent=txt;
}

// Auto-usuwanie logów starszych niż 10 minut
setInterval(()=>{
  const cutoff=Date.now()-LOG_TTL;
  const before=groups.length;
  groups=groups.filter(g=>g.addedAt>=cutoff);
  if(groups.length!==before) rebuildDOM();
},30000); // sprawdzaj co 30s

function connect(){
  ws=new WebSocket('ws://localhost:PORT_WS/ws');
  ws.onopen=()=>{setStatus(true,'Połączono');addLine('['+new Date().toTimeString().slice(0,8)+'] ✓ Połączono z serwerem')};
  ws.onmessage=e=>addLine(e.data);
  ws.onclose=()=>{setStatus(false,'Rozłączono – ponawiam...');reconnectTimer=setTimeout(connect,2500)};
  ws.onerror=()=>{ws.close()};
}
function sendCmd(){
  const inp=document.getElementById('cmd-input');
  const val=inp.value.trim();
  if(!val||!ws||ws.readyState!==1)return;
  ws.send('CMD:'+val);
  inp.value='';
}
document.addEventListener('DOMContentLoaded',()=>{
  const ci=document.getElementById('cmd-input');
  const cmdHist=[];let cmdHistIdx=-1;
  ci.addEventListener('keydown',e=>{
    if(e.key==='Enter'){if(ci.value.trim())cmdHist.unshift(ci.value.trim());cmdHistIdx=-1;sendCmd();}
    else if(e.key==='ArrowUp'){e.preventDefault();if(cmdHistIdx<cmdHist.length-1){cmdHistIdx++;ci.value=cmdHist[cmdHistIdx];}}
    else if(e.key==='ArrowDown'){e.preventDefault();if(cmdHistIdx>0){cmdHistIdx--;ci.value=cmdHist[cmdHistIdx];}else{cmdHistIdx=-1;ci.value='';}}
  });
});
async function fetchStats(){
  try{
    const r=await fetch('http://localhost:PORT_WS/stats');
    const d=await r.json();
    if(d.ok){
      const ramEl=document.getElementById('st-ram');
      ramEl.textContent=d.ram_rss;
      ramEl.className='stat-val'+(d.ram_over?' stat-over':d.ram_warn?' stat-warn':'');
      const cpuEl=document.getElementById('st-cpu');
      cpuEl.textContent=d.cpu+'%';
      cpuEl.className='stat-val'+(d.cpu>80?' stat-warn':'');
      document.getElementById('st-thr').textContent=d.threads;
      document.getElementById('st-con').textContent=d.conns;
      document.getElementById('st-dr').textContent=d.disk_r||'—';
      document.getElementById('st-dw').textContent=d.disk_w||'—';
      document.getElementById('st-cache').textContent=d.cache;
      document.getElementById('st-ses').textContent=d.sessions;
    }
  }catch(e){}
}
fetchStats();
setInterval(fetchStats,3000);
connect();
</script>
</body>
</html>"""

class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _check_console_auth(self):
        """Zwraca True jeśli request pochodzi od admina/ownera, False w przeciwnym razie."""
        cookie = self.headers.get("Cookie", "")
        token = None
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("session="):
                token = part[8:]
                break
        username = get_session(token) if token else None
        return username and (is_admin(username) or is_owner(username))

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/ws" and self.headers.get("Upgrade","").lower() == "websocket":
            if not self._check_console_auth():
                try:
                    self.send_response(403)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except: pass
                return
            if not ws_handshake(self):
                return
            with ws_lock:
                ws_clients.append(self)
            ws_send(self, f"[{datetime.now().strftime('%H:%M:%S')}] \u2713 Konsola podlaczona. Czekam na logi...")
            ws_send(self, f"[{datetime.now().strftime('%H:%M:%S')}] [CMD] Wpisz 'help' aby zobaczyc dostepne komendy.")
            while True:
                data = ws_recv(self)
                if data is None:
                    break
                data = data.strip()
                if data.startswith("CMD:"):
                    cmd = data[4:].strip()
                    ts  = datetime.now().strftime("%H:%M:%S")
                    ws_send(self, f"[{ts}] > {cmd}")
                    result = handle_command(cmd)
                    if result == "__CLEAR_LOGS__":
                        ws_send(self, f"[{ts}] __CLEAR_LOGS__")
                    elif result:
                        for line in result.split("\n"):
                            ws_send(self, f"[{ts}] {line}")
            with ws_lock:
                if self in ws_clients:
                    ws_clients.remove(self)
            return

        if p.path == "/stats":
            if not self._check_console_auth():
                self.send_response(403); self.end_headers(); return
            data = json.dumps(get_stats()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return

        if p.path in ("/", ""):
            if not self._check_console_auth():
                # Przekieruj na stronę logowania głównego serwera
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{PORT}/login")
                self.end_headers()
                return
            page = (CONSOLE_HTML
                .replace("PORT_MAIN", str(PORT))
                .replace("PORT_WS",   str(CONSOLE_PORT))
            )
            b = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return

        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    admin_pass = ensure_admin()
    _current_admin_pass = admin_pass

    t = threading.Thread(target=broadcast_logs, daemon=True)
    t.start()

    rl = threading.Thread(target=ram_limiter, daemon=True)
    rl.start()



    socketserver.TCPServer.allow_reuse_address = True
    con_srv = socketserver.ThreadingTCPServer((HOST, CONSOLE_PORT), ConsoleHandler)
    con_srv.allow_reuse_address = True
    ct = threading.Thread(target=con_srv.serve_forever, daemon=True)
    ct.start()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((HOST, PORT), Handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            con_srv.shutdown()