#!/usr/bin/env python3
"""
Uruchom:  python3 StartUp.py
Komputer: http://localhost:8080
Telefon:  http://<twoje-ip>:8080   (ta sama siec Wi-Fi)

Logowanie: kazdy uzytkownik ma swoj wlasny folder w ./SAFE CLOUD/<username>/
Dane kont sa zapisane w ./users.json (hasla jako PBKDF2-HMAC-SHA256 z sola)

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
MAINTENANCE_FILE = Path("./maintenance.json")
HOST        = "0.0.0.0"
SESSION_TTL = 60 * 60 * 24 * 30  # sesja wazna 30 dni
ADMIN_USER  = "admin"        # nazwa konta admina
OWNER_USER  = ""             # owner ustawiany przez: set owner <user>
# ──────────────────────────────────────────────────────

STORAGE_DIR.mkdir(exist_ok=True)

# ── TRYB KONSERWACJI ──────────────────────────────────
_MAINTENANCE_DEFAULT = {"active": False, "message": "Serwer jest chwilowo niedostepny. Wróc za chwile."}

def _load_maintenance():
    if MAINTENANCE_FILE.exists():
        try:
            return json.loads(MAINTENANCE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(_MAINTENANCE_DEFAULT)

def _save_maintenance(d):
    MAINTENANCE_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

_maintenance = _load_maintenance()

MAINTENANCE_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>SAFE CLOUD \u2014 Konserwacja</title>
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){
  function makeFavicon(){
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="#818cf8" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.12)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="#818cf8" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el)el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',makeFavicon);}else{makeFavicon();}
})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#09090b;--sur:#18181b;--brd:#27272a;
  --txt:#e6edf3;--muted:#7d8590;
  --acc:#e2e8f0;--acc2:#94a3b8;
  --gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);
  --gr3:rgba(67,56,202,.28);--gr4:rgba(124,58,237,.20);
}
body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
  background-image:none;
}
.card{
  background:var(--sur);border:1px solid var(--brd);border-radius:20px;
  padding:44px 38px;width:100%;max-width:400px;text-align:center;
  box-shadow:0 24px 64px rgba(0,0,0,.55);
  position:relative;z-index:1;
}
/* Logo */
.logo{
  display:flex;align-items:center;justify-content:center;gap:10px;
  font-family:'Audiowide',sans-serif;font-size:19px;font-weight:700;
  letter-spacing:.04em;margin-bottom:6px;
}
.lm{width:36px;height:36px;border-radius:9px;overflow:hidden;
  display:flex;align-items:center;justify-content:center}
.version{font-size:10px;font-weight:600;letter-spacing:.08em;color:var(--acc2);
  text-align:center;margin-bottom:32px;font-family:'Inter',sans-serif}
/* Ikona narzędzi */
.maint-icon-wrap{
  width:72px;height:72px;border-radius:20px;margin:0 auto 24px;
  background:linear-gradient(135deg,rgba(79,70,229,.18),rgba(129,140,248,.10));
  border:1px solid rgba(129,140,248,.22);
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 32px rgba(79,70,229,.15);
  animation:pulse 3s ease-in-out infinite;
}
@keyframes pulse{
  0%,100%{box-shadow:0 0 24px rgba(79,70,229,.15);}
  50%{box-shadow:0 0 44px rgba(129,140,248,.32);}
}
.maint-icon-wrap svg{animation:spin 8s linear infinite;}
@keyframes spin{from{transform:rotate(0deg);}to{transform:rotate(360deg);}}
/* Tekst */
h2{font-size:19px;font-weight:700;margin-bottom:10px;letter-spacing:.01em}
.msg{font-size:14px;color:var(--muted);line-height:1.65;margin-bottom:28px}
/* Separator */
.sep{height:1px;background:var(--brd);margin:0 0 22px}
/* Status bar */
.status-row{
  display:flex;align-items:center;justify-content:center;gap:8px;
  font-size:12px;color:var(--muted);
}
.status-dot{
  width:7px;height:7px;border-radius:50%;background:var(--acc);
  animation:blink 1.4s ease-in-out infinite;flex-shrink:0;
}
@keyframes blink{0%,100%{opacity:1;}50%{opacity:.25;}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="lm">
      <svg viewBox="0 0 38 22" width="32" height="19" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z"
              stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round"
              fill="rgba(129,140,248,0.08)"/>
        <path d="M11 8.5a3.5 3.5 0 012.2-3.2"
              stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/>
      </svg>
    </div>
    SAFE CLOUD
  </div>
  <div class="version">KONSERWACJA</div>

  <div class="maint-icon-wrap">
    <!-- Ikona kluczy krzyżowych -->
    <svg viewBox="0 0 24 24" fill="none" stroke="var(--acc)" stroke-width="1.5"
         stroke-linecap="round" stroke-linejoin="round" width="34" height="34">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>
    </svg>
  </div>

  <h2>Trwa konserwacja</h2>
  <p class="msg">%%MSG%%</p>

  <div class="sep"></div>

  <div class="status-row">
    <div class="status-dot"></div>
    Wróć za chwilę &mdash; pracujemy nad ulepszeniami
  </div>
</div>
%%BG_ANIM%%
</body>
</html>"""
# ──────────────────────────────────────────────────────

# ── ANIMOWANE TŁO (gwiazdy + fale gradientów) ─────────
# Wstrzykiwane do każdej strony tuż przed </body>
BG_ANIMATION_JS = """<canvas id="bg-canvas" style="position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0"></canvas>
<style>
#bg-canvas{opacity:.85;height:100% !important}
@supports (height:100dvh){#bg-canvas{height:100dvh !important}}
</style>
<script>
(function(){
  var cv=document.getElementById('bg-canvas');
  var ctx=cv.getContext('2d');
  var W,H,stars=[],shooters=[];
  var gr1c,gr2c,gr3c,accc;
  var _saveFrame=0;

  function parseRgba(v){
    v=v.trim();
    var m=v.match(/rgba?[(]([^)]+)[)]/);
    if(m){var p=m[1].split(',');return{r:+p[0],g:+p[1],b:+p[2],a:p[3]!=null?+p[3]:1};}
    return{r:79,g:70,b:229,a:.5};
  }
  function hexToRgb(h){
    h=h.replace('#','');
    if(h.length===3)h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    return{r:parseInt(h.slice(0,2),16),g:parseInt(h.slice(2,4),16),b:parseInt(h.slice(4,6),16)};
  }
  function readColors(){
    var s=getComputedStyle(document.documentElement);
    gr1c=parseRgba(s.getPropertyValue('--gr1')||'rgba(79,70,229,.55)');
    gr2c=parseRgba(s.getPropertyValue('--gr2')||'rgba(109,40,217,.30)');
    gr3c=parseRgba(s.getPropertyValue('--gr3')||'rgba(67,56,202,.28)');
    var acc=s.getPropertyValue('--acc').trim()||'#e2e8f0';
    accc=hexToRgb(acc);
  }

  /* ── Zapis / odczyt stanu z sessionStorage ── */
  var SS_KEY='sc_bg_state';
  function saveState(){
    try{
      var st={
        t:t,
        stars:stars.map(function(s){return[
          Math.round(s.x*10)/10,
          Math.round(s.y*10)/10,
          Math.round(s.r*100)/100,
          Math.round(s.vy*1000)/1000,
          Math.round(s.tw*1000)/1000,
          Math.round(s.ts*10000)/10000
        ];}),
        ts:Date.now()
      };
      sessionStorage.setItem(SS_KEY,JSON.stringify(st));
    }catch(e){}
  }
  function loadState(){
    try{
      var raw=sessionStorage.getItem(SS_KEY);
      if(!raw)return null;
      var st=JSON.parse(raw);
      /* Porzuć stan starszy niż 30s — strona mogła się odświeżyć po długiej przerwie */
      if(Date.now()-st.ts>30000)return null;
      /* Kompensuj czas który minął między zapisem a odczytem */
      var elapsed=(Date.now()-st.ts)/1000;
      st.t+=elapsed*0.011;
      return st;
    }catch(e){return null;}
  }

  /* Stabilny rozmiar — ignoruje znikający pasek przeglądarki na iOS */
  var _stableW=0,_stableH=0,_resizeTimer=null;
  function getStableSize(){
    if(window.visualViewport){
      return{w:Math.round(window.visualViewport.width),h:Math.round(window.visualViewport.height)};
    }
    return{w:window.innerWidth,h:window.innerHeight};
  }
  function resize(){
    var sz=getStableSize();
    if(sz.w===_stableW && Math.abs(sz.h-_stableH)<120) return;
    _stableW=sz.w; _stableH=sz.h;
    W=cv.width=_stableW;
    H=cv.height=_stableH;
    initStars();
  }
  function debouncedResize(){
    clearTimeout(_resizeTimer);
    _resizeTimer=setTimeout(resize,150);
  }

  function initStars(savedStars){
    stars=[];
    var n=Math.round(W*H/10000);n=Math.max(50,Math.min(180,n));
    if(savedStars&&savedStars.length===n){
      /* Odtwórz zapisane gwiazdy — skaluj pozycje do aktualnego rozmiaru ekranu */
      var savedW=savedStars.reduce(function(mx,s){return Math.max(mx,s[0]);},0)||W;
      var savedH=savedStars.reduce(function(mx,s){return Math.max(mx,s[1]);},0)||H;
      var sx=W/Math.max(savedW,1), sy=H/Math.max(savedH,1);
      for(var i=0;i<n;i++){
        var s=savedStars[i];
        stars.push({x:s[0]*sx,y:s[1]*sy,r:s[2],vy:s[3],tw:s[4],ts:s[5]});
      }
    } else {
      for(var i=0;i<n;i++){
        stars.push({
          x:Math.random()*W, y:Math.random()*H,
          r:Math.random()*1.5+.3,
          vy:Math.random()*.12+.03,
          tw:Math.random()*Math.PI*2,
          ts:Math.random()*.03+.008
        });
      }
    }
  }

  function spawnShooter(){
    if(shooters.length<3&&Math.random()<.004){
      shooters.push({
        x:Math.random()*W*.6, y:Math.random()*H*.35,
        vx:2.8+Math.random()*2.2, vy:1.2+Math.random()*1.6,
        life:1
      });
    }
  }

  var t=0;
  function frame(){
    ctx.clearRect(0,0,W,H);

    /* ── fale gradientów ── */
    var blobs=[
      {x:W*.3+Math.sin(t*.55)*W*.22, y:H*.15+Math.cos(t*.42)*H*.18, r:W*.7,  c:gr1c},
      {x:W*.72+Math.cos(t*.48)*W*.18,y:H*.75+Math.sin(t*.65)*H*.22, r:W*.55, c:gr2c},
      {x:W*.5 +Math.sin(t*.33)*W*.12, y:H*.5+Math.cos(t*.72)*H*.12, r:W*.42, c:gr3c},
    ];
    blobs.forEach(function(b){
      var g=ctx.createRadialGradient(b.x,b.y,0,b.x,b.y,b.r);
      g.addColorStop(0,'rgba('+b.c.r+','+b.c.g+','+b.c.b+','+(b.c.a*.9)+')');
      g.addColorStop(1,'rgba('+b.c.r+','+b.c.g+','+b.c.b+',0)');
      ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
    });

    /* ── gwiazdy ── */
    var isLight=document.documentElement.classList.contains('theme-light');
    var starColor=isLight?'10,10,20':'230,237,243';
    var shootColor=isLight?'20,20,60':'255,255,255';
    stars.forEach(function(s){
      s.tw+=s.ts;
      var alpha=(isLight?.15:.25)+Math.sin(s.tw)*(isLight?.10:.22);
      ctx.beginPath(); ctx.arc(s.x,s.y,s.r,0,Math.PI*2);
      ctx.fillStyle='rgba('+starColor+','+alpha+')';
      ctx.fill();
      s.y+=s.vy; if(s.y>H){s.y=-2;s.x=Math.random()*W;}
    });

    /* ── spadające gwiazdy ── */
    spawnShooter();
    for(var i=shooters.length-1;i>=0;i--){
      var s=shooters[i];
      var tlen=55;
      var tx=s.x-s.vx*(tlen/Math.sqrt(s.vx*s.vx+s.vy*s.vy))*1.8;
      var ty=s.y-s.vy*(tlen/Math.sqrt(s.vx*s.vx+s.vy*s.vy))*1.8;
      var gsh=ctx.createLinearGradient(tx,ty,s.x,s.y);
      gsh.addColorStop(0,'rgba('+shootColor+',0)');
      gsh.addColorStop(1,'rgba('+shootColor+','+(s.life*.75)+')');
      ctx.beginPath(); ctx.moveTo(tx,ty); ctx.lineTo(s.x,s.y);
      ctx.strokeStyle=gsh; ctx.lineWidth=1.4; ctx.stroke();
      ctx.beginPath(); ctx.arc(s.x,s.y,1.8,0,Math.PI*2);
      ctx.fillStyle='rgba('+shootColor+','+s.life+')'; ctx.fill();
      s.x+=s.vx; s.y+=s.vy; s.life-=.016;
      if(s.life<=0||s.x>W+50||s.y>H+50) shooters.splice(i,1);
    }

    t+=.011;

    /* Zapisuj stan co ~60 klatek (~1s) */
    _saveFrame++;
    if(_saveFrame%30===0) saveState();

    requestAnimationFrame(frame);
  }

  /* Zapisz stan przed opuszczeniem strony */
  window.addEventListener('pagehide', saveState);
  window.addEventListener('beforeunload', saveState);

  /* Init — odtwórz stan jeśli jest */
  var sz=getStableSize();
  _stableW=W=cv.width=sz.w;
  _stableH=H=cv.height=sz.h;
  readColors();
  var saved=loadState();
  if(saved){
    t=saved.t;
    initStars(saved.stars);
  } else {
    initStars(null);
  }
  frame();

  window.addEventListener('resize', debouncedResize);
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize', debouncedResize);
  }
  new MutationObserver(readColors).observe(document.documentElement,{attributes:true,attributeFilter:['style']});

  /* Upewnij się że karta jest nad canvasem */
  document.querySelectorAll('.card,.card-wrap,main,.viewer,.topbar').forEach(function(el){
    if(getComputedStyle(el).position==='static') el.style.position='relative';
    el.style.zIndex='1';
  });
})();
</script>"""
# ──────────────────────────────────────────────────────
import struct, hmac, base64 as _b64, hashlib as _hl, time as _time_mod

TOTP_FILE = Path("./totp.json")

def _totp_load():
    if TOTP_FILE.exists():
        try: return json.loads(TOTP_FILE.read_text(encoding="utf-8"))
        except: pass
    return {}

def _totp_save(d):
    TOTP_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

def totp_get_secret(username):
    return _totp_load().get(username, {}).get("secret")

def totp_is_enabled(username):
    return bool(_totp_load().get(username, {}).get("enabled"))

def totp_enable(username, secret):
    d = _totp_load()
    d[username] = {"secret": secret, "enabled": True}
    _totp_save(d)

def totp_disable(username):
    d = _totp_load()
    if username in d:
        del d[username]
        _totp_save(d)

def totp_generate_secret():
    return _b64.b32encode(secrets.token_bytes(20)).decode()

def totp_get_uri(username, secret):
    label = urllib.parse.quote(f"SafeCloud:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer=SafeCloud&algorithm=SHA1&digits=6&period=30"

def totp_hotp(secret, counter):
    try:
        key = _b64.b32decode(secret.upper())
    except Exception:
        return -1
    msg = struct.pack(">Q", counter)
    h   = hmac.new(key, msg, _hl.sha1).digest()
    offset = h[-1] & 0x0f
    code = struct.unpack(">I", h[offset:offset+4])[0] & 0x7fffffff
    return code % 1000000

def totp_verify(secret, code, window=1):
    t = int(_time_mod.time()) // 30
    for i in range(-window, window + 1):
        if totp_hotp(secret, t + i) == int(code):
            return True
    return False

# Tymczasowe tokeny po poprawnym haśle (oczekiwanie na kod 2FA)
_totp_pending = {}  # { token: (username, expires) }

def totp_pending_create(username):
    token = secrets.token_hex(24)
    _totp_pending[token] = (username, time.time() + 300)  # 5 min
    return token

def totp_pending_get(token):
    entry = _totp_pending.get(token)
    if not entry: return None
    username, exp = entry
    if time.time() > exp:
        del _totp_pending[token]
        return None
    return username

def totp_pending_del(token):
    _totp_pending.pop(token, None)

# ── AUTO BACKUP ───────────────────────────────────────
BACKUP_DIR      = Path("./backups")
BACKUP_MAX_KEEP = 3
BACKUP_INTERVAL = 60 * 60 * 24  # 24h

def auto_backup_run():
    """Tworzy ZIP backup folderu SAFE CLOUD. Zachowuje max BACKUP_MAX_KEEP plików."""
    import zipfile as _zf
    BACKUP_DIR.mkdir(exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"backup_{ts}.zip"
    count = 0
    try:
        with _zf.ZipFile(out, "w", _zf.ZIP_DEFLATED) as zf:
            for fp in STORAGE_DIR.rglob("*"):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(STORAGE_DIR.parent))
                    count += 1
        size = human_size(out.stat().st_size)
        print(f"[BACKUP] ✓ Zapisano: {out.name} ({count} plików, {size})")
        # Usuń stare backupy
        all_backups = sorted(BACKUP_DIR.glob("backup_*.zip"), key=lambda x: x.stat().st_mtime)
        while len(all_backups) > BACKUP_MAX_KEEP:
            old = all_backups.pop(0)
            old.unlink()
            print(f"[BACKUP] Usunięto stary backup: {old.name}")
    except Exception as e:
        print(f"[BACKUP] ✗ Błąd: {e}")

def auto_backup_loop():
    """Co BACKUP_INTERVAL sekund tworzy backup."""
    while True:
        time.sleep(BACKUP_INTERVAL)
        auto_backup_run()


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

def get_owner_username():
    """Zwraca nazwę aktualnego właściciela z users.json lub None jeśli nie ustawiono."""
    users = load_users()
    for u, v in users.items():
        if isinstance(v, dict) and v.get("owner"):
            return u
    return None

def set_owner_username(new_owner):
    """Zapisuje właściciela w users.json (flaga owner: true)."""
    users = load_users()
    # Usuń flagę od poprzedniego właściciela
    for u, v in users.items():
        if isinstance(v, dict) and v.get("owner"):
            users[u]["owner"] = False
    # Ustaw nowego
    if new_owner in users:
        if isinstance(users[new_owner], dict):
            users[new_owner]["owner"] = True
        else:
            users[new_owner] = {"password": users[new_owner], "role": None, "owner": True}
    save_users(users)


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

def hash_password(pw, salt=None):
    """
    Hashuje hasło używając PBKDF2-HMAC-SHA256 z losową solą.
    Zwraca string w formacie: pbkdf2$<sól_hex>$<hash_hex>
    Jeśli podano salt (hex), używa go — tylko przy weryfikacji migracji (nie używaj zewnętrznie).
    """
    if salt is None:
        salt = secrets.token_hex(32)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode("utf-8"), 260_000)
    return f"pbkdf2${salt}${dk.hex()}"

def verify_password(pw, stored):
    """
    Weryfikuje hasło. Obsługuje stary format SHA-256 (legacy) i nowy PBKDF2.
    Przy starym formacie zwraca (True, new_hash) sygnalizując potrzebę migracji.
    """
    if stored.startswith("pbkdf2$"):
        try:
            _, salt, _ = stored.split("$")
        except ValueError:
            return False, None
        return hash_password(pw, salt) == stored, None
    # Stary format SHA-256 — weryfikacja i sygnał do migracji
    if hashlib.sha256(pw.encode()).hexdigest() == stored:
        return True, hash_password(pw)  # zwraca nowy hash do nadpisania
    return False, None

def generate_admin_password():
    charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%&*"
    return "".join(secrets.choice(charset) for _ in range(16))

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

def handle_command(cmd, caller=""):
    """Obsługa komend z konsoli. Zwraca odpowiedź jako string."""
    parts = cmd.strip().split()
    if not parts:
        return None
    c = parts[0].lower()

    # --ver
    if c == "--ver":
        if len(parts) >= 3 and parts[1].lower() == "set":
            if is_moderator(caller):
                return "[CMD] ✗ Brak uprawnień."
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
        if user == ADMIN_USER or is_owner(user):
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
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
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
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
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

    # add mod <user>
    if c == "add" and len(parts) >= 2 and parts[1].lower() == "mod":
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: add mod <user>"
        user = parts[2]
        users = load_users()
        if user not in users:
            return f"[CMD] ✗ Użytkownik '{user}' nie istnieje."
        if user == ADMIN_USER or is_owner(user):
            return "[CMD] ✗ Admin i owner nie mogą być moderatorami."
        v = users[user]
        if isinstance(v, dict):
            users[user]["moderator"] = True
        else:
            users[user] = {"password": v, "role": None, "moderator": True}
        save_users(users)
        return f"[CMD] ✓ Użytkownik '{user}' jest teraz moderatorem."

    # remove mod <user>
    if c == "remove" and len(parts) >= 2 and parts[1].lower() == "mod":
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: remove mod <user>"
        user = parts[2]
        users = load_users()
        if user not in users or not is_moderator(user):
            return f"[CMD] ✗ Użytkownik '{user}' nie jest moderatorem."
        users[user]["moderator"] = False
        save_users(users)
        return f"[CMD] ✓ Usunięto uprawnienia moderatora od '{user}'."

    # list mods
    if c == "list" and len(parts) >= 2 and parts[1].lower() == "mods":
        users = load_users()
        mods = [u for u in users if is_moderator(u)]
        if not mods:
            return "[CMD] Brak moderatorów."
        lines = ["[CMD] Moderatorzy:"]
        for u in mods:
            lines.append(f"  {u}")
        return "\n".join(lines)

    if c == "list" and len(parts) >= 2 and parts[1].lower() == "users":
        users = load_users()
        if not users:
            return "[CMD] Brak użytkowników."
        lines = ["[CMD] Użytkownicy:"]
        for u in users:
            r = get_user_role(users, u)
            role_info = f"  [{r['name']}]" if r else ""
            mod_info  = "  [MOD]" if is_moderator(u) else ""
            ban_info  = "  [ZBANOWANY]" if get_ban(u) else ""
            tag = " [ADMIN]" if u == ADMIN_USER else (" [OWNER]" if is_owner(u) else "")
            lines.append(f"  {u}{tag}{mod_info}{role_info}{ban_info}")
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

    # revoke <token> | revoke all
    if c == "revoke":
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: revoke <token>  lub  revoke all"
        if parts[1].lower() == "all":
            if is_moderator(caller):
                return "[CMD] ✗ Brak uprawnień."
            all_shares = load_shares()
            count = len(all_shares)
            if not count:
                return "[CMD] ~ Brak aktywnych linków do usunięcia."
            save_shares({})
            print(f"[SHARE] Wszystkie linki ({count}) usunięte przez {caller}.")
            return f"[CMD] ✓ Usunięto wszystkie {count} aktywnych linków udostępniania."
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
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        if len(parts) < 2:
            return "[CMD] ✗ Użycie: deluser <user> [--files]"
        user = parts[1]
        if user == ADMIN_USER or is_owner(user):
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



    # stats — pełne statystyki serwera w stylu menu
    if c == "stats":
        s = get_stats()
        if not s.get("ok"):
            return f"[CMD] ✗ Błąd pobierania statystyk: {s.get('error', '?')}"
        ram_mb  = s["ram_rss_raw"] / (1024 * 1024)
        cpu     = s["cpu"]
        thr     = s["threads"]
        con     = s["conns"]
        ses     = s["sessions"]
        cache   = s["cache"]
        dr      = s.get("disk_r") or "—"
        dw      = s.get("disk_w") or "—"
        # ocena RAM
        if ram_mb >= 250:   ram_icon = "🔴"
        elif ram_mb >= 150: ram_icon = "🟡"
        elif ram_mb >= 100: ram_icon = "🟠"
        else:               ram_icon = "🟢"
        # ocena CPU
        if cpu >= 80:   cpu_icon = "🔴"
        elif cpu >= 50: cpu_icon = "🟡"
        else:           cpu_icon = "🟢"
        # ocena wątków
        thr_icon = "🟡" if thr >= 50 else "🟢"
        # ocena połączeń
        con_icon = "🟡" if con >= 30 else "🟢"
        # ocena ogólna
        problems = []
        if ram_mb >= 280:   problems.append("RAM krytyczny")
        elif ram_mb >= 220: problems.append("RAM podwyższony")
        if cpu >= 80:       problems.append("CPU bardzo wysokie")
        elif cpu >= 50:     problems.append("CPU podwyższone")
        if thr >= 50:       problems.append(f"dużo wątków ({thr})")
        if con >= 30:       problems.append(f"dużo połączeń ({con})")
        if not problems:
            if ram_mb < 100 and cpu < 20:
                ocena = "✓ Doskonały — serwer działa bez zarzutu"
            elif ram_mb < 150 and cpu < 40:
                ocena = "✓ Dobry — wszystko w normie"
            else:
                ocena = "~ Stabilny — brak problemów, zasoby rosną"
        elif len(problems) == 1:
            ocena = f"⚠ Uwaga — {problems[0]}"
        else:
            ocena = f"⚠ Problemy: {', '.join(problems)}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        w = 54  # szerokość ramki
        sep  = "─" * w
        sep2 = "═" * w
        def row(label, val, icon=""):
            pad = w - len(label) - len(str(val)) - (2 if icon else 0)
            if icon:
                return f"  {icon} {label}{' ' * (pad - 1)}{val}"
            return f"  {label}{' ' * pad}{val}"
        lines = [
            f"╔{sep2}╗",
            f"║{'  📊 STATYSTYKI SERWERA — SAFE CLOUD':^{w}}║",
            f"╠{sep2}╣",
            f"║{' ' * w}║",
            f"║  🕐 Czas pomiaru: {now_str:<{w - 19}}║",
            f"║  📌 Stan: {ocena:<{w - 10}}║",
            f"║{' ' * w}║",
            f"╠{'─ PAMIĘĆ ':─<{w}}╣",
            f"║{row('RAM (RSS):', s['ram_rss'], ram_icon):<{w + 3}}║",
            f"║{row('RAM (VMS):', s['ram_vms']):<{w + 2}}║",
            f"║{' ' * w}║",
            f"╠{'─ PROCESOR ':─<{w}}╣",
            f"║{row('Użycie CPU:', f'{cpu} %', cpu_icon):<{w + 3}}║",
            f"║{row('Wątki:', str(thr), thr_icon):<{w + 3}}║",
            f"║{' ' * w}║",
            f"╠{'─ SIEĆ ':─<{w}}╣",
            f"║{row('Aktywne połączenia:', str(con), con_icon):<{w + 3}}║",
            f"║{row('Aktywne sesje:', str(ses)):<{w + 2}}║",
            f"║{' ' * w}║",
            f"╠{'─ DYSK ':─<{w}}╣",
            f"║{row('Odczyt dysku:', dr):<{w + 2}}║",
            f"║{row('Zapis dysku:', dw):<{w + 2}}║",
            f"║{' ' * w}║",
            f"╠{'─ INTERNET ':─<{w}}╣",
            f"║{row('Wysyłanie:', nu):<{w + 2}}║",
            f"║{row('Pobieranie:', nd):<{w + 2}}║",
            f"║{' ' * w}║",
            f"╠{'─ CACHE ':─<{w}}╣",
            f"║{row('Miniaturki w cache:', str(cache)):<{w + 2}}║",
            f"║{' ' * w}║",
            f"╚{sep2}╝",
        ]
        return "\n".join(lines)

    # help
    # adminpass
    if c == "adminpass":
        if not (is_admin(caller) or is_owner(caller)):
            return "[CMD] ✗ Brak uprawnień."
        return f"[CMD] \U0001f511 Aktualne haslo admina: {_current_admin_pass}"

    if c == "help" and len(parts) >= 2 and parts[1].lower() == "mod":
        return (
            "[CMD] ─────────────────────────── Pomoc: komenda MOD ───────────────────────────\n"
            "  Moderator ma dostęp do terminala w interfejsie użytkownika,\n"
            "  ale NIE może logować się do konsoli administracyjnej (port 8081).\n"
            "\n"
            "  Nadawanie uprawnień moderatora:\n"
            "    add mod <user>\n"
            "\n"
            "  Odbieranie uprawnień moderatora:\n"
            "    remove mod <user>\n"
            "\n"
            "  Lista moderatorów:\n"
            "    list mods\n"
            "\n"
            "  Możliwości moderatora:\n"
            "    · Widzi terminal w głównym interfejsie (port 8080)\n"
            "    · Może wykonywać komendy przez terminal\n"
            "    · Widzi statystyki serwera (RAM, CPU itd.)\n"
            "    · Ma niebieską odznakę MOD przy nazwie\n"
            "\n"
            "  Ograniczenia moderatora:\n"
            "    · Brak dostępu do konsoli na porcie 8081\n"
            "    · Nie może wykonać: set owner\n"
            "    · Nie może zbanować ani usunąć konta admin/owner\n"
            "    · Uprawnienia zapisywane są w users.json (flaga moderator: true)\n"
            "[CMD] ──────────────────────────────────────────────────────────────────────────"
        )

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
        if is_moderator(caller):
            return (
                "──────────────────KOMENDY (MOD)──────────────────\n"
                "[CMD] Dostępne komendy:\n"
                "  ban <user> <czas> <s/m/h/d> [powód]   – zbanuj na czas\n"
                "  ban <user> permanent [powód]          – ban permanentny\n"
                "  unban <user>                          – zdejmij bana\n"
                "  list bans                             – lista banów\n"
                "  help ban                              – szczegółowa pomoc o banach\n"
                "  list users                            – lista użytkowników\n"
                "  list shares                           – lista aktywnych linków udostępniania\n"
                "  revoke <token>                        – unieważnij link udostępniania\n"
                "  list mods                             – lista moderatorów\n"
                "  list roles                            – lista ról\n"
                "  disk                                  – zajęte miejsce per użytkownik\n"
                "  clear logs                            – wyczyść terminal\n"
                "  ping                                  – sprawdź ping między tobą a serwerem\n"
                "  stats                                 – szczegółowe statystyki serwera (ramka)\n"
                "  status                                – krótki stan serwera (RAM, CPU, wątki...)\n"
                "  --ver                                 – pokaż aktualną wersję aplikacji\n"
                "  help                                  – ta pomoc\n"
                "\n"
                "──────────────────"
            )
        return (
            "──────────────────KOMENDY──────────────────\n"
            "[CMD] Dostępne komendy:\n"
            "  adminpass                             – pokaż aktualne hasło admina\n"
            "  ban <user> <czas> <s/m/h/d> [powód]   – zbanuj na czas\n"
            "  ban <user> permanent [powód]          – ban permanentny\n"
            "  unban <user>                          – zdejmij bana\n"
            "  list bans                             – lista banów\n"
            "  add mod <user>                        – nadaj uprawnienia moderatora\n"
            "  remove mod <user>                     – usuń uprawnienia moderatora\n"
            "  list mods                             – lista moderatorów\n"
            "  help mod                              – szczegółowa pomoc o moderatorach\n"
            "  add role <user> <nazwa> <#kolor>      – nadaj rolę\n"
            "  remove role <user>                    – usuń rolę\n"
            "  list roles                            – lista ról\n"
            "  list users                            – lista użytkowników\n"
            "  list shares                           – lista aktywnych linków udostępniania\n"
            "  revoke <token>                        – unieważnij link udostępniania\n"
            "  revoke all                            – usuń wszystkie aktywne linki\n"
            "  deluser <user>                        – usuń konto (pliki zostają)\n"
            "  deluser <user> --files                – usuń konto i wszystkie pliki\n"
            "  passwd <user> <haslo>                 – zmień hasło użytkownika\n"
            "  set owner <user>                      – ustaw konto właściciela (tymczasowo)\n"
            "  disk                                  – zajęte miejsce per użytkownik\n"
            "  backup                                – spakuj cały SAFE CLOUD do ZIP\n"
            "  clear logs                            – wyczyść terminal\n"
            "  maintenance on [msg]                  – włącz tryb konserwacji\n"
            "  maintenance off                       – wyłącz tryb konserwacji\n"
            "  maintenance status                    – sprawdź stan konserwacji\n"
            "  --m on/off/status                     – skrót komendy maintenance\n"
            "  ping                                  – sprawdź ping między tobą a serwerem\n"
            "  ping ngrok                            – sprawdź ping do tunelu ngrok\n"
            "  stats                                 – szczegółowe statystyki serwera (ramka)\n"
            "  status                                – krótki stan serwera (RAM, CPU, wątki...)\n"
            "  restart / reset / --r                 – zrestartuj serwer\n"
            "  --ver                                 – pokaż aktualną wersję aplikacji\n"
            "  --ver set <X.Y.Z> [stage]             – ustaw wersję (stage: alpha/beta/rc/stable)\n"
            "  help                                  – ta pomoc\n"
            "\n" 
            "──────────────────"
        )

    # set owner <user>
    if c == "set" and len(parts) >= 2 and parts[1].lower() == "owner":
        if len(parts) < 3:
            return "[CMD] ✗ Użycie: set owner <user>"
        # Moderator nigdy nie może zmienić ownera
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        # Jeśli owner jest ustawiony — tylko on może go zmienić
        # Jeśli owner nie jest ustawiony — może admin
        current_owner = get_owner_username()
        if current_owner and not is_owner(caller):
            return "[CMD] ✗ Tylko właściciel może zmienić konto właściciela."
        if not current_owner and not is_admin(caller):
            return "[CMD] ✗ Tylko admin może ustawić właściciela po raz pierwszy."
        new_owner = parts[2]
        users = load_users()
        if new_owner not in users:
            return f"[CMD] ✗ Użytkownik '{new_owner}' nie istnieje."
        if new_owner == ADMIN_USER:
            return "[CMD] ✗ Konto admin nie może być właścicielem."
        old_owner = current_owner or "(brak)"
        set_owner_username(new_owner)
        return f"[CMD] ✓ Właściciel zmieniony z '{old_owner}' na '{new_owner}'. Zapisano w users.json."

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
        nu = s.get('net_up')   or '—'
        nd = s.get('net_down') or '—'
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
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        import threading as _th
        def _do_restart():
            time.sleep(0.8)
            import sys, os as _os, subprocess as _sp
            try:
                if sys.platform == "win32":
                    # Na Windows: uruchom nowy proces z własną konsolą
                    _sp.Popen(
                        [sys.executable] + sys.argv,
                        creationflags=0x00000010,  # CREATE_NEW_CONSOLE
                        close_fds=True
                    )
                else:
                    # Linux/macOS: nowy proces w tle
                    _sp.Popen(
                        [sys.executable] + sys.argv,
                        start_new_session=True
                    )
            except Exception:
                pass
            _os._exit(0)
        _th.Thread(target=_do_restart, daemon=True).start()
        return "[CMD] ✓ Serwer restartuje się... odśwież stronę za chwilę."

    # passwd <user> <nowe_haslo>
    if c == "passwd":
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
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
            tag = " [ADMIN]" if name == ADMIN_USER else (" [OWNER]" if is_owner(name) else "")
            lines.append(f"  {name}{tag}  —  {human_size(size)}  ({count} plików)")
        grand = sum(x[1] for x in totals)
        lines.append(f"  ─────────────────────────")
        lines.append(f"  RAZEM  —  {human_size(grand)}")
        return "\n".join(lines)

    # backup
    if c == "backup":
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
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

    # maintenance on [wiadomość] / maintenance off / maintenance status
    if c in ("maintenance", "--m"):
        if is_moderator(caller):
            return "[CMD] ✗ Brak uprawnień."
        sub = parts[1].lower() if len(parts) >= 2 else ""
        if sub == "on":
            msg = " ".join(parts[2:]) if len(parts) >= 3 else _maintenance["message"]
            _maintenance["active"] = True
            _maintenance["message"] = msg
            _save_maintenance(_maintenance)
            print(f"[MAINTENANCE] Tryb konserwacji WŁĄCZONY przez {caller}. Wiadomość: {msg}")
            return f"[CMD] MAINTENANCE Tryb konserwacji WŁĄCZONY.\n[CMD] Wiadomość: {msg}\n[CMD] Dostęp: tylko admin i owner."
        elif sub == "off":
            _maintenance["active"] = False
            _save_maintenance(_maintenance)
            print(f"[MAINTENANCE] Tryb konserwacji WYŁĄCZONY przez {caller}.")
            return "[CMD] MAINTENANCE Tryb konserwacji WYŁĄCZONY. Serwer dostępny dla wszystkich."
        elif sub == "status":
            st = "WŁĄCZONY" if _maintenance["active"] else "wyłączony"
            return f"[CMD] Tryb konserwacji: {st}\n[CMD] Wiadomość: {_maintenance['message']}"
        elif sub == "msg" and len(parts) >= 3:
            _maintenance["message"] = " ".join(parts[2:])
            _save_maintenance(_maintenance)
            return f"[CMD] Wiadomość konserwacji zmieniona na: {_maintenance['message']}"
        else:
            return (
                "[CMD] Użycie:\n"
                "  maintenance on [wiadomość]  – włącz tryb konserwacji\n"
                "  maintenance off             – wyłącz tryb konserwacji\n"
                "  maintenance status          – sprawdź stan\n"
                "  maintenance msg <tekst>     – zmień wiadomość (bez włączania)"
            )

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
    users = load_users()
    v = users.get(username)
    return isinstance(v, dict) and bool(v.get("owner"))

def is_moderator(username):
    """Moderator ma dostęp do terminala w UI, ale nie do konsoli na porcie 8081."""
    users = load_users()
    v = users.get(username)
    return isinstance(v, dict) and bool(v.get("moderator"))

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

# ── CACHE MINIATUREK (LRU, max 40 wpisów / 20 MB) ────
from collections import OrderedDict
CACHE_MAX_ENTRIES = 40
CACHE_MAX_BYTES   = 20 * 1024 * 1024  # 20 MB
_cache_total_bytes = 0
thumb_cache: "OrderedDict[str, tuple]" = OrderedDict()  # { path_str: (mtime, jpeg_bytes) }

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

def _thumb_cache_put(key, mtime, data):
    """Wstawia do cache LRU i usuwa najstarsze wpisy gdy przekroczono limity."""
    global _cache_total_bytes
    # Usuń stary wpis jeśli istnieje
    if key in thumb_cache:
        _cache_total_bytes -= len(thumb_cache[key][1])
        del thumb_cache[key]
    thumb_cache[key] = (mtime, data)
    _cache_total_bytes += len(data)
    # Ewakuuj najstarsze wpisy
    while thumb_cache and (len(thumb_cache) > CACHE_MAX_ENTRIES or _cache_total_bytes > CACHE_MAX_BYTES):
        _, (_, evicted) = thumb_cache.popitem(last=False)
        _cache_total_bytes -= len(evicted)

def get_video_thumbnail(path, size=800):
    """Wyciąga klatkę z wideo przez ffmpeg i zwraca JPEG bytes. Lazy — tylko przy żądaniu."""
    import subprocess, io
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", "00:00:03",
                "-i", str(path),
                "-vframes", "1",
                "-f", "image2",
                "-vcodec", "mjpeg",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout:
            # Spróbuj od początku pliku (krótkie wideo)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-vframes", "1",
                 "-f", "image2", "-vcodec", "mjpeg", "pipe:1"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
            )
        if not result.stdout:
            return None
        with Image.open(io.BytesIO(result.stdout)) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72, optimize=True)
            return buf.getvalue()
    except FileNotFoundError:
        return None  # ffmpeg nie jest zainstalowany
    except Exception:
        return None

def get_thumbnail(path, size=800):
    """Zwraca JPEG miniaturkę jako bytes. Cache LRU po mtime."""
    try:
        from PIL import Image
        import io
        key   = str(path)
        mtime = path.stat().st_mtime
        if key in thumb_cache and thumb_cache[key][0] == mtime:
            # LRU: przesuń na koniec (najnowszy)
            thumb_cache.move_to_end(key)
            return thumb_cache[key][1]

        # Obsługa plików wideo — lazy, przez ffmpeg
        video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".flv", ".wmv"}
        if path.suffix.lower() in video_exts:
            data = get_video_thumbnail(path, size)
            if data:
                _thumb_cache_put(key, mtime, data)
            return data

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
                img.save(buf, format="JPEG", quality=75, optimize=True)
                data = buf.getvalue()
            _thumb_cache_put(key, mtime, data)
            return data

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70, optimize=True)
            data = buf.getvalue()
        _thumb_cache_put(key, mtime, data)
        return data
    except Exception:
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
            video_exts = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v", ".flv", ".wmv"}
            if is_image(name):
                thumb = f'<div class="thumb thumb-img"><img data-src="/thumb?path={enc}" alt="{sname}" class="lazy"></div>'
            elif Path(name).suffix.lower() in video_exts:
                thumb = f'<div class="thumb thumb-video"><div class="thumb-video-inner">{icon}<img class="thumb-video-cover lazy" data-src="/thumb?path={enc}" alt="" style="display:none"><div class="thumb-video-play"><svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20"><circle cx="12" cy="12" r="10" fill="rgba(0,0,0,.55)"/><polygon points="10,8 10,16 17,12" fill="white"/></svg></div></div></div>'
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
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){
  function makeFavicon(){
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }
  function init(){
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init);}else{init();}
})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#09090b;--sur:#18181b;--brd:#27272a;
  --txt:#e6edf3;--muted:#7d8590;
  --acc:#e2e8f0;--acc2:#94a3b8;--red:#f85149;
  --gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);--gr3:rgba(71,85,105,.10);--gr4:rgba(51,65,85,.08);
  --acc-rgb:129,140,248;
}
body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
  background-image:none;
}
.card{background:var(--sur);border:1px solid var(--brd);border-radius:16px;padding:36px 32px;width:100%;max-width:380px;box-shadow:0 20px 60px rgba(0,0,0,.5);position:relative;z-index:1}
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
.info{background:color-mix(in srgb,var(--acc) 10%,transparent);border:1px solid color-mix(in srgb,var(--acc) 30%,transparent);color:var(--acc);border-radius:8px;padding:10px 13px;font-size:13px;margin-bottom:14px;display:none}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><div class="lm"><svg viewBox="0 0 38 22" width="32" height="19" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/></svg></div>SAFE CLOUD</div>
  <div style="text-align:center;margin-top:-18px;margin-bottom:20px;font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--acc2);letter-spacing:.04em;font-weight:600">%%APP_VERSION%%</div>
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
%%BG_ANIM%%
</body>
</html>"""


MAIN_HTML = r"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>SAFE CLOUD%%ADMIN_TITLE%%</title>
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){
  function makeFavicon(){
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }
  function init(){
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init);}else{init();}
})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#09090b;--sur:#18181b;--brd:#27272a;
  --txt:#e6edf3;--muted:#7d8590;
  --acc:#e2e8f0;--acc2:#94a3b8;--acc-rgb:226,232,240;
  --red:#f85149;--folder:#e3b341;
  --gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);--gr3:rgba(71,85,105,.10);--gr4:rgba(51,65,85,.08);
  --admin:#a78bfa;
  --r:12px;
}
body{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;font-size:14px;
  overflow-y:scroll;scrollbar-width:none;
  background-image:none;
}
body::-webkit-scrollbar{display:none}
html{scrollbar-width:none}
html::-webkit-scrollbar{display:none}
header{background:var(--sur);backdrop-filter:blur(18px);border:1px solid var(--brd);border-radius:10px;position:sticky;top:10px;z-index:50;margin:10px 10px 0;box-shadow:0 4px 24px rgba(0,0,0,.4)}
%%ADMIN_HEADER_STYLE%%
.hi{padding:0 20px;height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.logo{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px;color:var(--txt);text-decoration:none}
.brand{font-family:'Audiowide',sans-serif;letter-spacing:.04em;line-height:1}
.lm{width:38px;height:24px;border-radius:0;overflow:visible;display:flex;align-items:center;justify-content:center;background:none!important}
.lm-admin{background:linear-gradient(135deg,#3730a3,#a78bfa);}
.hs{display:flex;align-items:center;gap:16px}
.st{font-size:12px;color:var(--muted)}
.st b{color:var(--txt);font-weight:500}
.user-badge{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:500;color:var(--txt)}
.avatar{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,var(--acc2),var(--acc));display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700;flex-shrink:0}
.avatar-admin{background:linear-gradient(135deg,var(--acc2),var(--acc));}
.avatar-owner{background:linear-gradient(135deg,#92400e,#f59e0b);}
.admin-badge{font-size:10px;font-weight:700;background:rgba(167,139,250,.15);color:var(--admin);border:1px solid rgba(167,139,250,.35);border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.owner-badge{font-size:10px;font-weight:700;background:rgba(245,158,11,.15);color:#f59e0b;border:1px solid rgba(245,158,11,.35);border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.role-badge{font-size:10px;font-weight:700;border:1px solid;border-radius:4px;padding:2px 6px;letter-spacing:.05em}
.logout-btn{font-size:12px;color:var(--muted);background:none;border:1px solid var(--brd);border-radius:6px;padding:4px 10px;cursor:pointer;font-family:inherit;transition:all .15s}
.logout-btn:hover{color:var(--red);border-color:#6e3535;background:rgba(248,81,73,.08)}
.ver-badge{font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace;color:var(--acc2);border-radius:4px;padding:1px 5px;letter-spacing:.04em;line-height:1.4;white-space:nowrap;align-self:center;margin-bottom:0;vertical-align:middle;position:relative;top:1px}

main{max-width:1200px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}

.bc{display:flex;align-items:center;flex-wrap:wrap;gap:4px;margin-bottom:20px;font-size:13px;color:var(--muted)}
.bc a{color:var(--acc);text-decoration:none;font-weight:500}
.bc a:hover{text-decoration:underline}
.bc span{color:var(--muted)}

.dz{border:1.5px dashed var(--brd);border-radius:var(--r);background:var(--sur);padding:28px 20px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;margin-bottom:20px}
.dz:hover,.dz.over{border-color:var(--acc);background:color-mix(in srgb,var(--acc) 6%,transparent)}
.dz-ic{display:flex;align-items:center;justify-content:center;margin-bottom:8px;transition:transform .2s}
.dz:hover .dz-ic,.dz.over .dz-ic{transform:translateY(-3px)}
.dz h3{font-size:14px;font-weight:600;margin-bottom:4px}
.dz p{font-size:12px;color:var(--muted)}
#fi{display:none}
/* ── Upload popup ─────────────────────────────────── */
#upload-popup{
  position:fixed;bottom:20px;right:20px;width:320px;
  background:var(--sur);border:1px solid var(--brd);border-radius:14px;
  box-shadow:0 8px 32px rgba(0,0,0,.5);z-index:9999;
  overflow:hidden;transition:box-shadow .2s;
}
#upload-popup:hover{box-shadow:0 12px 40px rgba(0,0,0,.6)}
.upo-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:10px 14px;background:rgba(255,255,255,.03);
  border-bottom:1px solid var(--brd);cursor:pointer;user-select:none;
  transition:background .12s;
}
.upo-header:hover{background:rgba(255,255,255,.06)}
.upo-collapsed #upo-chevron{transform:rotate(180deg)}
.upo-title{font-size:12px;font-weight:600;color:var(--txt);letter-spacing:.02em;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.upo-hbtns{display:flex;align-items:center;gap:4px;flex-shrink:0;margin-left:8px}
.upo-hbtn{
  background:none;border:none;cursor:pointer;color:var(--muted);
  padding:3px;border-radius:5px;display:flex;align-items:center;justify-content:center;
  transition:background .12s,color .12s;
}
.upo-hbtn:hover{background:rgba(255,255,255,.08);color:var(--txt)}
.pu-cancel{
  background:none;border:none;cursor:pointer;color:var(--muted);
  padding:2px;border-radius:4px;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:color .12s,background .12s;
}
.pu-cancel:hover{color:var(--red);background:rgba(248,81,73,.12)}
.pu-cancel.hidden{visibility:hidden;pointer-events:none}
.upo-body{transition:max-height .25s ease,opacity .2s;max-height:320px;opacity:1;overflow:hidden}
.upo-collapsed .upo-body{max-height:0;opacity:0}
.upo-overall{display:flex;align-items:center;gap:8px;padding:10px 14px 6px}
.upo-overall-bar{flex:1;height:3px;background:var(--brd);border-radius:99px;overflow:hidden}
.upo-overall-fill{height:100%;background:var(--acc);border-radius:99px;transition:width .2s;width:0}
.upo-overall-lbl{font-size:10px;color:var(--muted);white-space:nowrap;flex-shrink:0}
.upo-list{max-height:220px;overflow-y:auto;padding:0 14px 10px;scrollbar-width:thin;scrollbar-color:var(--brd) transparent}
.upo-list::-webkit-scrollbar{width:3px}
.upo-list::-webkit-scrollbar-thumb{background:var(--brd);border-radius:99px}
.pu-item{display:flex;align-items:center;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.pu-item:last-child{border-bottom:none}
.pu-name{font-size:11px;color:var(--txt);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.pu-pct{font-size:10px;color:var(--muted);width:30px;text-align:right;flex-shrink:0}
.pu-bar-wrap{width:52px;height:3px;background:var(--brd);border-radius:99px;overflow:hidden;flex-shrink:0}
.pu-bar-fill{height:100%;border-radius:99px;transition:width .2s;width:0;background:var(--acc)}
.pu-bar-fill.done{background:#3fb950}
.pu-bar-fill.err{background:var(--red)}
.pu-status{font-size:11px;width:14px;flex-shrink:0;text-align:center}

.tb{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;flex-wrap:wrap}
.tbl{display:flex;align-items:center;gap:8px}
.tbr{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tl{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.cnt{font-size:12px;color:var(--muted);background:var(--bg);border:1px solid var(--brd);border-radius:99px;padding:2px 10px}
.btn{display:inline-flex;align-items:center;gap:6px;font-family:inherit;font-size:13px;font-weight:500;padding:7px 14px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:background .15s,border-color .15s;text-decoration:none;white-space:nowrap}
.btn-accent{background:color-mix(in srgb,var(--acc) 12%,transparent);border-color:color-mix(in srgb,var(--acc) 40%,transparent);color:var(--acc);transition:background .18s,border-color .18s,color .18s,box-shadow .18s,transform .1s}
.btn-accent:hover{background:color-mix(in srgb,var(--acc) 22%,transparent);border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 20%,transparent);transform:translateY(-1px)}
.btn-accent:active{transform:translateY(0);box-shadow:none}
.btn:hover{background:color-mix(in srgb,var(--acc) 8%,var(--sur));border-color:var(--acc)}
.btnp{background:var(--acc2);border-color:var(--acc2);color:#e0e7ff}
.btnp:hover{background:#4338ca;border-color:#4338ca}
/* ── Mono theme — wyraźniejsze przyciski ── */
.theme-mono .btn{border-color:rgba(226,232,240,.25);background:rgba(226,232,240,.06);color:#e2e8f0}
.theme-mono .btn:hover{background:rgba(226,232,240,.12);border-color:rgba(226,232,240,.5)}
.theme-mono .btnp{background:#e2e8f0;border-color:#e2e8f0;color:#09090b}
.theme-mono .btnp:hover{background:#f1f5f9;border-color:#f1f5f9}
.theme-mono .btn-accent{background:rgba(226,232,240,.1);border-color:rgba(226,232,240,.35);color:#e2e8f0}
.theme-mono .btn-accent:hover{background:rgba(226,232,240,.18);border-color:#e2e8f0}
.theme-mono .stab-side:hover{background:rgba(226,232,240,.08)}
.theme-mono .stab-side.active{background:rgba(226,232,240,.13);color:#e2e8f0}
.theme-mono .sinput{border-color:rgba(226,232,240,.2)}
.theme-mono .sinput:focus{border-color:rgba(226,232,240,.6)}
.theme-mono .submit{background:#e2e8f0;color:#09090b}
.theme-mono .submit:hover{background:#f1f5f9}
/* ── Tryb jasny — globalne nadpisania ── */
.theme-light body{color:var(--txt)}
.theme-light header{background:var(--sur) !important;border-color:var(--brd)}
.theme-light .dz{background:var(--sur);border-color:var(--brd)}
.theme-light .card{background:var(--sur)}
.theme-light .btn{background:var(--sur);border-color:var(--brd);color:var(--txt)}
.theme-light .btn:hover{background:color-mix(in srgb,var(--acc) 8%,var(--sur));border-color:var(--acc)}
.theme-light .btnp{background:var(--acc2);color:#fff;border-color:var(--acc2)}
.theme-light .sort-btn{background:var(--sur);border-color:var(--brd);color:var(--muted)}
.theme-light .sort-btn:hover,.theme-light .sort-btn.active{background:color-mix(in srgb,var(--acc) 10%,var(--sur));color:var(--acc);border-color:var(--acc)}
.theme-light .modal{background:var(--sur)}
.theme-light .sinput,.theme-light input{background:var(--bg);border-color:var(--brd);color:var(--txt)}
.theme-light .sinput:focus,.theme-light input:focus{border-color:var(--acc)}
.theme-light .mb-settings-inner{background:var(--sur)}
.theme-light .stab-side{color:var(--muted)}
.theme-light .stab-side:hover{background:color-mix(in srgb,var(--acc) 8%,transparent);color:var(--txt)}
.theme-light .stab-side.active{background:color-mix(in srgb,var(--acc) 12%,transparent);color:var(--acc)}
.theme-light .card-info .card-name{color:var(--txt)}
.theme-light .card-meta{color:var(--muted)}
.theme-light .submit{background:var(--acc2);color:#fff}
.theme-light #upload-popup{background:var(--sur);border-color:var(--brd)}
/* Przełącznik trybu */
.mode-switch{display:flex;gap:4px;background:var(--bg);border:1px solid var(--brd);border-radius:8px;padding:3px;margin-bottom:16px}
.mode-btn{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;font-family:inherit;font-size:12px;font-weight:500;padding:6px 8px;border-radius:6px;border:none;background:none;color:var(--muted);cursor:pointer;transition:all .15s}
.mode-btn:hover{color:var(--txt);background:var(--sur)}
.mode-btn.active{background:var(--sur);color:var(--txt);box-shadow:0 1px 4px rgba(0,0,0,.2)}
.sort-btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 10px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--muted);transition:all .15s;white-space:nowrap}
.sort-btn:hover,.sort-btn.active{color:var(--txt);border-color:var(--acc);background:color-mix(in srgb,var(--acc) 8%,var(--sur))}
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
.card.selected{border-color:var(--acc);box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 40%,transparent)}
.card.selected .card-cb{background:var(--acc);border-color:var(--acc)}
.multi-bar{position:fixed;bottom:20px;left:50%;transform:translateX(-50%) translateY(80px);background:#1a2035;border:1px solid #2d3a52;border-radius:14px;padding:10px 18px;display:flex;align-items:center;gap:12px;box-shadow:0 8px 32px rgba(0,0,0,.6);z-index:300;transition:transform .25s cubic-bezier(.34,1.56,.64,1);white-space:nowrap}
.multi-bar.show{transform:translateX(-50%) translateY(0)}
.multi-cnt{font-size:13px;font-weight:600;color:var(--txt);min-width:80px}
.multi-btn{font-family:inherit;font-size:12px;font-weight:500;padding:6px 14px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s;display:flex;align-items:center;gap:6px}
.multi-btn:hover{background:color-mix(in srgb,var(--acc) 8%,var(--sur));border-color:var(--acc)}
.multi-btn-red{border-color:#6e3535;color:var(--red)}
.multi-btn-red:hover{background:rgba(248,81,73,.1)}
.multi-btn-acc{border-color:var(--acc2);color:#c7d2fe;background:rgba(79,70,229,.15)}
.multi-btn-acc:hover{background:rgba(79,70,229,.3)}
.thumb{height:110px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.thumb-folder{background:rgba(227,179,65,.08);color:var(--folder)}
.thumb-img{background:var(--bg)}
.thumb-img img{width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
.thumb-img img.loaded{opacity:1}
.thumb-file{background:color-mix(in srgb,var(--acc) 7%,transparent);color:var(--acc)}
.thumb-audio{background:color-mix(in srgb,var(--acc) 7%,transparent);color:var(--acc);position:relative;overflow:hidden}
.thumb-audio-inner{width:100%;height:100%;display:flex;align-items:center;justify-content:center;position:relative}
.thumb-audio-cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
.thumb-audio-cover.loaded{opacity:1}
.thumb-video{background:var(--bg);position:relative;overflow:hidden}
.thumb-video-inner{width:100%;height:100%;display:flex;align-items:center;justify-content:center;position:relative}
.thumb-video-cover{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .3s}
.thumb-video-cover.loaded{opacity:1}
.thumb-video-play{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;opacity:0;transition:opacity .2s}
.thumb-video-cover.loaded~.thumb-video-play,.card:hover .thumb-video-play{opacity:1}
.thumb-audio.has-cover .thumb-audio-inner svg{display:none}
.card-info{padding:10px 10px 11px;border-top:1px solid var(--brd)}
.card-name{display:block;font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px}
.card-meta{font-size:11px;color:var(--muted)}
.card-actions{position:absolute;top:7px;right:7px;display:flex;gap:4px;opacity:0;transition:opacity .15s}
.card:hover .card-actions{opacity:1}
.act{width:28px;height:28px;background:rgba(10,12,20,.9);border:1px solid var(--brd);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--txt);text-decoration:none;transition:background .15s}
.act:hover{background:var(--brd)}
.act-del:hover{color:var(--red);border-color:#6e3535;background:rgba(248,81,73,.1)}
.share-ttl-btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 12px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--muted);transition:all .15s}
.share-ttl-btn:hover{color:var(--txt);border-color:#2d3a52}
.share-ttl-btn.active{background:color-mix(in srgb,var(--acc) 20%,transparent);border-color:var(--acc2);color:var(--acc)}

.card.drag-over{border-color:var(--acc)!important;box-shadow:0 0 0 2px color-mix(in srgb,var(--acc) 50%,transparent),0 8px 32px color-mix(in srgb,var(--acc) 20%,transparent)!important;background:color-mix(in srgb,var(--acc) 10%,transparent)!important}
.card.drag-over .thumb{filter:brightness(1.15)}
.card.dragging-sel{opacity:.28;transform:scale(.95) rotate(-1deg);transition:opacity .2s,transform .2s;filter:saturate(.5)}
#drag-ghost{pointer-events:none}
.dg-stack{position:relative;width:160px;height:52px}
.dg-card{position:absolute;border-radius:10px;height:44px;display:flex;align-items:center;padding:0 12px;gap:8px;font-size:12px;font-weight:600;backdrop-filter:blur(12px)}
.dg-card1{background:rgba(26,32,53,.97);border:1.5px solid #4f46e5;box-shadow:0 8px 32px rgba(79,70,229,.55),0 2px 8px rgba(0,0,0,.4);color:#c7d2fe;top:4px;left:0;width:156px;z-index:3}
.dg-card2{background:rgba(30,38,64,.9);border:1.5px solid #3730a3;top:0px;left:8px;width:148px;z-index:2;transform:rotate(2.5deg);opacity:.85}
.dg-card3{background:rgba(35,44,75,.85);border:1.5px solid #312e81;top:-3px;left:14px;width:140px;z-index:1;transform:rotate(5deg);opacity:.65}
.dg-badge{background:linear-gradient(135deg,var(--acc2),var(--acc));border-radius:99px;min-width:20px;height:20px;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff;padding:0 5px;flex-shrink:0}
.dg-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:110px}

.empty-state{grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--muted)}
.empty-state p{font-size:14px;font-weight:500;color:var(--txt);margin:12px 0 4px}
.empty-state small{font-size:12px}

.mb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(6px);z-index:200;align-items:center;justify-content:center}
.mb.show{display:flex}
.modal{background:var(--sur);border:1px solid var(--brd);border-radius:14px;padding:24px;width:360px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,.6)}
@media(max-width:520px){
  #settings-body{flex-direction:column}
  #settings-sidebar{width:100%!important;flex-direction:row!important;flex-wrap:wrap!important;border-right:none!important;border-bottom:1px solid var(--brd)!important;padding:8px!important;gap:4px!important;flex-shrink:0!important;overflow-x:auto}
  #settings-sidebar .stab-side{padding:8px 10px!important;font-size:13px!important;flex:1;min-width:fit-content;justify-content:center;white-space:nowrap}
  #settings-sidebar .stab-side svg{display:none}
  #settings-sidebar>div[style*="flex:1"]{display:none!important}
  #settings-sidebar>div[style*="height:1px"]{display:none!important}
}
.modal h3{font-size:15px;font-weight:600;margin-bottom:14px}
.modal input{width:100%;padding:9px 12px;border:1px solid var(--brd);border-radius:8px;font-family:inherit;font-size:14px;color:var(--txt);background:var(--bg);outline:none;margin-bottom:14px;transition:border-color .15s}
.modal input:focus{border-color:var(--acc)}
.mbtns{display:flex;gap:8px;justify-content:flex-end}
.rename-row{display:flex;align-items:center;border:1px solid var(--brd);border-radius:8px;background:var(--bg);margin-bottom:14px;overflow:hidden;transition:border-color .15s}
.rename-row:focus-within{border-color:var(--acc)}
.rename-row input{flex:1;padding:9px 12px;border:none;font-family:inherit;font-size:14px;color:var(--txt);background:transparent;outline:none}
.rename-ext{padding:9px 12px 9px 0;font-size:14px;color:var(--muted);white-space:nowrap;user-select:none}

.theme-btn{font-family:inherit;background:var(--sur);border:2px solid var(--brd);border-radius:12px;padding:8px 8px 10px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:8px;transition:border-color .15s,box-shadow .15s,transform .1s;color:var(--muted);font-size:12px;font-weight:500;min-width:0}
.theme-btn:hover{border-color:var(--acc);transform:scale(1.02);color:var(--txt)}
.theme-btn.active{border-color:var(--acc);color:var(--txt);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 35%,transparent);background:color-mix(in srgb,var(--acc) 6%,transparent)}
.theme-preview{width:100%;height:44px;border-radius:8px}
@media(max-width:480px){.theme-preview{height:38px}}
.stab-side{font-family:inherit;font-size:14px;font-weight:500;padding:11px 14px;background:none;border:none;border-radius:9px;color:var(--muted);cursor:pointer;transition:background .15s,color .15s;display:flex;align-items:center;gap:10px;width:100%;text-align:left;-webkit-tap-highlight-color:transparent}
.stab-side:hover{background:color-mix(in srgb,var(--acc) 8%,transparent);color:var(--txt)}
.stab-side.active{background:color-mix(in srgb,var(--acc) 13%,transparent);color:var(--txt)}
.stab-side-red{color:#f87171!important}
.stab-side-red:hover{background:rgba(248,81,73,.08)!important;color:var(--red)!important}
.stab-side-red.active{background:rgba(248,81,73,.13)!important;color:var(--red)!important}
.slabel{display:block;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.sinput{width:100%;padding:9px 12px;border:1px solid var(--brd);border-radius:8px;font-family:inherit;font-size:14px;color:var(--txt);background:var(--bg);outline:none;margin-bottom:14px;transition:border-color .15s}
.sinput:focus{border-color:var(--acc)}
.serr{font-size:12px;color:var(--red);margin-bottom:10px;display:none}
.toast{position:fixed;bottom:24px;right:20px;left:20px;max-width:340px;margin:0 auto;background:var(--brd);border:1px solid var(--brd);color:var(--txt);border-radius:10px;padding:12px 16px;font-size:13px;font-weight:500;z-index:300;pointer-events:none;transform:translateY(80px);opacity:0;transition:all .3s;display:flex;align-items:center;gap:8px}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{background:rgba(248,81,73,.15);border-color:#6e3535;color:var(--red)}

.term-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);z-index:399;opacity:0;pointer-events:none;transition:opacity .25s ease}
.term-overlay.open{opacity:1;pointer-events:all}
.term-fab{display:none}
.term-fab-btn{display:none!important}
.term-header-btn{font-family:inherit;font-size:12px;font-weight:500;padding:6px 12px;border-radius:8px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s;display:flex;align-items:center;gap:6px}
.term-header-btn:hover{background:color-mix(in srgb,var(--acc) 10%,var(--sur));border-color:var(--acc2);color:var(--acc)}
.term-header-btn.open{background:color-mix(in srgb,var(--acc) 20%,transparent);border-color:var(--acc2);color:var(--acc)}
.term-panel{position:fixed;bottom:20px;right:20px;width:480px;max-width:calc(100vw - 40px);height:380px;background:var(--bg);border:1px solid var(--brd);border-radius:12px;box-shadow:0 16px 64px rgba(0,0,0,.7);z-index:400;display:none;flex-direction:column;overflow:hidden;transform:translateY(20px) scale(.97);opacity:0;pointer-events:none;transition:transform .2s cubic-bezier(.34,1.56,.64,1),opacity .2s}
.term-panel.open{transform:translateY(0) scale(1);opacity:1;pointer-events:all}
.term-slider-header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--sur);border-bottom:1px solid var(--brd);flex-shrink:0}
.term-slider-close{background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;padding:2px 6px;border-radius:4px;line-height:1;transition:color .15s}
.term-slider-close:hover{color:var(--red)}
.term-title{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;display:flex;align-items:center;gap:7px}
.term-dot{width:7px;height:7px;border-radius:50%}
.term-out{flex:1;overflow-y:auto;padding:12px 16px;font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;color:#7d8590;scrollbar-width:none}
.term-out::-webkit-scrollbar{display:none}
.term-out .tline{padding:1px 0;border-left:2px solid transparent;padding-left:8px}
.term-out .tline.ok{color:#3fb950;border-left-color:#3fb950}
.term-out .tline.err{color:#f85149;border-left-color:#f85149}
.term-out .tline.cmd{color:var(--acc);border-left-color:var(--acc)}
.term-bar{display:flex;align-items:center;gap:8px;padding:10px 16px;border-top:1px solid var(--brd);background:var(--bg);flex-shrink:0}
.term-prefix{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--acc)}
.term-input{flex:1;font-family:'JetBrains Mono',monospace;font-size:13px;background:transparent;border:none;outline:none;color:var(--txt);caret-color:var(--acc)}
.term-input::placeholder{color:#2d3a52}
.term-send{font-family:inherit;font-size:12px;font-weight:500;padding:4px 10px;border-radius:6px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s}
.term-send:hover{background:var(--acc2);border-color:var(--acc2);color:#e0e7ff}

/* ── HAMBURGER MENU ── */
.user-mini-badge{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:500;color:var(--txt);white-space:nowrap}
.user-mini-name{font-size:13px;font-weight:600;color:var(--txt)}
@media(max-width:600px){.user-mini-badge{display:none!important}}
.ham-btn{display:none;flex-direction:column;justify-content:center;align-items:center;width:40px;height:40px;gap:5px;background:none;border:1px solid var(--brd);border-radius:8px;cursor:pointer;padding:0;transition:background .15s,border-color .15s;flex-shrink:0;-webkit-tap-highlight-color:transparent;touch-action:manipulation;user-select:none}
.ham-btn:hover{background:color-mix(in srgb,var(--acc) 8%,var(--sur));border-color:var(--brd)}
.ham-btn span{display:block;width:16px;height:2px;background:var(--txt);border-radius:2px;transition:transform .25s,opacity .25s,width .25s}
.ham-btn.open span:nth-child(1){transform:translateY(7px) rotate(45deg)}
.ham-btn.open span:nth-child(2){opacity:0;width:0}
.ham-btn.open span:nth-child(3){transform:translateY(-7px) rotate(-45deg)}

.mob-menu{position:fixed;top:0;left:0;right:0;bottom:0;z-index:400;display:flex;visibility:hidden;pointer-events:none}
.mob-menu.open{visibility:visible;pointer-events:all}
.mob-menu-overlay{position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.55);backdrop-filter:blur(4px);z-index:1;-webkit-tap-highlight-color:transparent;opacity:0;transition:opacity .3s ease}
.mob-menu.open .mob-menu-overlay{opacity:1}
.mob-menu-panel{position:relative;z-index:2;margin-left:auto;width:min(280px,85vw);height:100%;background:var(--bg);border-left:1px solid var(--brd);box-shadow:-8px 0 40px rgba(0,0,0,.6);transform:translateX(calc(100% + 50px));transition:transform .32s cubic-bezier(.34,1.1,.64,1);display:flex;flex-direction:column;padding:0;flex-shrink:0;overflow:hidden}
.mob-menu.open .mob-menu-panel{transform:translateX(0)}
.mob-menu-head{display:flex;flex-direction:column;border-bottom:1px solid var(--brd);user-select:none}
.mob-menu-user{display:flex;align-items:center;gap:12px}
.mob-menu-user-info{display:flex;flex-direction:column;gap:5px}
.mob-menu-close{width:34px;height:34px;background:none;border:1px solid var(--brd);border-radius:7px;cursor:pointer;color:var(--txt);display:flex;align-items:center;justify-content:center;font-size:16px;transition:background .15s;-webkit-tap-highlight-color:transparent;touch-action:manipulation;flex-shrink:0}
.mob-menu-close:hover{background:var(--brd)}
.mob-menu-body{flex:1;padding:0;overflow-y:auto;-webkit-overflow-scrolling:touch}
.mob-menu-item{display:flex;align-items:center;justify-content:center;gap:10px;padding:13px 16px;font-size:15px;font-weight:500;color:var(--txt);text-decoration:none;cursor:pointer;transition:background .15s;border:none;background:none;width:100%;font-family:inherit;text-align:center;user-select:none;-webkit-tap-highlight-color:transparent;touch-action:manipulation;-webkit-user-select:none}
.mob-menu-item:active{background:color-mix(in srgb,var(--acc) 15%,transparent)}
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
  .ham-btn{display:flex!important}
  .hs{display:none!important}
}
@media(max-width:480px){
  .grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
}
.sbar{display:flex;align-items:center;gap:0;background:var(--bg);border-bottom:1px solid var(--brd);padding:0 18px;height:32px;font-size:11px;font-family:'JetBrains Mono',monospace;overflow-x:auto;flex-wrap:nowrap;scrollbar-width:none}
.sbar::-webkit-scrollbar{display:none}
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
.sbar-lbl{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.04em}
.sbar-val{color:var(--txt);font-weight:600}
.sbar-val.warn{color:#f59e0b}
.sbar-val.over{color:#f85149}
.sbar-dot{width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0}
.sbar-dot.warn{background:#f59e0b}
.sbar-dot.over{background:#f85149}
.mob-stats-block{margin:16px 16px 12px;padding:0;text-align:center}
.mob-stats-block .msb-title{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:10px;font-weight:600;text-align:center}
.mob-stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.msb-row{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:8px 6px;background:var(--bg);border-radius:9px;border:1px solid var(--brd)}
.msb-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.msb-val{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:var(--txt)}
.msb-val.warn{color:#f59e0b}
.msb-val.over{color:#f85149}
/* Light mode — karty statystyk */
.theme-light .msb-row{background:var(--sur);border-color:var(--brd)}
.theme-light .sbar{background:var(--sur)}
/* Light mode — dodatkowe elementy */
.theme-light .multi-bar{background:var(--sur);border-color:var(--brd)}
.theme-light .multi-btn{background:var(--sur);border-color:var(--brd);color:var(--txt)}
.theme-light .cnt{background:var(--sur);border-color:var(--brd);color:var(--muted)}
.theme-light .modal{background:var(--sur);border-color:var(--brd)}
.theme-light .modal input{background:var(--bg)}
.theme-light .toast{background:var(--sur);color:var(--txt)}
.theme-light .card{background:var(--sur) !important}
.theme-light .dz{background:var(--sur) !important}
.theme-light .term-panel{background:var(--sur)}
.theme-light .empty-state{color:var(--muted)}
.theme-light #upload-popup .upo-header{background:rgba(0,0,0,.04)}
.theme-light .pu-name{color:var(--txt)}
.theme-light .search-inp{background:var(--bg);color:var(--txt);border-color:var(--brd)}
.theme-light .mob-menu-panel{background:var(--sur)}
.theme-light .mob-menu-item{color:var(--txt)}
.theme-light .mob-menu-item:hover{background:color-mix(in srgb,var(--acc) 8%,transparent)}
@media(max-width:600px){
  .sbar{height:auto;padding:6px 14px;flex-wrap:wrap;gap:4px 0}
  .sbar-item{padding:2px 10px;border-right:1px solid var(--brd)}
}
</style>
</head>
<body>
<header%%ADMIN_HEADER_ATTR%%>
  <div class="hi">
    <a class="logo" href="/?path="><svg viewBox="0 0 38 22" width="38" height="22" fill="none" xmlns="http://www.w3.org/2000/svg" style="position:relative;top:3px;flex-shrink:0"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/></svg><span class="brand">%%HEADER_TITLE%%</span><span class="ver-badge">%%APP_VERSION%%</span></a>
    <div class="hs">
      <div class="st">Pliki: <b>%%FILE_COUNT%%</b></div>
      <div class="st">Zajęte: <b>%%TOTAL_SIZE%%</b></div>
      <div class="user-badge">
        <div class="avatar%%ADMIN_AVATAR%%">%%USER_INITIAL%%</div>
        <span>%%USERNAME%%</span>
        %%ADMIN_BADGE%%
      </div>
      %%TERMINAL_BTN%%
    </div>
    <!-- Hamburger button + desktop user badge -->
    <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
      <div class="user-mini-badge">
        <div class="avatar%%ADMIN_AVATAR%%" style="width:26px;height:26px;font-size:11px">%%USER_INITIAL%%</div>
        <span class="user-mini-name">%%USERNAME%%</span>
        %%ADMIN_BADGE%%
      </div>
      <button class="ham-btn" id="ham-btn" aria-label="Menu">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
</header>

<!-- Mobile slide-in menu -->
<div class="mob-menu" id="mob-menu">
  <div class="mob-menu-overlay" id="mob-overlay" onclick="closeMobMenu()"></div>
  <div class="mob-menu-panel">
    <div class="mob-menu-head" style="flex-direction:column;align-items:stretch;gap:0;padding:0">
      <!-- Top bar z X -->
      <div style="display:flex;align-items:center;justify-content:flex-end;padding:10px 14px 6px">
        <button class="mob-menu-close" onclick="closeMobMenu()">&#x2715;</button>
      </div>
      <!-- Konto -->
      <div style="display:flex;align-items:center;gap:14px;padding:4px 16px 16px">
        <div class="avatar%%ADMIN_AVATAR%%" style="width:46px;height:46px;font-size:18px;flex-shrink:0">%%USER_INITIAL%%</div>
        <div style="min-width:0">
          <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:4px">
            <span style="font-size:15px;font-weight:700;color:var(--txt);line-height:1">%%USERNAME%%</span>
            %%ADMIN_BADGE%%
          </div>
          <div style="font-size:11px;color:var(--muted)">Pliki: <b style="color:var(--txt)">%%FILE_COUNT%%</b> &nbsp;·&nbsp; Zajęte: <b style="color:var(--txt)">%%TOTAL_SIZE%%</b></div>
        </div>
      </div>
    </div>
    <div class="mob-menu-sep"></div>
    <div class="mob-menu-body">
      <button class="mob-menu-item" onclick="closeMobMenu();openSettings()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>
        Ustawienia konta
      </button>
      <div class="mob-menu-sep"></div>
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
            <stop offset="0%" stop-color="#e2e8f0" id="upg-stop1"/>
            <stop offset="100%" stop-color="#94a3b8" id="upg-stop2"/>
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

<!-- ── Upload Popup ─────────────────────────────────── -->
<div id="upload-popup" style="display:none">
  <div class="upo-header" onclick="upoToggle()" title="Zwiń / rozwiń">
    <span class="upo-title" id="upo-title">Przesyłanie...</span>
    <div class="upo-hbtns">
      <svg id="upo-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13" style="flex-shrink:0;transition:transform .2s;color:var(--muted)"><polyline points="18 15 12 9 6 15"/></svg>
      <button class="upo-hbtn" onclick="event.stopPropagation();upoClose()" title="Zamknij" id="upo-close-btn" style="display:none">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="13" height="13"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  </div>
  <div class="upo-body" id="upo-body">
    <div class="upo-overall">
      <div class="upo-overall-bar"><div class="upo-overall-fill" id="pf"></div></div>
      <span class="upo-overall-lbl" id="pl"></span>
    </div>
    <div id="pu-list" class="upo-list"></div>
  </div>
</div>

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

<div class="mb" id="mb-settings" style="display:none" onclick="if(event.target===this)closeSettings()">
  <div class="modal" style="max-width:540px;width:96vw;max-height:90vh;display:flex;flex-direction:column;padding:0;overflow:hidden">
    <div style="padding:16px 20px;border-bottom:1px solid var(--brd);display:flex;align-items:center;gap:12px;flex-shrink:0">
      <div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--acc2),var(--acc));display:flex;align-items:center;justify-content:center;flex-shrink:0">
        <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" width="18" height="18"><circle cx="12" cy="8" r="4"/><path d="M6 20v-2a6 6 0 0112 0v2"/></svg>
      </div>
      <div style="flex:1">
        <div style="font-size:15px;font-weight:600;color:var(--txt)">Ustawienia konta</div>
        <div style="font-size:12px;color:var(--muted)" id="s-header-user"></div>
      </div>
      <button onclick="closeSettings()" style="background:none;border:1px solid var(--brd);border-radius:7px;color:var(--muted);font-size:16px;cursor:pointer;width:32px;height:32px;display:flex;align-items:center;justify-content:center">&times;</button>
    </div>
    <div style="display:flex;flex:1;overflow:hidden;min-height:0" id="settings-body">
      <div style="width:160px;flex-shrink:0;border-right:1px solid var(--brd);padding:10px 8px;display:flex;flex-direction:column;gap:2px;background:var(--bg)" id="settings-sidebar">
        <button class="stab-side active" id="stab-password" onclick="switchSTab('password')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          Zmień hasło
        </button>
        <button class="stab-side" id="stab-username" onclick="switchSTab('username')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Zmień nazwę
        </button>
        <button class="stab-side" id="stab-2fa" onclick="switchSTab('2fa')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          2FA
        </button>
        <button class="stab-side" id="stab-theme" onclick="switchSTab('theme')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 010 20"/><path d="M12 2C6.5 7 6.5 17 12 22"/><path d="M2 12h20"/></svg>
          Motyw
        </button>
        <div style="flex:1;min-height:12px"></div>
        <div style="height:1px;background:var(--brd);margin:4px 0"></div>
        <button class="stab-side stab-side-red" id="stab-danger" onclick="switchSTab('danger')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          Wyloguj
        </button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:22px 22px 20px">
        <div id="stab-content-password">
          <div style="font-size:14px;font-weight:600;color:var(--txt);margin-bottom:4px">Zmień hasło</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:18px">Po zmianie hasła inne aktywne sesje zostaną wylogowane.</div>
          <label class="slabel">Aktualne hasło</label>
          <input type="password" id="s-old-pw" class="sinput" placeholder="••••••••">
          <label class="slabel">Nowe hasło</label>
          <input type="password" id="s-new-pw" class="sinput" placeholder="min. 4 znaki">
          <label class="slabel">Powtórz nowe hasło</label>
          <input type="password" id="s-new-pw2" class="sinput" placeholder="••••••••">
          <div class="serr" id="s-pw-err"></div>
          <button class="btn btnp" style="width:100%;gap:8px" onclick="changePassword()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v14a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
            Zmień hasło
          </button>
        </div>
        <div id="stab-content-username" style="display:none">
          <div style="font-size:14px;font-weight:600;color:var(--txt);margin-bottom:4px">Zmień nazwę użytkownika</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:18px">Folder z plikami zostanie przeniesiony automatycznie. Zostaniesz przelogowany.</div>
          <label class="slabel">Nowa nazwa</label>
          <input type="text" id="s-new-name" class="sinput" placeholder="nowa_nazwa" maxlength="32">
          <label class="slabel">Potwierdź hasłem</label>
          <input type="password" id="s-name-pw" class="sinput" placeholder="••••••••">
          <div class="serr" id="s-name-err"></div>
          <button class="btn btnp" style="width:100%;gap:8px" onclick="changeUsername()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            Zmień nazwę
          </button>
        </div>
        <div id="stab-content-2fa" style="display:none">
          <div style="font-size:14px;font-weight:600;color:var(--txt);margin-bottom:4px">Uwierzytelnianie dwuskładnikowe</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:18px">Zabezpiecz konto jednorazowymi kodami z Google Authenticator.</div>
          <div id="s-2fa-inner"><div style="font-size:13px;color:var(--muted)">Ładowanie...</div></div>
        </div>
        <div id="stab-content-theme" style="display:none">
          <div style="font-size:14px;font-weight:600;color:var(--txt);margin-bottom:4px">Motyw kolorystyczny</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:14px">Wybierz kolor akcentu i tryb interfejsu.</div>
          <div class="mode-switch">
            <button class="mode-btn active" data-mode="dark" onclick="setMode('dark')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
              Ciemny
            </button>
            <button class="mode-btn" data-mode="light" onclick="setMode('light')">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
              Jasny
            </button>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:10px" id="theme-grid">
            <button class="theme-btn" data-name="Niebieski" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#4f46e5,#818cf8)"></div>
              <span>Niebieski</span>
            </button>
            <button class="theme-btn" data-name="Zielony" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#059669,#34d399)"></div>
              <span>Zielony</span>
            </button>
            <button class="theme-btn" data-name="Czerwony" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#dc2626,#f87171)"></div>
              <span>Czerwony</span>
            </button>
            <button class="theme-btn" data-name="Fioletowy" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#9333ea,#c084fc)"></div>
              <span>Fioletowy</span>
            </button>
            <button class="theme-btn" data-name="Mono" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#18181b,#e2e8f0)"></div>
              <span>Mono</span>
            </button>
            <button class="theme-btn" data-name="Różowy" onclick="applyTheme(this)">
              <div class="theme-preview" style="background:linear-gradient(135deg,#db2777,#f472b6)"></div>
              <span>Różowy</span>
            </button>
          </div>
        </div>
        <div id="stab-content-danger" style="display:none">
          <div style="font-size:14px;font-weight:600;color:var(--txt);margin-bottom:4px">Wyloguj</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:12px">Zakończ bieżącą sesję.</div>
          <form method="POST" action="/logout" style="margin:0 0 28px">
            <button class="btn btn-accent" style="width:100%;justify-content:center;">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
              Wyloguj
            </button>
          </form>
          <div style="height:1px;background:var(--brd);margin-bottom:20px"></div>
          <div style="font-size:14px;font-weight:600;color:var(--red);margin-bottom:4px">Usuń konto</div>
          <div style="font-size:12px;color:var(--muted);margin-bottom:16px">Ta operacja jest nieodwracalna.</div>
          <div style="background:rgba(248,81,73,.07);border:1px solid rgba(248,81,73,.25);border-radius:10px;padding:12px 14px;margin-bottom:16px;font-size:12px;color:var(--muted)">
            ⚠ Twoje konto zostanie trwale usunięte. Możesz wybrać czy usunąć też pliki.
          </div>
          <label class="slabel">Potwierdź hasłem</label>
          <input type="password" id="s-del-pw" class="sinput" placeholder="••••••••">
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--txt);margin-bottom:18px;cursor:pointer">
            <input type="checkbox" id="s-del-files" style="width:auto;margin:0;accent-color:var(--red)"> Usuń też wszystkie moje pliki
          </label>
          <div class="serr" id="s-del-err"></div>
          <button class="btn" style="width:100%;border-color:#7f2a2a;color:var(--red);background:rgba(248,81,73,.08);gap:8px" onclick="deleteAccount()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/></svg>
            Usuń konto na zawsze
          </button>
        </div>
      </div>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const CUR="%%CURRENT_PATH%%";
let SORT_BY="%%SORT_BY%%", SORT_DIR="%%SORT_DIR%%";


// ── MOTYW ────────────────────────────────────────────
function hexToRgb(hex){
  const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  return r+','+g+','+b;
}
const THEMES = {
  'Niebieski':    {
    dark: {acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},
    light:{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},
  },
  'Zielony':      {
    dark: {acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},
    light:{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},
  },
  'Czerwony':     {
    dark: {acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},
    light:{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},
  },
  'Fioletowy':    {
    dark: {acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},
    light:{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},
  },
  'Mono':          {
    dark: {acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},
    light:{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},
  },
  'Różowy':       {
    dark: {acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'},
    light:{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'},
  },
};

let _currentMode = (function(){try{var s=JSON.parse(localStorage.getItem('sc_theme')||'null');return(s&&s.mode)||'dark';}catch(e){return'dark';}}());
let _currentThemeName = (function(){try{var s=JSON.parse(localStorage.getItem('sc_theme')||'null');return(s&&s.name)||'Mono';}catch(e){return'Mono';}}());

function _applyVars(t, name){
  const r=document.documentElement;
  r.style.setProperty('--acc',   t.acc);
  r.style.setProperty('--acc2',  t.acc2);
  r.style.setProperty('--acc-rgb', hexToRgb(t.acc));
  r.style.setProperty('--bg',    t.bg);
  r.style.setProperty('--sur',   t.sur);
  r.style.setProperty('--brd',   t.brd);
  r.style.setProperty('--txt',   t.txt||'#e6edf3');
  r.style.setProperty('--muted', t.muted||'#7d8590');
  r.style.setProperty('--gr1',   t.gr1);
  r.style.setProperty('--gr2',   t.gr2);
  r.style.setProperty('--gr3',   t.gr3);
  r.style.setProperty('--gr4',   t.gr4);
  r.classList.toggle('theme-mono', name==='Mono');
  r.classList.toggle('theme-light', _currentMode==='light');
  updateSvgColors(t.acc, t.acc2);
}

function applyTheme(btn){
  const name=btn.dataset.name;
  _currentThemeName=name;
  const theme=THEMES[name]||THEMES['Mono'];
  const t=theme[_currentMode]||theme.dark;
  _applyVars(t, name);
  localStorage.setItem('sc_theme', JSON.stringify({name, mode:_currentMode}));
  document.querySelectorAll('.theme-btn').forEach(b=>b.classList.toggle('active', b.dataset.name===name));
  toast('✓ Motyw: '+name);
}

function setMode(mode){
  _currentMode=mode;
  const theme=THEMES[_currentThemeName]||THEMES['Mono'];
  const t=theme[mode]||theme.dark;
  _applyVars(t, _currentThemeName);
  localStorage.setItem('sc_theme', JSON.stringify({name:_currentThemeName, mode}));
  // Zaktualizuj przyciski trybu
  document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active', b.dataset.mode===mode));
}
function updateSvgColors(acc, acc2){
  const s1=document.getElementById('upg-stop1');
  const s2=document.getElementById('upg-stop2');
  if(s1)s1.setAttribute('stop-color',acc);
  if(s2)s2.setAttribute('stop-color',acc2);
}
function loadTheme(){
  try{
    const saved=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!saved) return;
    _currentMode = saved.mode||'dark';
    _currentThemeName = saved.name||'Mono';
    const theme=THEMES[_currentThemeName]||THEMES['Mono'];
    const t=theme[_currentMode]||theme.dark;
    _applyVars(t, _currentThemeName);
    document.querySelectorAll('.theme-btn').forEach(b=>{
      b.classList.toggle('active', b.dataset.name===_currentThemeName);
    });
    document.querySelectorAll('.mode-btn').forEach(b=>{
      b.classList.toggle('active', b.dataset.mode===_currentMode);
    });
  }catch(e){}
}
loadTheme();
// ─────────────────────────────────────────────────────
// ── USTAWIENIA KONTA ─────────────────────────────────
function openSettings(tab){
  document.getElementById('mb-settings').style.display='flex';
  // Ustaw nazwę usera w headerze modala
  const uname=document.querySelector('.user-mini-name');
  const hdr=document.getElementById('s-header-user');
  if(uname&&hdr)hdr.textContent=uname.textContent;
  switchSTab(tab||'password');
}
function closeSettings(){
  document.getElementById('mb-settings').style.display='none';
  ['s-old-pw','s-new-pw','s-new-pw2','s-new-name','s-name-pw','s-del-pw'].forEach(id=>{
    const el=document.getElementById(id);if(el)el.value='';
  });
  ['s-pw-err','s-name-err','s-del-err'].forEach(id=>{
    const el=document.getElementById(id);if(el){el.style.display='none';el.textContent='';}
  });
}
function switchSTab(tab){
  ['password','username','2fa','theme','danger'].forEach(t=>{
    document.getElementById('stab-'+t).classList.toggle('active',t===tab);
    document.getElementById('stab-content-'+t).style.display=t===tab?'block':'none';
  });
  if(tab==='2fa') load2FATab();
  if(tab==='theme') loadTheme();
}
async function load2FATab(){
  const el=document.getElementById('s-2fa-inner');
  el.innerHTML='<div style="font-size:13px;color:var(--muted)">Ładowanie...</div>';
  try{
    const r=await fetch('/2fa/setup');
    const d=await r.json();
    if(!d.ok){el.innerHTML='<div style="color:var(--red)">Błąd ładowania</div>';return;}
    if(d.enabled){
      el.innerHTML=`
        <p style="font-size:13px;color:#3fb950;margin-bottom:16px">✓ 2FA jest <b>włączone</b> na Twoim koncie.</p>
        <label class="slabel">Podaj hasło aby wyłączyć 2FA</label>
        <input type="password" id="s-2fa-dis-pw" class="sinput" placeholder="••••••••">
        <div class="serr" id="s-2fa-dis-err"></div>
        <button class="btn" style="width:100%;border-color:#6e3535;color:var(--red)" onclick="disable2FASettings()">Wyłącz 2FA</button>`;
    } else {
      _2fa_secret=d.secret;
      const qrUrl='https://api.qrserver.com/v1/create-qr-code/?size=160x160&data='+encodeURIComponent(d.uri);
      el.innerHTML=`
        <p style="font-size:13px;color:var(--muted);margin-bottom:12px">Zeskanuj kod QR w <b>Google Authenticator</b>, a następnie wpisz kod aby aktywować.</p>
        <div style="text-align:center;margin:12px 0"><img src="${qrUrl}" width="160" height="160" style="border-radius:8px;background:#fff;padding:6px"></div>
        <div style="font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--muted);background:var(--bg);border:1px solid var(--brd);border-radius:8px;padding:8px;margin-bottom:12px;word-break:break-all">${d.secret}</div>
        <label class="slabel">Kod weryfikacyjny</label>
        <input type="text" id="s-2fa-code" class="sinput" placeholder="000000" maxlength="6" inputmode="numeric" style="letter-spacing:6px;font-size:18px;text-align:center">
        <div class="serr" id="s-2fa-err"></div>
        <button class="btn btnp" style="width:100%" onclick="enable2FASettings()">Włącz 2FA</button>`;
    }
  }catch(e){el.innerHTML='<div style="color:var(--red)">Błąd połączenia</div>';}
}
async function enable2FASettings(){
  const code=document.getElementById('s-2fa-code').value.trim();
  const err=document.getElementById('s-2fa-err');
  if(code.length!==6){err.textContent='Wpisz 6-cyfrowy kod';err.style.display='block';return;}
  const r=await fetch('/2fa/setup',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'secret='+encodeURIComponent(_2fa_secret)+'&code='+encodeURIComponent(code)});
  const d=await r.json();
  if(d.ok){toast('✓ 2FA włączone!');load2FATab();}
  else{err.textContent=d.error;err.style.display='block';}
}
async function disable2FASettings(){
  const pw=document.getElementById('s-2fa-dis-pw').value;
  const err=document.getElementById('s-2fa-dis-err');
  err.style.display='none';
  if(!pw){err.textContent='Wpisz hasło';err.style.display='block';return;}
  const r=await fetch('/2fa/disable',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'password='+encodeURIComponent(pw)});
  const d=await r.json();
  if(d.ok){toast('✓ 2FA wyłączone');load2FATab();}
  else{err.textContent=d.error;err.style.display='block';}
}
async function changePassword(){
  const old=document.getElementById('s-old-pw').value;
  const np=document.getElementById('s-new-pw').value;
  const np2=document.getElementById('s-new-pw2').value;
  const err=document.getElementById('s-pw-err');
  err.style.display='none';
  const r=await fetch('/settings/change-password',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'old_password='+encodeURIComponent(old)+'&new_password='+encodeURIComponent(np)+'&new_password2='+encodeURIComponent(np2)});
  const d=await r.json();
  if(d.ok){closeSettings();toast('✓ Hasło zmienione');}
  else{err.textContent=d.error;err.style.display='block';}
}
async function changeUsername(){
  const name=document.getElementById('s-new-name').value.trim();
  const pw=document.getElementById('s-name-pw').value;
  const err=document.getElementById('s-name-err');
  err.style.display='none';
  const r=await fetch('/settings/change-username',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'new_username='+encodeURIComponent(name)+'&password='+encodeURIComponent(pw)});
  const d=await r.json();
  if(d.ok){toast('✓ Nazwa zmieniona — odświeżam...');setTimeout(()=>location.reload(),1000);}
  else{err.textContent=d.error;err.style.display='block';}
}
async function deleteAccount(){
  const pw=document.getElementById('s-del-pw').value;
  const del_files=document.getElementById('s-del-files').checked?'1':'0';
  const err=document.getElementById('s-del-err');
  err.style.display='none';
  if(!pw){err.textContent='Wpisz hasło aby potwierdzić.';err.style.display='block';return;}
  if(!confirm('Na pewno usunąć konto? Tej operacji nie można cofnąć.'))return;
  try{
  const r=await fetch('/settings/delete-account',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'password='+encodeURIComponent(pw)+'&delete_files='+del_files});
  const d=await r.json();
  if(d.ok){location.href='/login';}
  else{err.textContent=d.error;err.style.display='block';}
  }catch{err.textContent='Błąd połączenia.';err.style.display='block';}
}
// ────────────────────────────────────────────────────
// ── 2FA ─────────────────────────────────────────────
let _2fa_secret = "";
async function open2FAModal(){
  document.getElementById('mb-2fa').style.display='flex';
  document.getElementById('2fa-qr-wrap').innerHTML='<div style="font-size:12px;color:var(--muted)">Ładowanie...</div>';
  document.getElementById('2fa-secret-display').textContent='';
  document.getElementById('2fa-err').style.display='none';
  document.getElementById('2fa-dis-err').style.display='none';
  document.getElementById('2fa-code-inp').value='';
  document.getElementById('2fa-disable-pw').value='';
  try{
    const r=await fetch('/2fa/setup');
    const d=await r.json();
    if(!d.ok){toast('Błąd ładowania 2FA',true);close2FAModal();return;}
    if(d.enabled){
      document.getElementById('2fa-setup-view').style.display='none';
      document.getElementById('2fa-disable-view').style.display='block';
      document.getElementById('2fa-title').textContent='🔐 Uwierzytelnianie dwuskładnikowe';
    } else {
      _2fa_secret=d.secret;
      document.getElementById('2fa-setup-view').style.display='block';
      document.getElementById('2fa-disable-view').style.display='none';
      document.getElementById('2fa-secret-display').textContent='Sekret: '+d.secret;
      // Generuj QR przez api.qrserver.com
      const qrUrl='https://api.qrserver.com/v1/create-qr-code/?size=160x160&data='+encodeURIComponent(d.uri);
      document.getElementById('2fa-qr-wrap').innerHTML=
        '<img src="'+qrUrl+'" width="160" height="160" style="border-radius:8px;background:#fff;padding:6px" alt="QR Code">'+
        '<div style="font-size:11px;color:var(--muted);margin-top:6px">Zeskanuj w Google Authenticator</div>';
    }
  }catch(e){toast('Błąd połączenia',true);close2FAModal();}
}
function close2FAModal(){
  document.getElementById('mb-2fa').style.display='none';
  _2fa_secret='';
}
async function confirm2FASetup(){
  const code=document.getElementById('2fa-code-inp').value.trim();
  if(code.length!==6){document.getElementById('2fa-err').textContent='Wpisz 6-cyfrowy kod';document.getElementById('2fa-err').style.display='block';return;}
  const r=await fetch('/2fa/setup',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'secret='+encodeURIComponent(_2fa_secret)+'&code='+encodeURIComponent(code)});
  const d=await r.json();
  if(d.ok){close2FAModal();toast('✓ 2FA włączone! Przy następnym logowaniu będzie wymagany kod.');}
  else{document.getElementById('2fa-err').textContent=d.error;document.getElementById('2fa-err').style.display='block';}
}
async function disable2FA(){
  const pw=document.getElementById('2fa-disable-pw').value;
  const err=document.getElementById('2fa-dis-err');
  err.style.display='none';
  if(!pw){err.textContent='Wpisz hasło';err.style.display='block';return;}
  const r=await fetch('/2fa/disable',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'password='+encodeURIComponent(pw)});
  const d=await r.json();
  if(d.ok){close2FAModal();toast('✓ 2FA wyłączone');}
  else{err.textContent=d.error;err.style.display='block';}
}
// ────────────────────────────────────────────────────
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
var _upoCollapsed=false;
function upoToggle(){
  _upoCollapsed=!_upoCollapsed;
  const popup=document.getElementById('upload-popup');
  popup.classList.toggle('upo-collapsed',_upoCollapsed);
  const ch=document.getElementById('upo-chevron');
  if(ch)ch.style.transform=_upoCollapsed?'rotate(180deg)':'rotate(0deg)';
}
function upoClose(){
  document.getElementById('upload-popup').style.display='none';
}

async function upload(files,hasRelPath=false){
  if(!files.length)return;
  const popup=document.getElementById('upload-popup');
  const pf=document.getElementById('pf');
  const pl=document.getElementById('pl');
  const puList=document.getElementById('pu-list');
  const upoTitle=document.getElementById('upo-title');
  const upoCloseBtn=document.getElementById('upo-close-btn');

  popup.style.display='block';
  popup.classList.remove('upo-collapsed');
  _upoCollapsed=false;
  const ch=document.getElementById('upo-chevron');
  if(ch)ch.style.transform='rotate(0deg)';
  puList.innerHTML='';
  pf.style.width='0';
  pl.textContent='';
  upoCloseBtn.style.display='none';

  const arr=[...files];
  const total=arr.length;
  let done=0,ok=0,fail=0,cancelled=0;
  const CONCURRENCY=2;

  function updateTitle(){
    const left=total-done-cancelled;
    if(left>0) upoTitle.textContent='Pozostało: '+left+' / '+total;
    else upoTitle.textContent=(fail||cancelled)?'\u2718 Ukończono z błędami':'\u2714 Przesłano pomyślnie';
  }
  updateTitle();

  function getFilePath(file){
    const rel=file._relPath||(file.webkitRelativePath||'');
    if(!rel)return CUR;
    const parts=rel.split('/');
    const subdir=parts.slice(0,-1).join('/');
    return CUR?(subdir?CUR+'/'+subdir:CUR):(subdir||'');
  }

  // Stwórz wiersz dla każdego pliku z przyciskiem anulowania
  const rows={};
  const xhrs={};
  arr.forEach((file,i)=>{
    const id='pu-'+i;
    const row=document.createElement('div');
    row.className='pu-item';
    row.innerHTML=
      `<span class="pu-name" title="${file.name}">${file.name}</span>`+
      `<span class="pu-status" id="${id}-st"></span>`+
      `<div class="pu-bar-wrap"><div class="pu-bar-fill" id="${id}-bar"></div></div>`+
      `<span class="pu-pct" id="${id}-pct">—</span>`+
      `<button class="pu-cancel" id="${id}-cancel" title="Anuluj" onclick="upoCancel(${i})">` +
        `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="11" height="11"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`+
      `</button>`;
    puList.appendChild(row);
    rows[i]={
      bar:document.getElementById(id+'-bar'),
      pct:document.getElementById(id+'-pct'),
      st:document.getElementById(id+'-st'),
      cancel:document.getElementById(id+'-cancel'),
    };
  });

  window.upoCancel=function(i){
    if(xhrs[i]){
      xhrs[i].abort();
      delete xhrs[i];
    }
  };

  function uploadOne(file,i){
    return new Promise(resolve=>{
      // Plik mógł być anulowany zanim trafił do kolejki
      if(rows[i].st.textContent==='\u2298'){resolve();return;}

      const fd=new FormData();
      fd.append('path',getFilePath(file));
      fd.append('file',file);
      const xhr=new XMLHttpRequest();
      xhrs[i]=xhr;

      xhr.upload.onprogress=e=>{
        if(!e.lengthComputable)return;
        const pct=Math.round(e.loaded/e.total*100);
        rows[i].bar.style.width=pct+'%';
        rows[i].pct.textContent=pct+'%';
      };
      xhr.onload=()=>{
        delete xhrs[i];
        rows[i].cancel.classList.add('hidden');
        try{
          const d=JSON.parse(xhr.responseText);
          if(d.ok){
            ok++;
            rows[i].bar.classList.add('done');
            rows[i].bar.style.width='100%';
            rows[i].pct.textContent='100%';
            rows[i].st.textContent='\u2714';
          } else {
            fail++;
            rows[i].bar.classList.add('err');
            rows[i].pct.textContent='';
            rows[i].st.textContent='\u2718';
            toast('Błąd: '+d.error,true);
          }
        }catch{
          fail++;
          rows[i].bar.classList.add('err');
          rows[i].st.textContent='\u2718';
        }
        done++;
        pf.style.width=(done/total*100)+'%';
        pl.textContent=done+' / '+total+(fail?' · ✗ '+fail:'');
        updateTitle();
        resolve();
      };
      xhr.onabort=()=>{
        delete xhrs[i];
        cancelled++;
        rows[i].cancel.classList.add('hidden');
        rows[i].bar.classList.add('err');
        rows[i].pct.textContent='';
        rows[i].st.textContent='\u2298';
        done++;
        pf.style.width=(done/total*100)+'%';
        pl.textContent=done+' / '+total+(fail||cancelled?' · ✗ '+(fail+cancelled):'');
        updateTitle();
        resolve();
      };
      xhr.onerror=()=>{
        delete xhrs[i];
        fail++;done++;
        rows[i].cancel.classList.add('hidden');
        rows[i].bar.classList.add('err');
        rows[i].pct.textContent='';
        rows[i].st.textContent='\u2718';
        pf.style.width=(done/total*100)+'%';
        pl.textContent=done+' / '+total+' · ✗ '+fail;
        updateTitle();
        resolve();
      };
      xhr.open('POST','/upload');
      xhr.send(fd);
    });
  }

  const queue=arr.map((f,i)=>()=>uploadOne(f,i));
  async function worker(){while(queue.length){const task=queue.shift();if(task)await task();}}
  await Promise.all(Array.from({length:Math.min(CONCURRENCY,total)},worker));

  pf.style.width='100%';
  const msg=ok+' '+(ok===1?'plik':'pliki/ów')+' przesłano'+(fail?' · ✗ '+fail+' błędów':'')+(cancelled?' · ⊘ '+cancelled+' anulowano':'');
  pl.textContent=msg;
  upoCloseBtn.style.display='flex';
  if(ok)toast('✓ '+ok+' '+(ok===1?'plik':'pliki/ów')+' przesłano');
  setTimeout(()=>location.reload(),900);
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
        const wrapA=img.closest('.thumb-audio');
        if(wrapA)wrapA.classList.add('has-cover');
        // okładka wideo — pokaż cover
        const wrapV=img.closest('.thumb-video-inner');
        if(wrapV)wrapV.closest('.thumb-video').classList.add('has-cover');
      };
      img.onerror=()=>{img.style.display='none';};
      lazyObs.unobserve(img);
    }
  });
},{rootMargin:'120px'});
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

  // Zamknij przy ESC
  document.addEventListener('keydown',e=>{if(e.key==='Escape')window.closeMobMenu();});

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
async function desktopRestart(){
  if(!confirm('Zrestartować serwer?'))return;
  try{await fetch('/restart',{method:'POST'});}catch(e){}
  toast('Restartuję... odśwież za chwilę');
  setTimeout(()=>location.reload(),4000);
}
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
%%BG_ANIM%%
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
                <circle cx="40" cy="40" r="4" fill="var(--acc)"/>
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
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){{
  function makeFavicon(){{
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }}
  function init(){{
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{{attributes:true,attributeFilter:['style','class']}});
  }}
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',init);}}else{{init();}}
}})();
</script>
<script>
(function(){{
  try{{
    var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!_s) return;
    var _DK={'Niebieski':{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},'Zielony':{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},'Czerwony':{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},'Fioletowy':{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},'Mono':{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},'Różowy':{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}};
    var _LT={'Niebieski':{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},'Zielony':{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},'Czerwony':{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},'Fioletowy':{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},'Mono':{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},'Różowy':{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}};
    var _mode=_s.mode||'dark', _name=_s.name||'Mono';
    var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
    var r=document.documentElement;
    r.style.setProperty('--acc',  t.acc);
    r.style.setProperty('--acc2', t.acc2);
    r.style.setProperty('--bg',   t.bg);
    r.style.setProperty('--sur',  t.sur);
    r.style.setProperty('--brd',  t.brd);
    r.style.setProperty('--txt',  t.txt||'#e6edf3');
    r.style.setProperty('--muted',t.muted||'#7d8590');
    r.style.setProperty('--gr1',  t.gr1);
    r.style.setProperty('--gr2',  t.gr2);
    r.style.setProperty('--gr3',  t.gr3);
    r.style.setProperty('--gr4',  t.gr4);
    r.classList.toggle('theme-mono', _name==='Mono');
    r.classList.toggle('theme-light', _mode==='light');
  }}catch(e){{}}
}})();
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;--gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);--gr3:rgba(71,85,105,.10);--gr4:rgba(51,65,85,.08);--r:10px}}
body{{
  font-family:"Inter",system-ui,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;flex-direction:column;
  background-image:none;
}}
.topbar{{background:rgba(10,12,20,.90);backdrop-filter:blur(12px);border-bottom:1px solid var(--brd);padding:0 20px;height:52px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:50;flex-shrink:0}}
.back{{display:flex;align-items:center;gap:6px;color:var(--muted);text-decoration:none;font-size:13px;font-weight:500;padding:5px 10px;border-radius:7px;border:1px solid transparent;transition:all .15s;white-space:nowrap}}
.back:hover{{color:var(--txt);border-color:var(--brd);background:var(--sur)}}
.topbar-name{{font-size:14px;font-weight:600;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}}
.topbar-meta{{font-size:12px;color:var(--muted);white-space:nowrap}}
.dl-btn{{display:flex;align-items:center;gap:6px;color:#e0e7ff;background:var(--acc2);border:none;border-radius:7px;padding:6px 12px;font-family:inherit;font-size:13px;font-weight:500;cursor:pointer;text-decoration:none;white-space:nowrap;transition:opacity .15s}}
.dl-btn:hover{{opacity:.85}}
.viewer{{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;z-index:1}}
.vimg-wrap{{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;padding:24px;cursor:grab}}
.vimg-wrap:active{{cursor:grabbing}}
.vimg-wrap img{{max-width:100%;max-height:75vh;object-fit:contain;transition:transform .2s;border-radius:6px;user-select:none}}
.vimg-controls{{display:flex;align-items:center;justify-content:center;gap:8px;padding:12px 20px;border-top:1px solid var(--brd);background:var(--sur);flex-shrink:0}}
.vimg-controls button{{background:var(--bg);border:1px solid var(--brd);color:var(--txt);padding:5px 14px;border-radius:6px;cursor:pointer;font-size:16px;font-family:inherit;transition:background .15s}}
.vimg-controls button:hover{{background:var(--brd)}}
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
.vaudio-progress-fill{{position:absolute;left:0;top:0;height:100%;border-radius:2px;background:linear-gradient(90deg,var(--acc2),var(--acc));pointer-events:none;transition:width .1s linear}}
.vaudio-progress-thumb{{position:absolute;top:50%;width:14px;height:14px;border-radius:50%;background:#818cf8;transform:translate(-50%,-50%) scale(0);transition:transform .15s;box-shadow:0 0 6px rgba(129,140,248,.6);pointer-events:none}}
.vaudio-progress-bar:hover .vaudio-progress-thumb{{transform:translate(-50%,-50%) scale(1)}}
.vaudio-times{{display:flex;justify-content:space-between;width:100%;font-size:11px;color:var(--muted);padding:2px 0}}
.vaudio-controls{{display:flex;align-items:center;gap:16px;margin:4px 0}}
.vaudio-btn{{background:none;border:none;cursor:pointer;color:var(--muted);transition:color .15s,transform .1s;display:flex;align-items:center;justify-content:center;padding:6px;border-radius:50%}}
.vaudio-btn:hover{{color:var(--txt);transform:scale(1.1)}}
.vaudio-btn-play{{width:56px;height:56px;background:linear-gradient(135deg,var(--acc2),var(--acc));color:#fff !important;border-radius:50%;box-shadow:0 4px 20px rgba(79,70,229,.5);transition:transform .1s,box-shadow .15s}}
.vaudio-btn-play:hover{{transform:scale(1.07)!important;box-shadow:0 6px 28px rgba(79,70,229,.7)}}
.vaudio-vol-row{{display:flex;align-items:center;gap:8px;width:100%;color:var(--muted)}}
.vaudio-vol{{flex:1;-webkit-appearance:none;appearance:none;height:3px;border-radius:2px;background:rgba(255,255,255,.1);outline:none;cursor:pointer}}
.vaudio-vol::-webkit-slider-thumb{{-webkit-appearance:none;width:12px;height:12px;border-radius:50%;background:var(--acc);cursor:pointer}}
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
.arc-row:hover{{background:color-mix(in srgb,var(--acc) 7%,transparent)}}
.arc-dir .arc-name{{color:#e3b341;font-weight:500}}
.arc-name{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--txt)}}
.arc-size{{font-size:11px;color:var(--muted);white-space:nowrap;text-align:right}}
.arc-dl{{color:var(--acc);text-decoration:none;font-size:15px;display:flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:6px;transition:background .12s;border:1px solid transparent}}
.arc-dl:hover{{background:color-mix(in srgb,var(--acc) 15%,transparent);border-color:var(--acc)}}
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
{BG_ANIMATION_JS}
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
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){{
  function makeFavicon(){{
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }}
  function init(){{
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{{attributes:true,attributeFilter:['style','class']}});
  }}
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',init);}}else{{init();}}
}})();
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Audiowide&display=swap" rel="stylesheet">
<script>
(function(){{
  try{{
    var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!_s) return;
    var _DK={'Niebieski':{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},'Zielony':{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},'Czerwony':{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},'Fioletowy':{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},'Mono':{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},'Różowy':{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}};
    var _LT={'Niebieski':{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},'Zielony':{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},'Czerwony':{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},'Fioletowy':{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},'Mono':{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},'Różowy':{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}};
    var _mode=_s.mode||'dark', _name=_s.name||'Mono';
    var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
    var r=document.documentElement;
    r.style.setProperty('--acc',  t.acc);
    r.style.setProperty('--acc2', t.acc2);
    r.style.setProperty('--bg',   t.bg);
    r.style.setProperty('--sur',  t.sur);
    r.style.setProperty('--brd',  t.brd);
    r.style.setProperty('--txt',  t.txt||'#e6edf3');
    r.style.setProperty('--muted',t.muted||'#7d8590');
    r.style.setProperty('--gr1',  t.gr1);
    r.style.setProperty('--gr2',  t.gr2);
    r.style.setProperty('--gr3',  t.gr3);
    r.style.setProperty('--gr4',  t.gr4);
    r.classList.toggle('theme-mono', _name==='Mono');
    r.classList.toggle('theme-light', _mode==='light');
  }}catch(e){{}}
}})();
</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--red:#f85149;--red2:#6e3535;--acc:#e2e8f0;--acc2:#94a3b8}}
body{{
  font-family:'Inter',system-ui,sans-serif;
  background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  background-image:none;
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
{BG_ANIMATION_JS}
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

    def setup_2fa_prompt_page(self, session_token):
        """Strona po rejestracji pytająca o włączenie 2FA."""
        secret  = totp_generate_secret()
        uri     = totp_get_uri("__setup__", secret)
        qr_url  = "https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=" + urllib.parse.quote(uri)
        return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>SAFE CLOUD \u2014 Konfiguracja 2FA</title>
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){{
  var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
  if(!_s)return;
  var _DK={{'Niebieski':{{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'}},'Zielony':{{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'}},'Czerwony':{{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'}},'Fioletowy':{{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'}},'Mono':{{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'}},'Różowy':{{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}}}};
  var _LT={{'Niebieski':{{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'}},'Zielony':{{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'}},'Czerwony':{{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'}},'Fioletowy':{{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'}},'Mono':{{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'}},'Różowy':{{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}}}};
  var _mode=_s.mode||'dark',_name=_s.name||'Mono';
  var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
  var r=document.documentElement;
  r.style.setProperty('--acc',t.acc);r.style.setProperty('--acc2',t.acc2);
  r.style.setProperty('--bg',t.bg);r.style.setProperty('--sur',t.sur);r.style.setProperty('--brd',t.brd);
  r.style.setProperty('--txt',t.txt||'#e6edf3');r.style.setProperty('--muted',t.muted||'#7d8590');
  r.style.setProperty('--gr1',t.gr1);r.style.setProperty('--gr2',t.gr2);
  r.style.setProperty('--gr3',t.gr3);r.style.setProperty('--gr4',t.gr4);
  r.classList.toggle('theme-mono',_name==='Mono');r.classList.toggle('theme-light',_mode==='light');
}}catch(e){{}}
</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;
  --gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);--gr3:rgba(71,85,105,.10);--gr4:rgba(51,65,85,.08)}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:var(--sur);border:1px solid var(--brd);border-radius:20px;padding:36px 32px;
  width:100%;max-width:400px;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,.55);position:relative;z-index:1}}
.logo{{display:flex;align-items:center;justify-content:center;gap:9px;
  font-family:'Audiowide',sans-serif;font-size:15px;font-weight:700;letter-spacing:.04em;
  color:var(--txt);margin-bottom:28px}}
/* Badge nowy krok */
.step-badge{{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;color:var(--acc);
  background:color-mix(in srgb,var(--acc) 12%,transparent);
  border:1px solid color-mix(in srgb,var(--acc) 30%,transparent);
  border-radius:20px;padding:4px 12px;margin-bottom:20px}}
h2{{font-size:18px;font-weight:700;margin-bottom:8px}}
.sub{{font-size:13px;color:var(--muted);line-height:1.6;margin-bottom:24px}}
.sep{{height:1px;background:var(--brd);margin:20px 0}}
/* Przyciski */
.btn-primary{{width:100%;padding:12px;border:none;border-radius:12px;
  background:linear-gradient(135deg,var(--acc2),var(--acc));color:var(--bg);
  font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;
  transition:opacity .15s,transform .1s;margin-bottom:10px;display:flex;
  align-items:center;justify-content:center;gap:8px}}
.btn-primary:hover{{opacity:.9;transform:translateY(-1px)}}
.btn-skip{{width:100%;padding:11px;border:1px solid var(--brd);border-radius:12px;
  background:none;color:var(--muted);font-family:inherit;font-size:13px;
  cursor:pointer;transition:all .15s}}
.btn-skip:hover{{border-color:var(--acc);color:var(--txt)}}
/* Sekcja QR */
.qr-wrap{{display:none;margin-top:20px;text-align:left}}
.qr-wrap.show{{display:block}}
.qr-center{{text-align:center;margin:16px 0}}
.qr-center img{{border-radius:10px;background:#fff;padding:8px}}
.qr-secret{{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);
  background:var(--bg);border:1px solid var(--brd);border-radius:8px;
  padding:8px 12px;word-break:break-all;text-align:center;margin:10px 0 16px}}
label{{display:block;font-size:11px;font-weight:600;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted);margin-bottom:6px;text-align:left}}
input[type=text]{{width:100%;padding:10px 13px;border:1px solid var(--brd);border-radius:8px;
  font-family:inherit;font-size:16px;color:var(--txt);background:var(--bg);outline:none;
  margin-bottom:12px;letter-spacing:6px;text-align:center;transition:border-color .15s}}
input[type=text]:focus{{border-color:var(--acc)}}
.err{{color:#f85149;font-size:12px;margin-bottom:12px;display:none}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg width="30" height="18" viewBox="0 0 38 22" fill="none">
      <path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z"
            stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(226,232,240,0.08)"/>
      <path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/>
    </svg>
    SAFE CLOUD
  </div>

  <div class="step-badge">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
    Opcjonalne zabezpieczenie
  </div>

  <h2>Czy chcesz w\u0142\u0105czy\u0107 2FA?</h2>
  <p class="sub">Uwierzytelnianie dwusk\u0142adnikowe znacznie zwi\u0119ksza bezpiecze\u0144stwo konta. Mo\u017cesz to zrobi\u0107 teraz lub p\u00f3\u017aniej w ustawieniach.</p>

  <!-- Krok 1 — pytanie -->
  <div id="step1">
    <button class="btn-primary" onclick="showSetup()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      Tak, w\u0142\u0105cz 2FA teraz
    </button>
    <button class="btn-skip" onclick="skipSetup()">Pomi\u0144 \u2014 zrobi\u0119 to p\u00f3\u017aniej</button>
  </div>

  <!-- Krok 2 — konfiguracja -->
  <div class="qr-wrap" id="step2">
    <div class="sep" style="margin-top:0"></div>
    <p style="font-size:13px;color:var(--muted);margin-bottom:4px">
      Zeskanuj kod QR w <b style="color:var(--txt)">Google Authenticator</b> lub podobnej aplikacji.
    </p>
    <div class="qr-center">
      <img src="{qr_url}" width="160" height="160" alt="QR kod">
    </div>
    <div class="qr-secret" id="secret-display">{secret}</div>
    <label>Wpisz 6-cyfrowy kod weryfikacyjny</label>
    <input type="text" id="code-inp" placeholder="000000" maxlength="6" inputmode="numeric"
           oninput="this.value=this.value.replace(/[^0-9]/g,'')">
    <div class="err" id="err-msg">Nieprawid\u0142owy kod. Spr\u00f3buj ponownie.</div>
    <button class="btn-primary" onclick="verifyAndEnable()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
      Potwierd\u017a i w\u0142\u0105cz 2FA
    </button>
    <button class="btn-skip" onclick="skipSetup()">Pomi\u0144 na razie</button>
  </div>
</div>
{BG_ANIMATION_JS}
<script>
var SECRET='{secret}';
var SESSION_TOKEN='{session_token}';

function showSetup(){{
  document.getElementById('step1').style.display='none';
  document.getElementById('step2').classList.add('show');
  document.getElementById('code-inp').focus();
}}

function skipSetup(){{
  // Przekieruj na stronę główną — sesja już istnieje w cookie
  window.location.href='/';
}}

async function verifyAndEnable(){{
  var code=document.getElementById('code-inp').value.trim();
  var err=document.getElementById('err-msg');
  err.style.display='none';
  if(code.length!==6){{err.textContent='Wpisz 6-cyfrowy kod.';err.style.display='block';return;}}
  try{{
    var r=await fetch('/2fa/setup-register',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{secret:SECRET,code:code}})
    }});
    var d=await r.json();
    if(d.ok){{
      window.location.href='/';
    }}else{{
      err.textContent=d.error||'Nieprawid\u0142owy kod. Spr\u00f3buj ponownie.';
      err.style.display='block';
      document.getElementById('code-inp').value='';
      document.getElementById('code-inp').focus();
    }}
  }}catch{{
    err.textContent='B\u0142\u0105d po\u0142\u0105czenia. Spr\u00f3buj ponownie.';
    err.style.display='block';
  }}
}}

document.getElementById('code-inp').addEventListener('keydown',function(e){{
  if(e.key==='Enter')verifyAndEnable();
}});
</script>
</body>
</html>"""

    def totp_page(self, pending, error=""):
        err_display = "block" if error else "none"
        return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>SAFE CLOUD – Weryfikacja 2FA</title>
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){{
  function makeFavicon(){{
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }}
  function init(){{
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{{attributes:true,attributeFilter:['style','class']}});
  }}
  if(document.readyState==='loading'){{document.addEventListener('DOMContentLoaded',init);}}else{{init();}}
}})();
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">

<script>
(function(){{
  try{{
    var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!_s) return;
    var _DK={'Niebieski':{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},'Zielony':{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},'Czerwony':{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},'Fioletowy':{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},'Mono':{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},'Różowy':{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}};
    var _LT={'Niebieski':{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},'Zielony':{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},'Czerwony':{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},'Fioletowy':{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},'Mono':{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},'Różowy':{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}};
    var _mode=_s.mode||'dark', _name=_s.name||'Mono';
    var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
    var r=document.documentElement;
    r.style.setProperty('--acc',  t.acc);
    r.style.setProperty('--acc2', t.acc2);
    r.style.setProperty('--bg',   t.bg);
    r.style.setProperty('--sur',  t.sur);
    r.style.setProperty('--brd',  t.brd);
    r.style.setProperty('--txt',  t.txt||'#e6edf3');
    r.style.setProperty('--muted',t.muted||'#7d8590');
    r.style.setProperty('--gr1',  t.gr1);
    r.style.setProperty('--gr2',  t.gr2);
    r.style.setProperty('--gr3',  t.gr3);
    r.style.setProperty('--gr4',  t.gr4);
    r.classList.toggle('theme-mono', _name==='Mono');
    r.classList.toggle('theme-light', _mode==='light');
  }}catch(e){{}}
}})();
</script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;--red:#f85149}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;background-image:none}}
.card{{background:var(--sur);border:1px solid var(--brd);border-radius:16px;padding:36px 32px;width:100%;max-width:360px;box-shadow:0 20px 60px rgba(0,0,0,.5);text-align:center;position:relative;z-index:1}}
.logo{{display:flex;align-items:center;justify-content:center;gap:10px;font-weight:700;font-size:20px;margin-bottom:8px;font-family:'Audiowide',sans-serif}}
.sub{{font-size:13px;color:var(--muted);margin-bottom:24px}}
.otp-wrap{{display:flex;gap:8px;justify-content:center;margin-bottom:16px}}
.otp-inp{{width:44px;height:52px;text-align:center;font-size:22px;font-weight:700;border:1px solid var(--brd);border-radius:10px;background:var(--bg);color:var(--txt);outline:none;transition:border-color .15s;font-family:'JetBrains Mono',monospace}}
.otp-inp:focus{{border-color:var(--acc)}}
.submit{{width:100%;padding:11px;border:none;border-radius:8px;background:var(--acc2);color:#e0e7ff;font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;margin-top:4px}}
.submit:hover{{background:#4338ca}}
.err{{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.4);color:var(--red);border-radius:8px;padding:10px 13px;font-size:13px;margin-bottom:14px;display:{err_display}}}
.back{{font-size:12px;color:var(--muted);margin-top:16px;display:block;text-decoration:none}}
.back:hover{{color:var(--txt)}}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><svg viewBox="0 0 38 22" width="26" height="15" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/></svg>SAFE CLOUD</div>
  <div class="sub">Wprowadź 6-cyfrowy kod z Google Authenticator</div>
  <div class="err">{html.escape(error)}</div>
  <form method="POST" action="/totp-verify" id="otp-form">
    <input type="hidden" name="pending" value="{html.escape(pending)}">
    <input type="hidden" name="code" id="code-hidden">
    <div class="otp-wrap" id="otp-wrap">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
      <input class="otp-inp" maxlength="1" inputmode="numeric" pattern="[0-9]">
    </div>
    <button class="submit" type="submit">Weryfikuj</button>
  </form>
  <a class="back" href="/login">&#8592; Wróć do logowania</a>
</div>
<script>
const inputs=[...document.querySelectorAll('.otp-inp')];
inputs.forEach((inp,i)=>{{
  inp.addEventListener('input',e=>{{
    inp.value=inp.value.replace(/[^0-9]/g,'').slice(-1);
    if(inp.value&&i<5)inputs[i+1].focus();
    if(inputs.every(x=>x.value))submit();
  }});
  inp.addEventListener('keydown',e=>{{
    if(e.key==='Backspace'&&!inp.value&&i>0)inputs[i-1].focus();
  }});
  inp.addEventListener('paste',e=>{{
    e.preventDefault();
    const txt=(e.clipboardData||window.clipboardData).getData('text').replace(/[^0-9]/g,'');
    txt.split('').forEach((c,j)=>{{if(inputs[j])inputs[j].value=c;}});
    if(txt.length>=6)submit();
  }});
}});
function submit(){{
  document.getElementById('code-hidden').value=inputs.map(x=>x.value).join('');
  document.getElementById('otp-form').submit();
}}
inputs[0].focus();
</script>
</body>
</html>"""

    def auth_page(self, error="", tab="login"):
        page = (AUTH_HTML
            .replace("%%ERR_DISPLAY%%",  "block" if error else "none")
            .replace("%%ERROR_MSG%%",    html.escape(error))
            .replace("%%TAB_LOGIN%%",    "active" if tab == "login" else "")
            .replace("%%TAB_REG%%",      "active" if tab == "reg" else "")
            .replace("%%SHOW_LOGIN%%",   "block" if tab == "login" else "none")
            .replace("%%SHOW_REG%%",     "block" if tab == "reg" else "none")
            .replace("%%APP_VERSION%%",  (lambda v: f"v{v['version']} {v['stage']}")(load_version()))
            .replace("%%BG_ANIM%%",      BG_ANIMATION_JS)
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
        mod   = is_moderator(username)
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
            if mod:
                admin_badge = '<span class="role-badge" style="color:#60a5fa;border-color:#60a5fa55;background:#60a5fa18">MOD</span>'
            else:
                r = get_user_role(users, username)
                if r:
                    rc = r["color"]
                    rn = html.escape(r["name"])
                    admin_badge = f'<span class="role-badge" style="color:{rc};border-color:{rc}55;background:{rc}18">{rn}</span>'

        has_terminal = admin or owner or mod

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
            .replace("%%TERMINAL_BTN%%",       '<button class="logout-btn" onclick="openSettings()" style="border-color:rgba(129,140,248,.3);color:#818cf8;display:inline-flex;align-items:center;gap:5px"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13"><circle cx="12" cy="8" r="4"/><path d="M6 20v-2a6 6 0 0112 0v2"/><circle cx="19" cy="19" r="3" fill="rgba(129,140,248,.2)" stroke="currentColor"/><line x1="19" y1="17" x2="19" y2="21"/><line x1="17" y1="19" x2="21" y2="19"/></svg>Ustawienia</button>' + (' <button class="term-header-btn" onclick="desktopRestart()" title="Restartuj serwer" style="color:#f87171;border-color:#6e3535"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>Restart</button><button class="term-header-btn" id="term-header-btn" onclick="toggleTerm()" title="Terminal"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>Terminal</button>' if has_terminal else ''))
            .replace("%%MOB_TERMINAL_ITEM%%",  '<div class="mob-menu-sep"></div><button class="mob-menu-item" onclick="closeMobMenu();toggleTerm()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>Terminal admina</button>' if has_terminal else '')
            .replace("%%MOB_RESTART_BTN%%",    '''<button class="mob-menu-item red" id="mob-restart-btn" onclick="mobRestart()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Restartuj serwer
      </button>''' if (admin or owner) else "")
            .replace("%%MOB_STATS_BLOCK%%",    '''<div class="mob-menu-sep"></div>
      <div class="mob-stats-block">
        <div class="msb-title">Serwer</div>
        <div class="mob-stats-grid">
          <div class="msb-row"><span class="msb-lbl">RAM</span><span class="msb-val" id="msb-ram">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Cloudflared</span><span class="msb-val" id="msb-cfd">—</span></div>
          <div class="msb-row"><span class="msb-lbl">CPU</span><span class="msb-val" id="msb-cpu">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Wątki</span><span class="msb-val" id="msb-thr">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Połączenia</span><span class="msb-val" id="msb-con">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Cache</span><span class="msb-val" id="msb-cache">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Dysk R</span><span class="msb-val" id="msb-dr">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Dysk W</span><span class="msb-val" id="msb-dw">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Net ↑</span><span class="msb-val" id="msb-nup">—</span></div>
          <div class="msb-row"><span class="msb-lbl">Net ↓</span><span class="msb-val" id="msb-ndw">—</span></div>
        </div>
      </div>''' if has_terminal else "")
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
      // sieć
      const nup=document.getElementById('msb-nup');if(nup)nup.textContent=d.net_up||'—';
      const ndw=document.getElementById('msb-ndw');if(ndw)ndw.textContent=d.net_down||'—';
      const snup=document.getElementById('st-nup');if(snup)snup.textContent=d.net_up||'—';
      const sndw=document.getElementById('st-ndw');if(sndw)sndw.textContent=d.net_down||'—';
      // cloudflared RAM
      const cfd=document.getElementById('msb-cfd');
      if(cfd){cfd.textContent=d.cloudflared_ram||'—';}
    }catch(e){}
  }
  refreshStats();
  setInterval(refreshStats,30000);
})();''' if (admin or owner or mod) else "")
            .replace("%%SORT_BY%%",            sort_by)
            .replace("%%SORT_DIR%%",           sort_dir)
            .replace("%%SEARCH_VAL%%",         html.escape(search))
            .replace("%%SORT_NAME_ACTIVE%%",   "active" if sort_by == "name" else "")
            .replace("%%SORT_DATE_ACTIVE%%",   "active" if sort_by == "date" else "")
            .replace("%%SORT_SIZE_ACTIVE%%",   "active" if sort_by == "size" else "")
            .replace("%%SORT_NAME_ICO%%",      sort_ico("name"))
            .replace("%%SORT_DATE_ICO%%",      sort_ico("date"))
            .replace("%%SORT_SIZE_ICO%%",      sort_ico("size"))
            .replace("%%BG_ANIM%%",            BG_ANIMATION_JS)
        )
        return page

    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(p.query)

            # ── Tryb konserwacji ─────────────────────────
            if _maintenance["active"]:
                # Publiczne linki /s/ też blokujemy
                # Admin i owner mogą wejść normalnie — sprawdzamy sesję
                token = get_token_from_request(self)
                session_user = get_session(token) if token else None
                if not (session_user and (is_admin(session_user) or is_owner(session_user))):
                    # Zezwalamy na /login żeby admin mógł się zalogować
                    if p.path not in ("/login", "/register"):
                        page = MAINTENANCE_HTML.replace("%%MSG%%", html.escape(_maintenance["message"])).replace("%%BG_ANIM%%", BG_ANIMATION_JS)
                        self.send_html(page, 503)
                        return

            if p.path == "/login":
                self.send_html(self.auth_page())
                return
            if p.path == "/register":
                self.send_html(self.auth_page(tab="reg"))
                return

            # ── Publiczny link — strona z odliczaniem ────
            if p.path.startswith("/s/"):
                token = p.path[3:]
                share = get_share(token)
                if not share:
                    self.send_html("<html><body style='font-family:sans-serif;background:#09090b;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>\u274c Link wygas\u0142 lub nie istnieje</h2><p style='color:#7d8590'>Ten link zosta\u0142 ju\u017c u\u017cyty lub min\u0105\u0142 jego termin wa\u017cno\u015bci.</p></div></body></html>", 410)
                    return
                owner_dir = user_storage(share["owner"])
                fpath = safe_path(owner_dir, share["path"])
                if not fpath or not fpath.is_file():
                    self.send_html("<html><body style='font-family:sans-serif;background:#09090b;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>\u274c Plik nie istnieje</h2><p style='color:#7d8590'>Plik m\u00f3g\u0142 zosta\u0107 usuni\u0119ty.</p></div></body></html>", 404)
                    return
                fname_esc   = html.escape(share["name"])
                fsize_esc   = html.escape(human_size(fpath.stat().st_size))
                expires     = share.get("expires")
                now_ts      = time.time()

                # Ikona SVG dopasowana do rozszerzenia
                _ext = Path(share["name"]).suffix.lower()
                _ic  = "var(--acc)"
                if _ext in {".jpg",".jpeg",".png",".gif",".webp",".svg",".avif"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>'
                elif _ext in {".mp4",".avi",".mov",".mkv",".webm",".m4v"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><rect x="2" y="4" width="15" height="16" rx="2"/><path d="M17 8l5-3v14l-5-3V8z"/></svg>'
                elif _ext in {".mp3",".wav",".flac",".ogg",".aac",".m4a",".opus"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'
                elif _ext == ".pdf":
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/></svg>'
                elif _ext in {".zip",".rar",".7z",".tar",".gz",".bz2"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v11a2 2 0 002 2h12a2 2 0 002-2V9"/><path d="M10 13h4"/></svg>'
                elif _ext in {".doc",".docx",".odt"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h6"/></svg>'
                elif _ext in {".xls",".xlsx",".csv"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/></svg>'
                elif _ext in {".py",".js",".ts",".html",".css",".json",".xml",".sh",".cpp",".c",".java",".go",".rs"}:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>'
                else:
                    file_icon_svg = f'<svg viewBox="0 0 24 24" fill="none" stroke="{_ic}" stroke-width="1.4" width="36" height="36"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>'
                now_ts      = time.time()
                # Zbuduj odliczanie
                if expires:
                    remaining   = max(0, int(expires - now_ts))
                    expire_iso  = datetime.fromtimestamp(expires).strftime("%d.%m.%Y %H:%M:%S")
                    countdown_js = f"""
var _exp={int(expires)};
function _tick(){{
  var left=_exp-Math.floor(Date.now()/1000);
  if(left<=0){{document.getElementById('cdtimer').textContent='Link wygasł!';
    document.getElementById('dlbtn').disabled=true;return;}}
  var h=Math.floor(left/3600),m=Math.floor((left%3600)/60),s=left%60;
  document.getElementById('cdtimer').textContent=
    (h?h+'h ':'')+((m<10&&h)?'0':'')+m+'m '+(s<10?'0':'')+s+'s';
  setTimeout(_tick,1000);
}}
_tick();"""
                    expires_line = f'<div class="cd-expire">Wygasa: <b>{expire_iso}</b></div>'
                    timer_block  = f'<div class="cd-timer" id="cdtimer"></div>'
                else:
                    countdown_js = ""
                    expires_line = '<div class="cd-expire" style="color:#3fb950">Link bezterminowy</div>'
                    timer_block  = ""

                page = f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pobierz: {fname_esc}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg viewBox='0 0 38 22' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z' stroke='%23818cf8' stroke-width='1.6' stroke-linejoin='round' fill='rgba(129,140,248,0.12)'/%3E%3C/svg%3E">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;
  --gr1:rgba(148,163,184,.22);--gr2:rgba(100,116,139,.12);--gr3:rgba(71,85,105,.10);--gr4:rgba(51,65,85,.08)}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
  background-image:none}}
.card{{background:var(--sur);border:1px solid var(--brd);border-radius:20px;padding:36px 32px;
  max-width:400px;width:100%;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,.6);position:relative;z-index:1}}
/* Logo */
.sc-logo{{display:flex;align-items:center;justify-content:center;gap:9px;
  font-family:'Audiowide',sans-serif;font-size:15px;font-weight:700;letter-spacing:.04em;
  color:var(--txt);margin-bottom:28px}}
.sc-logo-mark{{width:32px;height:20px;flex-shrink:0}}
/* Ikona pliku */
.file-icon-wrap{{
  width:72px;height:72px;border-radius:18px;margin:0 auto 18px;
  display:flex;align-items:center;justify-content:center;
  background:linear-gradient(135deg,rgba(79,70,229,.2),rgba(129,140,248,.1));
  border:1px solid rgba(129,140,248,.2);
}}
/* Nazwa i rozmiar */
.fname{{font-size:15px;font-weight:600;word-break:break-all;margin-bottom:5px;line-height:1.4}}
.fsize{{font-size:12px;color:var(--muted);margin-bottom:22px}}
/* Separator */
.sep{{height:1px;background:var(--brd);margin:0 0 20px}}
/* Wygaśnięcie */
.cd-expire{{font-size:12px;color:var(--muted);margin-bottom:6px}}
.cd-expire b{{color:var(--txt)}}
.cd-timer{{font-size:30px;font-weight:700;color:var(--acc);font-variant-numeric:tabular-nums;
  letter-spacing:.06em;margin-bottom:22px;min-height:38px}}
/* Przycisk */
.dlbtn{{display:inline-flex;align-items:center;gap:9px;padding:13px 32px;width:100%;justify-content:center;
  background:linear-gradient(135deg,var(--acc2),var(--acc));color:#fff;
  font-family:inherit;font-size:14px;font-weight:600;border:none;border-radius:12px;
  cursor:pointer;text-decoration:none;transition:opacity .15s,transform .1s;
  box-shadow:0 4px 20px rgba(79,70,229,.4)}}
.dlbtn:hover{{opacity:.9;transform:translateY(-1px)}}
.dlbtn:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
/* Footer */
.footer{{margin-top:20px;font-size:11px;color:#3d4555;display:flex;align-items:center;justify-content:center;gap:5px}}
.footer svg{{opacity:.4}}
</style>
</head>
<body>
<div class="card">

  <!-- Logo -->
  <div class="sc-logo">
    <svg class="sc-logo-mark" viewBox="0 0 38 22" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z"
            stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/>
      <path d="M11 8.5a3.5 3.5 0 012.2-3.2"
            stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".35"/>
    </svg>
    SAFE CLOUD
  </div>

  <!-- Ikona pliku -->
  <div class="file-icon-wrap">
    {file_icon_svg}
  </div>

  <div class="fname">{fname_esc}</div>
  <div class="fsize">{fsize_esc}</div>

  <div class="sep"></div>

  {expires_line}
  {timer_block}

  <a class="dlbtn" id="dlbtn" href="/dl/{token}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" width="16" height="16">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
      <polyline points="7 10 12 15 17 10"/>
      <line x1="12" y1="15" x2="12" y2="3"/>
    </svg>
    Pobierz plik
  </a>

  <div class="footer">
    <svg viewBox="0 0 38 22" width="18" height="11" fill="none">
      <path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z"
            stroke="#818cf8" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/>
    </svg>
    Udost\u0119pniono przez SAFE CLOUD
  </div>
</div>
<script>{countdown_js}</script>
{BG_ANIMATION_JS}
</body>
</html>"""
                self.send_html(page)
                return

            # ── Faktyczne pobranie pliku przez link ──────
            if p.path.startswith("/dl/"):
                token = p.path[4:]
                share = get_share(token)
                if not share:
                    self.send_html("<html><body style='font-family:sans-serif;background:#09090b;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>\u274c Link wygas\u0142 lub nie istnieje</h2></div></body></html>", 410)
                    return
                owner_dir = user_storage(share["owner"])
                fpath = safe_path(owner_dir, share["path"])
                if not fpath or not fpath.is_file():
                    self.send_html("<html><body style='font-family:sans-serif;background:#09090b;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center'><h2>\u274c Plik nie istnieje</h2></div></body></html>", 404)
                    return
                delete_share(token)
                print(f"[SHARE] Pobrano: {share['name']} (w\u0142a\u015bciciel: {share['owner']}, IP: {self.client_address[0]})")
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

            if p.path == "/2fa/setup":
                username = self.require_auth()
                if not username: return
                secret = totp_generate_secret()
                uri    = totp_get_uri(username, secret)
                self.send_json({"ok": True, "secret": secret, "uri": uri,
                                "enabled": totp_is_enabled(username)})
                return

            if p.path == "/stats":
                if not (is_admin(username) or is_owner(username) or is_moderator(username)):
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
                fname_disp = urllib.parse.quote(target.name)

                range_header = self.headers.get("Range", "")
                if range_header and range_header.startswith("bytes="):
                    # ── HTTP Range Request (strumieniowanie wideo) ──
                    try:
                        rng = range_header[6:]
                        start_s, end_s = rng.split("-", 1)
                        start = int(start_s) if start_s else 0
                        end   = int(end_s)   if end_s   else size - 1
                        end   = min(end, size - 1)
                        if start > end or start >= size:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{size}")
                            self.end_headers(); return
                        chunk = end - start + 1
                        self.send_response(206)
                        self.send_header("Content-Type", mime)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.send_header("Content-Length", str(chunk))
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Disposition", f'inline; filename*=UTF-8\'\'{fname_disp}')
                        self.end_headers()
                        with open(target, "rb") as f:
                            f.seek(start)
                            remaining = chunk
                            while remaining > 0:
                                buf = f.read(min(65536, remaining))
                                if not buf: break
                                self.wfile.write(buf)
                                remaining -= len(buf)
                    except Exception:
                        self.send_response(400); self.end_headers()
                else:
                    # ── Pełny plik ──
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(size))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Disposition", f'inline; filename*=UTF-8\'\'{fname_disp}')
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
                stored = get_user_password(users, uname) if uname in users else None
                ok, new_hash = verify_password(pw, stored) if stored else (False, None)
                if ok:
                    # Migracja hasła ze starego SHA-256 do PBKDF2
                    if new_hash:
                        if isinstance(users[uname], dict):
                            users[uname]["password"] = new_hash
                        else:
                            users[uname] = {"password": new_hash, "role": None}
                        save_users(users)
                    ban = get_ban(uname)
                    if ban:
                        reason = ban.get("reason", "Brak powodu.")
                        human  = ban.get("human", "")
                        msg = f"Twoje konto jest zablokowane ({human}). Powód: {reason}"
                        self.send_html(self.auth_page(msg, "login"))
                        return
                    # Sprawdź 2FA
                    if totp_is_enabled(uname):
                        pending = totp_pending_create(uname)
                        self.send_html(self.totp_page(pending))
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
                if uname.lower() == ADMIN_USER.lower():
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
                # Pokaż stronę z pytaniem o 2FA zamiast od razu przekierowywać
                page = self.setup_2fa_prompt_page(token)
                b = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(b)
                return

            if p.path == "/totp-verify":
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                pending = data.get("pending", "")
                code    = data.get("code", "").strip().replace(" ", "")
                uname   = totp_pending_get(pending)
                if not uname:
                    self.send_html(self.auth_page("Sesja weryfikacji wygasła. Zaloguj się ponownie.", "login"))
                    return
                secret = totp_get_secret(uname)
                if not secret or not totp_verify(secret, code):
                    self.send_html(self.totp_page(pending, error="Nieprawidłowy kod. Spróbuj ponownie."))
                    return
                totp_pending_del(pending)
                token  = create_session(uname)
                cookie = f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                redirect(self, "/", cookie)
                return

            if p.path == "/2fa/setup-register":
                username = self.require_auth()
                if not username: return
                n    = int(self.headers.get("Content-Length", 0))
                try:
                    data = json.loads(self.rfile.read(n))
                except Exception:
                    self.send_json({"ok": False, "error": "Błąd danych"}); return
                code   = str(data.get("code", "")).strip().replace(" ", "")
                secret = str(data.get("secret", "")).strip()
                if not secret or not code:
                    self.send_json({"ok": False, "error": "Brak danych"}); return
                if not totp_verify(secret, code):
                    self.send_json({"ok": False, "error": "Nieprawidłowy kod — sprawdź czy zegar jest zsynchronizowany"}); return
                totp_enable(username, secret)
                print(f"[2FA] Włączono 2FA dla nowego użytkownika: {username}")
                self.send_json({"ok": True})
                return

            if p.path == "/2fa/setup":
                username = self.require_auth()
                if not username: return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                code   = data.get("code", "").strip().replace(" ", "")
                secret = data.get("secret", "").strip()
                if not secret or not code:
                    self.send_json({"ok": False, "error": "Brak danych"})
                    return
                if not totp_verify(secret, code):
                    self.send_json({"ok": False, "error": "Nieprawidłowy kod — sprawdź czy zegar jest zsynchronizowany"})
                    return
                totp_enable(username, secret)
                self.send_json({"ok": True})
                return

            if p.path == "/2fa/disable":
                username = self.require_auth()
                if not username: return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                pw   = data.get("password", "")
                users = load_users()
                ok, _ = verify_password(pw, get_user_password(users, username) or "")
                if not ok:
                    self.send_json({"ok": False, "error": "Nieprawidłowe hasło"})
                    return
                totp_disable(username)
                self.send_json({"ok": True})
                return

            if p.path == "/settings/change-password":
                username = self.require_auth()
                if not username: return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                old_pw  = data.get("old_password", "")
                new_pw  = data.get("new_password", "")
                new_pw2 = data.get("new_password2", "")
                users = load_users()
                ok, _ = verify_password(old_pw, get_user_password(users, username) or "")
                if not ok:
                    self.send_json({"ok": False, "error": "Nieprawidłowe aktualne hasło"}); return
                if len(new_pw) < 4:
                    self.send_json({"ok": False, "error": "Nowe hasło musi mieć min. 4 znaki"}); return
                if new_pw != new_pw2:
                    self.send_json({"ok": False, "error": "Hasła nie są identyczne"}); return
                v = users[username]
                if isinstance(v, dict): users[username]["password"] = hash_password(new_pw)
                else: users[username] = {"password": hash_password(new_pw), "role": None}
                save_users(users)
                # wyloguj inne sesje
                token_cur = get_token_from_request(self)
                to_del = [t for t,s in sessions.items() if s["username"]==username and t!=token_cur]
                for t in to_del: del sessions[t]
                self.send_json({"ok": True})
                return

            if p.path == "/settings/change-username":
                username = self.require_auth()
                if not username: return
                if is_admin(username) or is_owner(username):
                    self.send_json({"ok": False, "error": "Admin i owner nie mogą zmieniać nazwy"}); return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                new_name = data.get("new_username", "").strip()
                pw       = data.get("password", "")
                users = load_users()
                ok, _ = verify_password(pw, get_user_password(users, username) or "")
                if not ok:
                    self.send_json({"ok": False, "error": "Nieprawidłowe hasło"}); return
                if not new_name or not all(c.isalnum() or c in "_-" for c in new_name):
                    self.send_json({"ok": False, "error": "Niedozwolone znaki w nazwie"}); return
                if len(new_name) > 32:
                    self.send_json({"ok": False, "error": "Nazwa max 32 znaki"}); return
                if new_name in users:
                    self.send_json({"ok": False, "error": "Ta nazwa jest już zajęta"}); return
                if new_name.lower() == ADMIN_USER.lower():
                    self.send_json({"ok": False, "error": "Ta nazwa jest zarezerwowana"}); return
                # przenieś dane
                users[new_name] = users.pop(username)
                save_users(users)
                # przenieś folder
                old_dir = STORAGE_DIR / username
                new_dir = STORAGE_DIR / new_name
                if old_dir.exists(): shutil.move(str(old_dir), str(new_dir))
                # przenieś 2FA
                totp_d = _totp_load()
                if username in totp_d:
                    totp_d[new_name] = totp_d.pop(username)
                    _totp_save(totp_d)
                # wyloguj stare sesje
                to_del = [t for t,s in sessions.items() if s["username"]==username]
                for t in to_del: del sessions[t]
                # zaloguj ponownie z nową nazwą
                new_token = create_session(new_name)
                cookie = f"session={new_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Set-Cookie", cookie)
                resp = json.dumps({"ok": True}).encode()
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return

            if p.path == "/settings/delete-account":
                username = self.require_auth()
                if not username: return
                if is_admin(username) or is_owner(username):
                    self.send_json({"ok": False, "error": "Admin i owner nie mogą usunąć konta"}); return
                n    = int(self.headers.get("Content-Length", 0))
                data = parse_form_body(self.rfile.read(n))
                pw           = data.get("password", "")
                delete_files = data.get("delete_files", "0") == "1"
                users = load_users()
                ok, _ = verify_password(pw, get_user_password(users, username) or "")
                if not ok:
                    self.send_json({"ok": False, "error": "Nieprawidłowe hasło"}); return
                del users[username]
                save_users(users)
                # wyloguj
                to_del = [t for t,s in sessions.items() if s["username"]==username]
                for t in to_del: del sessions[t]
                bans.pop(username, None); save_bans()
                totp_disable(username)
                if delete_files:
                    user_dir = STORAGE_DIR / username
                    if user_dir.exists(): shutil.rmtree(user_dir)
                cookie = "session=; Path=/; Max-Age=0"
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Set-Cookie", cookie)
                resp = json.dumps({"ok": True}).encode()
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
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
                delim      = b"--" + boundary.encode()
                delim_end  = delim + b"--"
                CHUNK      = 256 * 1024  # 256 KB chunks

                # ── Streamingowy parser multipart ────────────────
                # Czyta dane partiami i pisze plik bezpośrednio na
                # dysk — nigdy nie trzyma całego pliku w RAM.

                sub_path = ""
                fname    = None
                out_path = None
                fout     = None
                state    = "PREAMBLE"   # PREAMBLE → HEADERS → FIELD_PATH | FILE_DATA
                buf      = b""
                bytes_read = 0
                error    = None

                def flush_file():
                    nonlocal fout, out_path
                    if fout:
                        try: fout.close()
                        except: pass
                        fout = None

                try:
                    while bytes_read < length:
                        to_read = min(CHUNK, length - bytes_read)
                        chunk   = self.rfile.read(to_read)
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        buf += chunk

                        while True:
                            if state == "PREAMBLE":
                                idx = buf.find(delim)
                                if idx == -1:
                                    buf = buf[-len(delim):]
                                    break
                                buf = buf[idx + len(delim):]
                                if buf.startswith(b"--"):
                                    break  # koniec
                                if buf.startswith(b"\r\n"):
                                    buf   = buf[2:]
                                    state = "HEADERS"
                                else:
                                    break

                            elif state == "HEADERS":
                                end = buf.find(b"\r\n\r\n")
                                if end == -1:
                                    break
                                headers_raw = buf[:end].decode("utf-8", errors="replace")
                                buf = buf[end + 4:]

                                disp = ""
                                for hline in headers_raw.splitlines():
                                    if hline.lower().startswith("content-disposition"):
                                        disp = hline
                                        break
                                field = filename = ""
                                for tok in disp.split(";"):
                                    tok = tok.strip()
                                    if tok.lower().startswith("name="):
                                        field = tok[5:].strip('"\'')
                                    elif tok.lower().startswith("filename="):
                                        filename = tok[9:].strip('"\'')

                                if field == "path":
                                    state = "FIELD_PATH"
                                elif field == "file" and filename:
                                    fname = Path(filename).name
                                    # Przygotuj plik docelowy
                                    tdir = safe_path(udir, sub_path)
                                    if not tdir:
                                        error = "Zla sciezka"
                                        break
                                    tdir.mkdir(parents=True, exist_ok=True)
                                    stem   = Path(fname).stem
                                    suffix = Path(fname).suffix
                                    out_path = tdir / fname
                                    counter = 1
                                    while out_path.exists():
                                        out_path = tdir / f"{stem} ({counter}){suffix}"
                                        counter += 1
                                    fout  = open(out_path, "wb")
                                    state = "FILE_DATA"
                                else:
                                    state = "PREAMBLE"  # nieznane pole — pomiń

                            elif state == "FIELD_PATH":
                                idx = buf.find(b"\r\n" + delim)
                                if idx == -1:
                                    break
                                sub_path = buf[:idx].decode("utf-8", errors="replace").strip("/")
                                buf   = buf[idx + 2 + len(delim):]
                                if buf.startswith(b"--"):
                                    break
                                if buf.startswith(b"\r\n"):
                                    buf   = buf[2:]
                                    state = "HEADERS"
                                else:
                                    state = "PREAMBLE"

                            elif state == "FILE_DATA":
                                sep = b"\r\n" + delim
                                idx = buf.find(sep)
                                if idx != -1:
                                    # Koniec danych pliku
                                    if fout:
                                        fout.write(buf[:idx])
                                    flush_file()
                                    buf   = buf[idx + 2 + len(delim):]
                                    if buf.startswith(b"--"):
                                        break  # koniec requestu
                                    if buf.startswith(b"\r\n"):
                                        buf   = buf[2:]
                                        state = "HEADERS"
                                    else:
                                        state = "PREAMBLE"
                                else:
                                    # Bufor nie zawiera jeszcze separatora —
                                    # pisz bezpiecznie trzymając ogon (len(sep)-1)
                                    safe = len(buf) - len(sep)
                                    if safe > 0:
                                        if fout:
                                            fout.write(buf[:safe])
                                        buf = buf[safe:]
                                    break
                            else:
                                break

                except Exception as e:
                    flush_file()
                    if out_path and out_path.exists():
                        try: out_path.unlink()
                        except: pass
                    return self.send_json({"ok": False, "error": f"Blad uploadu: {e}"})

                flush_file()

                if error:
                    if out_path and out_path.exists():
                        try: out_path.unlink()
                        except: pass
                    return self.send_json({"ok": False, "error": error})

                if not fname or not out_path or not out_path.exists():
                    return self.send_json({"ok": False, "error": "Brak pliku w zadaniu"})

                print(f"[UPLOAD] saved: {out_path}")
                self.send_json({"ok": True, "name": out_path.name})

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
                if not is_admin(username) and not is_owner(username) and not is_moderator(username):
                    return self.send_json({"ok": False, "error": "Brak uprawnień."})
                n    = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n))
                cmd  = data.get("cmd", "").strip()
                result = handle_command(cmd, username) or ""
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
ws_tokens     = {}  # { token: (username, expires) } — jednorazowe tokeny dla WS konsoli
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

def _session_cleanup_loop():
    """Co 5 minut usuwa wygasłe sesje HTTP i konsolowe z pamięci."""
    while True:
        time.sleep(300)
        now = time.time()
        expired_http = [t for t, s in list(sessions.items()) if s["expires"] <= now]
        for t in expired_http:
            sessions.pop(t, None)
        expired_con = [t for t, (u, exp) in list(console_sessions.items()) if exp <= now]
        for t in expired_con:
            console_sessions.pop(t, None)
        # Wyczyść stare IP z rate-limitera
        old_ips = [ip for ip, attempts in list(login_attempts.items())
                   if not attempts or now - max(attempts) > LOGIN_WINDOW_SEC * 2]
        for ip in old_ips:
            login_attempts.pop(ip, None)
        # Wyczyść wygasłe tokeny TOTP pending (2FA w trakcie logowania)
        expired_totp = [t for t, (u, exp) in list(_totp_pending.items()) if now > exp]
        for t in expired_totp:
            _totp_pending.pop(t, None)

def _fmt_bytes(n):
    for u in ["B","KB","MB","GB"]:
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} GB"

_ngrok_proc_cache = None
_disk_io_prev = None   # (timestamp, read_bytes, write_bytes)
_net_io_prev  = None   # (timestamp, bytes_sent, bytes_recv)

def get_stats():
    """Zwraca slownik z aktualnymi statystykami procesu."""
    result = {"ok": False}
    try:
        import psutil, os as _os
        proc = psutil.Process(_os.getpid())
        mem = proc.memory_info()
        try:    conns = len(proc.net_connections())
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
        # Sieć
        try:
            global _net_io_prev
            nio = psutil.net_io_counters()
            now_net = time.time()
            if _net_io_prev is not None:
                prev_nt, prev_s, prev_r = _net_io_prev
                dt_net = now_net - prev_nt
                if dt_net > 0:
                    rate_s = (nio.bytes_sent - prev_s) / dt_net
                    rate_r2 = (nio.bytes_recv - prev_r) / dt_net
                    net_up   = _fmt_bytes(rate_s)   + "/s" if rate_s   > 0 else None
                    net_down = _fmt_bytes(rate_r2)  + "/s" if rate_r2  > 0 else None
                else:
                    net_up = net_down = None
            else:
                net_up = net_down = None
            _net_io_prev = (now_net, nio.bytes_sent, nio.bytes_recv)
        except:
            net_up = net_down = None
        now_t = time.time()
        ram_mb = mem.rss / (1024 * 1024)
        # RAM cloudflared/ngrok
        ngrok_rss = 0
        cloudflared_rss = 0
        try:
            global _ngrok_proc_cache
            proc_ok = False
            if _ngrok_proc_cache:
                try:
                    if _ngrok_proc_cache.is_running():
                        ngrok_rss = _ngrok_proc_cache.memory_info().rss
                        if 'cloudflared' in _ngrok_proc_cache.name().lower():
                            cloudflared_rss = ngrok_rss
                        proc_ok = True
                except: _ngrok_proc_cache = None
            if not proc_ok:
                for p in psutil.process_iter(['name', 'memory_info']):
                    pname = p.info['name'].lower()
                    if 'cloudflared' in pname:
                        _ngrok_proc_cache = p
                        ngrok_rss = p.info['memory_info'].rss
                        cloudflared_rss = ngrok_rss
                        break
                    elif 'ngrok' in pname:
                        _ngrok_proc_cache = p
                        ngrok_rss = p.info['memory_info'].rss
                        break
        except: pass
        total_rss = mem.rss
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
            "cloudflared_ram": _fmt_bytes(cloudflared_rss) if cloudflared_rss else "—",
            "net_up":   net_up,
            "net_down": net_down,
        }
    except ImportError:
        result = {"ok": False, "error": "psutil niedostepny"}
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    return result

RAM_WARN_MB    = 100   # poziom ostrzeżenia (było 150)
RAM_CLEAN_MB   = 150   # agresywne czyszczenie (było 200)
RAM_RESTART_MB = 250   # restart serwera (było 280)

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

    # 4. Przy RAM_CLEAN_MB: wyczyść 50% cache miniaturek (najstarsze LRU)
    global _cache_total_bytes
    if ram_mb >= RAM_CLEAN_MB and thumb_cache:
        before = len(thumb_cache)
        remove_n = len(thumb_cache) // 2
        for _ in range(remove_n):
            if not thumb_cache: break
            _, (_, evicted) = thumb_cache.popitem(last=False)
            _cache_total_bytes -= len(evicted)
        actions.append(f"cache thumb: -{before - len(thumb_cache)}")

    # 5. Przy RAM_RESTART_MB: wyczyść cały cache
    if ram_mb >= RAM_RESTART_MB and thumb_cache:
        before = len(thumb_cache)
        thumb_cache.clear()
        _cache_total_bytes = 0
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
                    import sys, os as _os2, subprocess as _sp2
                    try:
                        if sys.platform == "win32":
                            _sp2.Popen([sys.executable] + sys.argv, creationflags=0x00000010, close_fds=True)
                        else:
                            _sp2.Popen([sys.executable] + sys.argv, start_new_session=True)
                    except Exception:
                        pass
                    _os2._exit(0)

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
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){
  function makeFavicon(){
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }
  function init(){
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init);}else{init();}
})();
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">

<script>
(function(){
  try{
    var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!_s) return;
    var _DK={'Niebieski':{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},'Zielony':{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},'Czerwony':{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},'Fioletowy':{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},'Mono':{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},'Różowy':{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}};
    var _LT={'Niebieski':{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},'Zielony':{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},'Czerwony':{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},'Fioletowy':{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},'Mono':{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},'Różowy':{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}};
    var _mode=_s.mode||'dark', _name=_s.name||'Mono';
    var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
    var r=document.documentElement;
    r.style.setProperty('--acc',  t.acc);
    r.style.setProperty('--acc2', t.acc2);
    r.style.setProperty('--bg',   t.bg);
    r.style.setProperty('--sur',  t.sur);
    r.style.setProperty('--brd',  t.brd);
    r.style.setProperty('--txt',  t.txt||'#e6edf3');
    r.style.setProperty('--muted',t.muted||'#7d8590');
    r.style.setProperty('--gr1',  t.gr1);
    r.style.setProperty('--gr2',  t.gr2);
    r.style.setProperty('--gr3',  t.gr3);
    r.style.setProperty('--gr4',  t.gr4);
    r.classList.toggle('theme-mono', _name==='Mono');
    r.classList.toggle('theme-light', _mode==='light');
  }catch(e){}
})();
</script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;--green:#3fb950;--yellow:#e3b341;--red:#f85149}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);height:100vh;display:flex;flex-direction:column;overflow:hidden;position:relative}
header{background:rgba(17,24,39,.95);border-bottom:1px solid var(--brd);padding:0 20px;height:52px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;position:relative;z-index:10}
.logo{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px;font-family:'Audiowide',sans-serif;letter-spacing:.04em}
.lm{width:28px;height:28px;border-radius:7px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.hright{display:flex;align-items:center;gap:12px}
.status{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--red);transition:background .3s}
.dot.on{background:var(--green);box-shadow:0 0 6px var(--green)}
.btn{font-family:inherit;font-size:12px;font-weight:500;padding:5px 12px;border-radius:7px;cursor:pointer;border:1px solid var(--brd);background:var(--sur);color:var(--txt);transition:all .15s}
.btn:hover{background:color-mix(in srgb,var(--acc) 8%,var(--sur));border-color:var(--acc)}
.btn-red{border-color:#6e3535;color:var(--red)}
.btn-red:hover{background:rgba(248,81,73,.1)}
.toolbar{display:flex;align-items:center;gap:8px;padding:8px 16px;background:var(--sur);border-bottom:1px solid var(--brd);flex-shrink:0}
.tl{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-right:4px}
.filter-btn{font-family:inherit;font-size:11px;font-weight:500;padding:3px 10px;border-radius:5px;cursor:pointer;border:1px solid var(--brd);background:transparent;color:var(--muted);transition:all .15s}
.filter-btn.active{background:var(--bg);color:var(--txt);border-color:#2d3a52}
.filter-btn:hover{color:var(--txt)}
#console{flex:1;overflow-y:auto;padding:12px 0;font-family:'JetBrains Mono',monospace;font-size:12.5px;line-height:1.7;background:var(--bg);position:relative;z-index:1}
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
.cmd-send:hover{background:var(--acc2);border-color:var(--acc2);color:var(--bg)}
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
  <div class="logo"><div class="lm"><svg viewBox="0 0 38 22" width="22" height="13" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/></svg></div>Konsola – SAFE CLOUD</div>
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
      <div class="stat">Net &#x2191; &ndash; <span class="stat-val" id="st-nup">&mdash;</span></div>
      <span class="stat-inner-sep">&middot;</span>
      <div class="stat">Net &#x2193; &ndash; <span class="stat-val" id="st-ndw">&mdash;</span></div>
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
  const host=window.location.hostname;
  ws=new WebSocket('ws://'+host+':PORT_WS/ws');
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
    const r=await fetch('http://'+window.location.hostname+':PORT_WS/stats');
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
      document.getElementById('st-nup').textContent=d.net_up||'—';
      document.getElementById('st-ndw').textContent=d.net_down||'—';
      document.getElementById('st-cache').textContent=d.cache;
      document.getElementById('st-ses').textContent=d.sessions;
    }
  }catch(e){}
}
fetchStats();
setInterval(fetchStats,3000);
connect();
</script>
""" + BG_ANIMATION_JS + """
</body>
</html>"""

CONSOLE_SESSIONS_FILE = Path("./console_sessions.json")
console_sessions = {}  # { token: (username, expires) }

def _load_console_sessions():
    """Wczytaj sesje konsoli z pliku przy starcie."""
    global console_sessions
    if not CONSOLE_SESSIONS_FILE.exists():
        return
    try:
        raw = json.loads(CONSOLE_SESSIONS_FILE.read_text(encoding="utf-8"))
        now = time.time()
        # Odfiltruj wygasłe
        console_sessions = {t: tuple(v) for t, v in raw.items() if v[1] > now}
    except: pass

def _save_console_sessions():
    """Zapisz sesje konsoli do pliku."""
    try:
        now = time.time()
        active = {t: list(v) for t, v in console_sessions.items() if v[1] > now}
        CONSOLE_SESSIONS_FILE.write_text(json.dumps(active, indent=2), encoding="utf-8")
    except: pass

def create_console_session(username):
    token = secrets.token_hex(32)
    console_sessions[token] = (username, time.time() + SESSION_TTL)
    _save_console_sessions()
    return token

def get_console_session(token):
    if not token:
        return None
    entry = console_sessions.get(token)
    if not entry:
        return None
    username, expires = entry
    if time.time() > expires:
        del console_sessions[token]
        _save_console_sessions()
        return None
    # Odnów TTL w pamięci (zapis przy następnym create/delete lub co jakiś czas)
    console_sessions[token] = (username, time.time() + SESSION_TTL)
    return username

CONSOLE_LOGIN_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<title>Konsola – logowanie</title>
<link rel="icon" id="dyn-favicon" type="image/svg+xml" href="">
<script>
(function(){
  function makeFavicon(){
    var acc=getComputedStyle(document.documentElement).getPropertyValue('--acc').trim()||'#e2e8f0';
    var svg='<svg viewBox="0 0 38 22" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="'+acc+'" stroke-width="1.6" stroke-linejoin="round" fill="'+acc+'22"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="'+acc+'" stroke-width="1.1" stroke-linecap="round" opacity=".4"/></svg>';
    var el=document.getElementById('dyn-favicon');
    if(el) el.href='data:image/svg+xml,'+encodeURIComponent(svg);
  }
  function init(){
    makeFavicon();
    new MutationObserver(makeFavicon).observe(document.documentElement,{attributes:true,attributeFilter:['style','class']});
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',init);}else{init();}
})();
</script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Audiowide&display=swap" rel="stylesheet">

<script>
(function(){
  try{
    var _s=JSON.parse(localStorage.getItem('sc_theme')||'null');
    if(!_s) return;
    var _DK={'Niebieski':{acc:'#818cf8',acc2:'#4f46e5',bg:'#0a0c14',sur:'#111827',brd:'#1e2535',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(79,70,229,.55)',gr2:'rgba(109,40,217,.30)',gr3:'rgba(67,56,202,.28)',gr4:'rgba(124,58,237,.20)'},'Zielony':{acc:'#34d399',acc2:'#059669',bg:'#091410',sur:'#0f1f1a',brd:'#1a3028',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(5,150,105,.50)',gr2:'rgba(4,120,87,.28)',gr3:'rgba(6,95,70,.25)',gr4:'rgba(20,83,45,.18)'},'Czerwony':{acc:'#f87171',acc2:'#dc2626',bg:'#110a0a',sur:'#1e1010',brd:'#2e1a1a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(220,38,38,.50)',gr2:'rgba(185,28,28,.28)',gr3:'rgba(153,27,27,.25)',gr4:'rgba(127,29,29,.18)'},'Fioletowy':{acc:'#c084fc',acc2:'#9333ea',bg:'#0d0a14',sur:'#180f27',brd:'#2a1a40',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(147,51,234,.55)',gr2:'rgba(126,34,206,.30)',gr3:'rgba(107,33,168,.28)',gr4:'rgba(88,28,135,.20)'},'Mono':{acc:'#e2e8f0',acc2:'#94a3b8',bg:'#09090b',sur:'#18181b',brd:'#27272a',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(148,163,184,.22)',gr2:'rgba(100,116,139,.12)',gr3:'rgba(71,85,105,.10)',gr4:'rgba(51,65,85,.08)'},'Różowy':{acc:'#f472b6',acc2:'#db2777',bg:'#11080d',sur:'#1e0f18',brd:'#2e1a26',txt:'#e6edf3',muted:'#7d8590',gr1:'rgba(219,39,119,.50)',gr2:'rgba(190,24,93,.28)',gr3:'rgba(157,23,77,.25)',gr4:'rgba(131,24,67,.18)'}};
    var _LT={'Niebieski':{acc:'#4f46e5',acc2:'#3730a3',bg:'#f0f2ff',sur:'#ffffff',brd:'#dde1f0',txt:'#1a1f36',muted:'#6b7280',gr1:'rgba(79,70,229,.12)',gr2:'rgba(109,40,217,.07)',gr3:'rgba(67,56,202,.06)',gr4:'rgba(124,58,237,.05)'},'Zielony':{acc:'#059669',acc2:'#047857',bg:'#f0faf6',sur:'#ffffff',brd:'#d1f0e6',txt:'#0f2a1f',muted:'#6b7280',gr1:'rgba(5,150,105,.10)',gr2:'rgba(4,120,87,.06)',gr3:'rgba(6,95,70,.05)',gr4:'rgba(20,83,45,.04)'},'Czerwony':{acc:'#dc2626',acc2:'#b91c1c',bg:'#fff0f0',sur:'#ffffff',brd:'#f0d5d5',txt:'#2a0a0a',muted:'#6b7280',gr1:'rgba(220,38,38,.10)',gr2:'rgba(185,28,28,.06)',gr3:'rgba(153,27,27,.05)',gr4:'rgba(127,29,29,.04)'},'Fioletowy':{acc:'#9333ea',acc2:'#7c3aed',bg:'#f5f0ff',sur:'#ffffff',brd:'#e2d5f5',txt:'#1a0a2e',muted:'#6b7280',gr1:'rgba(147,51,234,.10)',gr2:'rgba(126,34,206,.06)',gr3:'rgba(107,33,168,.05)',gr4:'rgba(88,28,135,.04)'},'Mono':{acc:'#334155',acc2:'#1e293b',bg:'#f8fafc',sur:'#ffffff',brd:'#e2e8f0',txt:'#0f172a',muted:'#64748b',gr1:'rgba(148,163,184,.15)',gr2:'rgba(100,116,139,.08)',gr3:'rgba(71,85,105,.06)',gr4:'rgba(51,65,85,.04)'},'Różowy':{acc:'#db2777',acc2:'#be185d',bg:'#fff0f7',sur:'#ffffff',brd:'#f0d5e8',txt:'#2a0a18',muted:'#6b7280',gr1:'rgba(219,39,119,.10)',gr2:'rgba(190,24,93,.06)',gr3:'rgba(157,23,77,.05)',gr4:'rgba(131,24,67,.04)'}};
    var _mode=_s.mode||'dark', _name=_s.name||'Mono';
    var t=(_mode==='light'?_LT:_DK)[_name]||(_mode==='light'?_LT:_DK)['Mono'];
    var r=document.documentElement;
    r.style.setProperty('--acc',  t.acc);
    r.style.setProperty('--acc2', t.acc2);
    r.style.setProperty('--bg',   t.bg);
    r.style.setProperty('--sur',  t.sur);
    r.style.setProperty('--brd',  t.brd);
    r.style.setProperty('--txt',  t.txt||'#e6edf3');
    r.style.setProperty('--muted',t.muted||'#7d8590');
    r.style.setProperty('--gr1',  t.gr1);
    r.style.setProperty('--gr2',  t.gr2);
    r.style.setProperty('--gr3',  t.gr3);
    r.style.setProperty('--gr4',  t.gr4);
    r.classList.toggle('theme-mono', _name==='Mono');
    r.classList.toggle('theme-light', _mode==='light');
  }catch(e){}
})();
</script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#09090b;--sur:#18181b;--brd:#27272a;--txt:#e6edf3;--muted:#7d8590;--acc:#e2e8f0;--acc2:#94a3b8;--red:#f85149}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;background-image:none}
.card{background:var(--sur);border:1px solid var(--brd);border-radius:16px;padding:36px 32px;width:100%;max-width:360px;box-shadow:0 20px 60px rgba(0,0,0,.5);position:relative;z-index:1}
.logo{display:flex;align-items:center;justify-content:center;gap:10px;font-weight:700;font-size:18px;margin-bottom:8px;font-family:'Audiowide',sans-serif;letter-spacing:.04em}
.sub{text-align:center;font-size:12px;color:var(--muted);margin-bottom:28px}
label{display:block;font-size:12px;font-weight:500;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em}
input{width:100%;padding:10px 13px;border:1px solid var(--brd);border-radius:8px;font-family:inherit;font-size:14px;color:var(--txt);background:var(--bg);outline:none;margin-bottom:16px;transition:border-color .15s}
input:focus{border-color:var(--acc)}
.submit{width:100%;padding:11px;border:none;border-radius:8px;background:var(--acc2);color:#e0e7ff;font-family:inherit;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s}
.submit:hover{background:#4338ca}
.err{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.4);color:var(--red);border-radius:8px;padding:10px 13px;font-size:13px;margin-bottom:14px;display:%%ERR%%}
</style>
</head>
<body>
<div class="card">
  <div class="logo"><svg viewBox="0 0 38 22" width="22" height="13" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M30 17H9a5 5 0 01-.6-10 7 7 0 0113.5-2A4 4 0 0130 8.5a4.25 4.25 0 010 8.5z" stroke="var(--acc)" stroke-width="1.6" stroke-linejoin="round" fill="rgba(129,140,248,0.08)"/><path d="M11 8.5a3.5 3.5 0 012.2-3.2" stroke="var(--acc)" stroke-width="1.1" stroke-linecap="round" opacity=".3"/></svg>SAFE CLOUD</div>
  <div class="sub">Konsola administracyjna</div>
  <div class="err">%%ERRMSG%%</div>
  <form method="POST" action="/login">
    <label>Nazwa użytkownika</label>
    <input name="username" type="text" autocomplete="username" autofocus>
    <label>Hasło</label>
    <input name="password" type="password" autocomplete="current-password">
    <button class="submit" type="submit">Zaloguj się</button>
  </form>
</div>
""" + BG_ANIMATION_JS + """
</body>
</html>"""


class ConsoleHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _get_session_user(self):
        cookie = self.headers.get("Cookie", "")
        token = next((p.strip()[9:] for p in cookie.split(";") if p.strip().startswith("csession=")), None)
        return get_console_session(token) if token else None

    def _set_cookie(self, token):
        return f"csession={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL}"

    def _send_html(self, content, code=200, extra_headers=None):
        b = content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path)

        if p.path == "/ws" and self.headers.get("Upgrade","").lower() == "websocket":
            caller_username = self._get_session_user()
            if not caller_username:
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
                    result = handle_command(cmd, caller_username)
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
            if not self._get_session_user():
                self.send_response(403); self.end_headers(); return
            data = json.dumps(get_stats()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if p.path == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "csession=; Path=/; Max-Age=0")
            self.send_header("Location", "/")
            self.end_headers()
            return

        if p.path in ("/", ""):
            username = self._get_session_user()
            if not username:
                self._send_html(CONSOLE_LOGIN_HTML.replace("%%ERR%%","none").replace("%%ERRMSG%%",""))
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

    def do_POST(self):
        p = urllib.parse.urlparse(self.path)
        if p.path == "/login":
            n = int(self.headers.get("Content-Length", 0))
            data = parse_form_body(self.rfile.read(n))
            uname = data.get("username", "").strip()
            pw    = data.get("password", "")
            users = load_users()
            stored_con = get_user_password(users, uname) if uname in users else None
            ok_con, new_hash_con = verify_password(pw, stored_con) if stored_con else (False, None)
            if ok_con and (is_admin(uname) or is_owner(uname)):
                if new_hash_con:
                    if isinstance(users[uname], dict): users[uname]["password"] = new_hash_con
                    else: users[uname] = {"password": new_hash_con, "role": None}
                    save_users(users)
                token = create_console_session(uname)
                self.send_response(302)
                self.send_header("Set-Cookie", self._set_cookie(token))
                self.send_header("Location", "/")
                self.end_headers()
                return
            page = CONSOLE_LOGIN_HTML.replace("%%ERR%%","block").replace("%%ERRMSG%%","Nieprawidłowe dane lub brak uprawnień.")
            self._send_html(page)
            return
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    admin_pass = ensure_admin()
    _current_admin_pass = admin_pass
    _load_console_sessions()

    t = threading.Thread(target=broadcast_logs, daemon=True)
    t.start()

    sc = threading.Thread(target=_session_cleanup_loop, daemon=True)
    sc.start()

    rl = threading.Thread(target=ram_limiter, daemon=True)
    rl.start()

    # ── AUTO BACKUP ───────────────────────────────────
    ab = threading.Thread(target=auto_backup_loop, daemon=True)
    ab.start()
    print(f"[BACKUP] Autobackup włączony — co {BACKUP_INTERVAL//3600}h, max {BACKUP_MAX_KEEP} kopii w ./backups/")
    # ──────────────────────────────────────────────────
    def start_cloudflared():
        import subprocess, psutil as _psu, shutil, os as _os
        # Sprawdź czy cloudflared już działa
        for p in _psu.process_iter(['name']):
            if 'cloudflared' in p.info['name'].lower():
                print(f"[CLOUDFLARED] Już działa (PID {p.pid})")
                return
        # Znajdź cloudflared — najpierw w PATH, potem w typowych lokalizacjach
        cfd_exe = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
        if not cfd_exe and sys.platform == "win32":
            candidates = [
                _os.path.expandvars(r"%ProgramFiles%\cloudflared\cloudflared.exe"),
                _os.path.expandvars(r"%LocalAppData%\cloudflared\cloudflared.exe"),
                _os.path.expandvars(r"%LocalAppData%\Microsoft\WinGet\Packages\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"),
                r"C:\Program Files\cloudflared\cloudflared.exe",
                r"C:\ProgramData\chocolatey\bin\cloudflared.exe",
                _os.path.join(_os.path.expanduser("~"), "cloudflared.exe"),
                _os.path.join(_os.path.expanduser("~"), "Downloads", "cloudflared.exe"),
                _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "cloudflared.exe"),
            ]
            for c in candidates:
                if _os.path.isfile(c):
                    cfd_exe = c
                    break
        if not cfd_exe:
            print("[CLOUDFLARED] ✗ Nie znaleziono cloudflared — umieść cloudflared.exe w tym samym folderze co StartUp.py")
            return
        # Uruchom cloudflared
        try:
            cmd = [cfd_exe, "tunnel", "run", "--url", f"http://127.0.0.1:{PORT}", "safecloud"]
            if sys.platform == "win32":
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            print(f"[CLOUDFLARED] Uruchomiono (PID {proc.pid}) — {cfd_exe}")
        except Exception as e:
            print(f"[CLOUDFLARED] ✗ Błąd uruchomienia: {e}")

    import sys as _sys_cf
    import sys
    try:
        import psutil as _check_psu
        cfd_thread = threading.Thread(target=start_cloudflared, daemon=True)
        cfd_thread.start()
    except ImportError:
        print("[CLOUDFLARED] ✗ Brak psutil — nie można sprawdzić czy cloudflared działa")
    # ──────────────────────────────────────────────────────

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