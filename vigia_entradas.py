#!/usr/bin/env python3
"""
Vigía de entradas – España vs Francia (UEFA Nations League, cuartos, marzo 2027)

Hace dos comprobaciones y avisa por correo (Gmail):
  1) NOTICIAS de rfef.es (Selección Absoluta + portada de noticias):
       - noticia nueva que hable de entradas y de Francia/Nations/cuartos -> URGENTE
       - cualquier otra noticia nueva sobre entradas o sobre Francia      -> aviso normal
  2) PÁGINA DEL EVENTO en tickets.rfef.es:
       - aparecen palabras de compra ("comprar", "cola virtual"...)      -> URGENTE
       - cambia el texto de la página                                   -> aviso normal
     (Esta web bloquea a GitHub con HTTP 403: en ese caso avisa UNA sola vez
      y sigue funcionando el vigilante de noticias.)

Uso:
  python3 vigia_entradas.py --once            # una comprobación (GitHub Actions)
  python3 vigia_entradas.py --intervalo 60    # bucle cada 60 s (ordenador)
  python3 vigia_entradas.py --test-aviso      # manda un correo de prueba

Variables de entorno:
  GMAIL_USER          (obligatoria) tu Gmail, que envía el correo
  GMAIL_APP_PASSWORD  (obligatoria) contraseña de aplicación de Google (16 letras)
  EMAIL_TO            (opcional)    destinatario; por defecto, el mismo Gmail
Solo usa la biblioteca estándar de Python 3.8+.
"""
import argparse, hashlib, html, json, os, re, sys, time, difflib, smtplib
import urllib.request, urllib.error
from email.message import EmailMessage
from datetime import datetime, timezone

URL_EVENTO = os.environ.get("URL", "https://tickets.rfef.es/evento/espana-francia-uefa-nations-league/")
URLS_NOTICIAS = [
    "https://rfef.es/es/noticias/seleccion-absoluta?baseFilters=79393",
    "https://rfef.es/es/noticias",
]
GMAIL_USER = os.environ.get("GMAIL_USER", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
EMAIL_TO = os.environ.get("EMAIL_TO", "").strip() or GMAIL_USER
ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")

PALABRAS_COMPRA = [
    "comprar", "compra tus entradas", "comprar entradas", "añadir al carrito",
    "anadir al carrito", "seleccionar entradas", "elige tus entradas",
    "selecciona tu zona", "ir a la compra", "add to cart", "buy tickets",
    "cola virtual", "sala de espera", "formulario de registro",
]
PALABRAS_NO_DISPONIBLE = [
    "próximamente", "proximamente", "agotad", "no disponible", "sold out",
    "venta no iniciada", "fuera de venta",
]
# Palabras en la URL/título de una noticia
TEMA_ENTRADAS = ["entradas", "localidades", "venta", "tickets", "registro", "formulario"]
TEMA_PARTIDO = ["francia", "nations", "cuartos", "liga-de-naciones", "liga de naciones"]
EXCLUIR_NOTICIA = ["femenin", "sub-", "futbol-sala", "sala", "playa", "ereuropa", "arbitr", "designaciones"]

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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
    except urllib.error.HTTPError as ex:
        return ex.code, ""
    except Exception as ex:
        print(f"[{ahora()}] Error de conexión con {url}: {ex}")
        return 0, ""


def texto_visible(pagina):
    p = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", pagina)
    p = re.sub(r"(?is)<!--.*?-->", " ", p)
    extras = re.findall(r'(?i)(?:value|aria-label|title)\s*=\s*"([^"]{2,80})"', p)
    p = re.sub(r"(?s)<[^>]+>", "\n", p)
    p = html.unescape(p) + "\n" + "\n".join(extras)
    lineas = [re.sub(r"\s+", " ", l).strip() for l in p.splitlines()]
    return "\n".join(l for l in lineas if l and not re.fullmatch(r"[\w\-]{30,}", l))


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


def avisar(titulo, mensaje, prioridad="default", enlace=URL_EVENTO):
    print(f"[{ahora()}] AVISO: {titulo} | {mensaje[:300]}")
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
    msg.set_content(f"{mensaje}\n\nAbrir: {enlace}\nEntradas: {URL_EVENTO}\n\n({ahora()})")
    msg.add_alternative(
        f"<p style='font-size:16px;white-space:pre-line'>{html.escape(mensaje)}</p>"
        f"<p><a href='{enlace}' style='display:inline-block;padding:12px 20px;background:#c60b1e;"
        f"color:#fff;border-radius:8px;text-decoration:none;font-weight:bold'>Abrir</a></p>"
        f"<p><a href='{URL_EVENTO}'>Página de entradas</a></p>"
        f"<p style='color:#888;font-size:12px'>{ahora()}</p>", subtype="html")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            s.send_message(msg)
        print("  Correo enviado.")
    except Exception as ex:
        print(f"  Error enviando correo: {ex}")


# ---------------------------------------------------------------- NOTICIAS
def extraer_noticias(pagina):
    """Devuelve {slug: titulo} de los enlaces /es/noticias/<slug>."""
    res = {}
    for m in re.finditer(r'(?is)<a[^>]+href="(?:https://rfef\.es)?/es/noticias/([a-z0-9\-]+)"[^>]*>(.*?)</a>', pagina):
        slug, titulo = m.group(1), re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        if slug in ("institucional", "labor-federativa", "competiciones-masculinas", "competiciones-femeninas",
                    "arbitros", "seleccion-absoluta", "seleccion-absoluta-femenina", "futbol-sala"):
            continue
        if len(slug) > 15 and (slug not in res or len(titulo) > len(res[slug])):
            res[slug] = titulo
    return res


def clasificar(slug, titulo):
    t = (slug + " " + titulo).lower()
    if any(x in t for x in EXCLUIR_NOTICIA):
        return None
    ent = any(x in t for x in TEMA_ENTRADAS)
    par = any(x in t for x in TEMA_PARTIDO)
    if ent and par:
        return "urgente"
    if ent or "francia" in t:
        return "normal"
    return None


def comprobar_noticias(e):
    vistas = set(e.get("noticias_vistas", []))
    primera = not vistas
    encontradas, fallos = {}, 0
    for url in URLS_NOTICIAS:
        status, pagina = descargar(url)
        if status != 200 or not pagina:
            fallos += 1
            print(f"[{ahora()}] Noticias: fallo HTTP {status} en {url}")
            continue
        encontradas.update(extraer_noticias(pagina))

    if fallos == len(URLS_NOTICIAS):
        e["fallos_noticias"] = e.get("fallos_noticias", 0) + 1
        if e["fallos_noticias"] == 3:
            avisar("⚠️ Vigía: no puedo leer las noticias de rfef.es",
                   "3 fallos seguidos. Revisa a mano https://rfef.es/es/noticias", "high",
                   "https://rfef.es/es/noticias")
        return
    if e.get("fallos_noticias", 0) >= 3:
        avisar("✅ Vigía: vuelvo a leer las noticias", "Sigo vigilando.", "low", "https://rfef.es/es/noticias")
    e["fallos_noticias"] = 0

    print(f"[{ahora()}] Noticias OK · {len(encontradas)} enlaces leídos")
    nuevas = {s: t for s, t in encontradas.items() if s not in vistas}
    relevantes = [(clasificar(s, t), s, t) for s, t in nuevas.items()]
    relevantes = [r for r in relevantes if r[0]]

    if primera:
        ya = [f"• {t or s}" for c, s, t in relevantes]
        avisar("👀 Vigía activado (noticias rfef.es)",
               f"Leo {len(encontradas)} noticias. Te escribiré en cuanto salga una nueva sobre entradas o Francia.\n"
               + ("Ahora mismo ya hay estas relacionadas:\n" + "\n".join(ya) if ya else "Ahora mismo no hay ninguna."),
               "low", "https://rfef.es/es/noticias/seleccion-absoluta?baseFilters=79393")
    else:
        for c, s, t in sorted(relevantes):
            enlace = f"https://rfef.es/es/noticias/{s}"
            if c == "urgente":
                avisar("🚨 ¡NOTICIA DE ENTRADAS! España–Francia",
                       f"{t or s}\nLee fechas, fases y si hay formulario de registro.", "urgent", enlace)
            else:
                avisar("📰 Noticia RFEF: posible info de entradas", t or s, "high", enlace)

    e["noticias_vistas"] = sorted(vistas | set(encontradas))[-3000:]


# ---------------------------------------------------------- PÁGINA EVENTO
def comprobar_evento(e):
    status, pagina = descargar(URL_EVENTO)
    if status != 200 or not pagina:
        e["fallos"] = e.get("fallos", 0) + 1
        print(f"[{ahora()}] Evento: fallo HTTP {status} ({e['fallos']} seguidos)")
        if e["fallos"] == 3 and not e.get("aviso_bloqueo_enviado"):
            avisar("ℹ️ Vigía: la web de entradas bloquea las comprobaciones automáticas",
                   f"tickets.rfef.es responde HTTP {status}. Sigo vigilando las NOTICIAS de rfef.es "
                   "(ahí se anuncian las fechas de venta). Este aviso solo te llega una vez.", "default")
            e["aviso_bloqueo_enviado"] = True
        return
    e["fallos"] = 0

    texto = texto_visible(pagina)
    huella = hashlib.sha256(texto.encode()).hexdigest()
    compra = buscar(texto, PALABRAS_COMPRA)
    no_disp = buscar(texto, PALABRAS_NO_DISPONIBLE)
    print(f"[{ahora()}] Evento OK · compra={compra or '-'} · no_disponible={no_disp or '-'}")

    if "huella" in e:
        nuevas = [w for w in compra if w not in e.get("compra", [])]
        if nuevas:
            avisar("🚨 ¡ENTRADAS! España–Francia",
                   f"Han aparecido en la página: {', '.join(nuevas)}. ¡Entra ya!", "urgent")
        elif huella != e.get("huella"):
            antes = e.get("texto", "").splitlines()
            diff = [l[1:] for l in difflib.unified_diff(antes, texto.splitlines(), lineterm="", n=0)
                    if l.startswith("+") and not l.startswith("+++")]
            avisar("🔔 Cambio en la página de entradas",
                   "Nuevo texto: " + (" · ".join(diff)[:300] or "(cambios menores)"), "high")
    e.update(huella=huella, compra=compra, no_disp=no_disp, texto=texto[:20000])


def comprobar():
    e = cargar_estado()
    comprobar_noticias(e)
    comprobar_evento(e)
    e["ultima"] = datetime.now(timezone.utc).isoformat()
    guardar_estado(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--intervalo", type=int, default=60, help="segundos entre comprobaciones")
    ap.add_argument("--test-aviso", action="store_true")
    a = ap.parse_args()
    if a.test_aviso:
        avisar("🧪 Prueba del vigía", "Si ves esto, los correos funcionan.", "high")
        return
    if a.once:
        comprobar()
        return
    print(f"Vigilando cada {a.intervalo}s. Ctrl+C para parar.")
    while True:
        comprobar()
        time.sleep(max(20, a.intervalo))


if __name__ == "__main__":
    sys.exit(main())
