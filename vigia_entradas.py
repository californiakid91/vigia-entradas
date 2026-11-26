#!/usr/bin/env python3
"""
Vigía de entradas – España vs Francia (UEFA Nations League)
Comprueba la página de tickets.rfef.es y avisa por correo (Gmail) cuando:
  - aparecen palabras de compra ("comprar", "añadir al carrito"...)  -> aviso URGENTE
  - el texto de la página cambia de forma relevante                -> aviso normal
  - la web falla o bloquea varias veces seguidas                   -> aviso de error

Uso:
  python3 vigia_entradas.py --once            # una comprobación (GitHub Actions)
  python3 vigia_entradas.py --intervalo 60    # bucle cada 60 s (tu ordenador)
  python3 vigia_entradas.py --test-aviso      # manda un correo de prueba

Variables de entorno:
  GMAIL_USER          (obligatoria) tu dirección de Gmail, que envía el correo
  GMAIL_APP_PASSWORD  (obligatoria) contraseña de aplicación de Google (16 letras)
  EMAIL_TO            (opcional)    destinatario; por defecto, el mismo Gmail
  URL                 (opcional)    página a vigilar
Solo usa la biblioteca estándar de Python 3.8+.
"""
import argparse, hashlib, html, json, os, re, sys, time, difflib
import urllib.request, urllib.error, smtplib
from email.message import EmailMessage
from datetime import datetime, timezone

URL = os.environ.get("URL", "https://tickets.rfef.es/evento/espana-francia-uefa-nations-league/")
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
EMAIL_TO = os.environ.get("EMAIL_TO", "").strip() or GMAIL_USER
ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")

PALABRAS_COMPRA = [
    "comprar", "compra tus entradas", "comprar entradas", "añadir al carrito",
    "anadir al carrito", "seleccionar entradas", "elige tus entradas",
    "selecciona tu zona", "ir a la compra", "add to cart", "buy tickets",
    "cola virtual", "sala de espera",
]
PALABRAS_NO_DISPONIBLE = [
    "próximamente", "proximamente", "agotad", "no disponible", "sold out",
    "venta no iniciada", "fuera de venta",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


def ahora():
    return datetime.now(timezone.utc).astimezone().strftime("%d/%m %H:%M:%S")


def descargar(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-ES,es;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def texto_visible(pagina):
    p = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", pagina)
    p = re.sub(r"(?is)<!--.*?-->", " ", p)
    # conserva el texto de botones/enlaces y los value/aria-label de inputs
    extras = re.findall(r'(?i)(?:value|aria-label|title)\s*=\s*"([^"]{2,80})"', p)
    p = re.sub(r"(?s)<[^>]+>", "\n", p)
    p = html.unescape(p) + "\n" + "\n".join(extras)
    lineas = [re.sub(r"\s+", " ", l).strip() for l in p.splitlines()]
    # quita líneas vacías y ruido típico (horas, tokens largos)
    limpias = [l for l in lineas if l and not re.fullmatch(r"[\w\-]{30,}", l)]
    return "\n".join(limpias)


def buscar(texto, palabras):
    t = texto.lower()
    return sorted({w for w in palabras if w in t})


def cargar_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def guardar_estado(e):
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)


def avisar(titulo, mensaje, prioridad="default", etiquetas=""):
    print(f"[{ahora()}] AVISO: {titulo} | {mensaje[:200]}")
    if not (GMAIL_USER and GMAIL_APP_PASSWORD):
        print("  (GMAIL_USER / GMAIL_APP_PASSWORD no configurados: aviso solo en pantalla)")
        return
    msg = EmailMessage()
    msg["Subject"] = titulo
    msg["From"] = f"Vigía entradas <{GMAIL_USER}>"
    msg["To"] = EMAIL_TO
    if prioridad in ("urgent", "high"):
        msg["X-Priority"] = "1"
        msg["Importance"] = "High"
    msg.set_content(f"{mensaje}\n\nAbrir la página: {URL}\n\n({ahora()})")
    msg.add_alternative(
        f"<p style='font-size:16px'>{html.escape(mensaje)}</p>"
        f"<p><a href='{URL}' style='display:inline-block;padding:12px 20px;background:#c60b1e;"
        f"color:#fff;border-radius:8px;text-decoration:none;font-weight:bold'>Abrir entradas</a></p>"
        f"<p style='color:#888;font-size:12px'>{ahora()}</p>", subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
    except Exception as ex:
        print(f"  Error enviando correo: {ex}")


def comprobar():
    e = cargar_estado()
    try:
        status, pagina = descargar(URL)
    except urllib.error.HTTPError as ex:
        status, pagina = ex.code, ""
    except Exception as ex:
        status, pagina = 0, ""
        print(f"[{ahora()}] Error de conexión: {ex}")

    if status != 200 or not pagina:
        e["fallos"] = e.get("fallos", 0) + 1
        print(f"[{ahora()}] Fallo HTTP {status} ({e['fallos']} seguidos)")
        if e["fallos"] == 3:   # avisa una sola vez por racha de fallos
            avisar("⚠️ Vigía: la web no responde",
                   f"HTTP {status} 3 veces seguidas. Puede ser caída, cola virtual o bloqueo anti-bots. Mírala a mano.",
                   "high", "warning")
        guardar_estado(e)
        return

    if e.get("fallos", 0) >= 3:
        avisar("✅ Vigía: la web vuelve a responder", "Sigo vigilando.", "low", "white_check_mark")
    e["fallos"] = 0

    texto = texto_visible(pagina)
    huella = hashlib.sha256(texto.encode()).hexdigest()
    compra = buscar(texto, PALABRAS_COMPRA)
    no_disp = buscar(texto, PALABRAS_NO_DISPONIBLE)
    print(f"[{ahora()}] OK · compra={compra or '-'} · no_disponible={no_disp or '-'}")

    primera = "huella" not in e
    if primera:
        avisar("👀 Vigía activado",
               f"Vigilando la página. Ahora mismo: compra={', '.join(compra) or 'nada'}; "
               f"no disponible={', '.join(no_disp) or 'nada'}.", "low", "eyes")
    else:
        nuevas = [w for w in compra if w not in e.get("compra", [])]
        if nuevas:
            avisar("🚨 ¡ENTRADAS! España–Francia",
                   f"Han aparecido en la página: {', '.join(nuevas)}. ¡Entra ya!",
                   "urgent", "rotating_light,soccer")
        elif huella != e.get("huella"):
            antes = e.get("texto", "").splitlines()
            diff = [l[1:] for l in difflib.unified_diff(antes, texto.splitlines(), lineterm="", n=0)
                    if l.startswith("+") and not l.startswith("+++")]
            resumen = " · ".join(diff)[:300] or "(cambios menores)"
            avisar("🔔 Cambio en la página de entradas", f"Nuevo texto: {resumen}", "high", "bell")

    e.update(huella=huella, compra=compra, no_disp=no_disp, texto=texto[:20000],
             ultima=datetime.now(timezone.utc).isoformat())
    guardar_estado(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre comprobaciones")
    ap.add_argument("--test-aviso", action="store_true")
    a = ap.parse_args()
    if a.test_aviso:
        avisar("🧪 Prueba del vigía", "Si ves esto en el móvil, los avisos funcionan.", "high", "test_tube")
        return
    if a.once:
        comprobar()
        return
    print(f"Vigilando {URL} cada {a.intervalo}s. Ctrl+C para parar.")
    while True:
        comprobar()
        time.sleep(max(20, a.intervalo))


if __name__ == "__main__":
    sys.exit(main())
