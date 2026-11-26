#!/usr/bin/env python3
"""
Vigía de entradas – España vs Francia (UEFA Nations League, cuartos, marzo 2027)

Hace dos comprobaciones y avisa por correo (Gmail):
  1) NOTICIAS de rfef.es (Selección Absoluta + portada de noticias), solo
     entradas de la Selección española masculina absoluta:
       - entradas España–Francia (Mestalla, Nations League)   -> URGENTE
       - entradas Mundial 2030                               -> URGENTE
       - entradas de cualquier otro partido de España        -> aviso normal
     (Ignora femenina, categorías inferiores, clubes, árbitros y productos.)
  1b) GOOGLE NOTICIAS (para la FIFA, cuya web no se puede leer): titulares
     nuevos sobre venta/registro/sorteo de entradas del Mundial 2030 o del
     España–Francia. Un solo correo por comprobación con todos los titulares.
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
import urllib.request, urllib.error, urllib.parse
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
# Solo noticias de ENTRADAS de la Selección española masculina absoluta.
# Palabras que se buscan en la URL y el título de cada noticia:
ENTRADAS_FUERTE = ["entradas", "localidades", "tickets"]
ENTRADAS_DEBIL = ["venta", "preventa", "registro", "formulario", "abonados", "socios", "sorteo de entradas"]
PARTIDO_FRANCIA = ["francia", "nations", "cuartos", "mestalla", "liga-de-naciones", "liga de naciones"]
MUNDIAL_2030 = ["2030"]
EXCLUIR_NOTICIA = [
    # otras selecciones y categorías
    "femenin", "sub-", "sub1", "sub2", "futbol-sala", "futsal", "sala", "playa", "ereuropa", "esports",
    "mundial-de-clubes", "mundial de clubes", "regional", "amateur", "veteran",
    # competiciones de clubes
    "copa-del-rey", "copa del rey", "copa-de-la-reina", "copa de la reina", "supercopa",
    "primera-federacion", "segunda-federacion", "tercera-federacion", "primera federacion",
    "segunda federacion", "tercera federacion", "liga-f", "arbitr", "designaciones",
    # productos
    "comic", "cómic", "camiseta", "tienda", "libro", "album", "álbum", "coleccion", "colección",
    "merchandising", "equipacion", "equipación",
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
    fuerte = any(x in t for x in ENTRADAS_FUERTE)
    entradas = fuerte or any(x in t for x in ENTRADAS_DEBIL)
    if not entradas:
        return None
    if any(x in t for x in PARTIDO_FRANCIA):
        return "francia"
    if any(x in t for x in MUNDIAL_2030):
        return "mundial"
    if fuerte:
        return "seleccion"
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
               f"Leo {len(encontradas)} noticias. Te escribiré en cuanto salga una nueva sobre entradas de la "
               "Selección española (España–Francia, otros partidos y Mundial 2030).\n"
               + ("Ahora mismo ya hay estas relacionadas:\n" + "\n".join(ya) if ya else "Ahora mismo no hay ninguna."),
               "low", "https://rfef.es/es/noticias/seleccion-absoluta?baseFilters=79393")
    else:
        asuntos = {
            "francia": "🚨 ¡ENTRADAS España–Francia (Mestalla)!",
            "mundial": "🏆 ¡ENTRADAS Mundial 2030!",
            "seleccion": "🇪🇸 Entradas de la Selección española",
        }
        for c, s, t in sorted(relevantes):
            enlace = f"https://rfef.es/es/noticias/{s}"
            avisar(asuntos[c], f"{t or s}\nLee fechas, fases y si hay formulario de registro.",
                   "urgent" if c != "seleccion" else "high", enlace)

    e["noticias_vistas"] = sorted(vistas | set(encontradas))[-3000:]


# ------------------------------------------------- GOOGLE NOTICIAS (FIFA)
# FIFA.com no se puede leer automáticamente (todo es JavaScript), así que se
# vigilan titulares en Google Noticias: cualquier anuncio de FIFA o RFEF sobre
# entradas sale ahí en minutos.
BUSQUEDAS_GOOGLE = [
    ("mundial", '"Mundial 2030" entradas'),
    ("mundial", '"World Cup 2030" tickets'),
    ("mundial", 'FIFA 2030 entradas registro'),
    ("francia", 'entradas "España-Francia" Mestalla'),
]
TITULAR_ENTRADAS = ["entrada", "ticket", "billete", "localidad"]
TITULAR_CLAVE = ["venta", "registro", "regist", "sorteo", "fase", "precio", "comprar", "cómo", "como ",
                 "fecha", "sale", "on sale", "ballot", "draw", "apply", "solicitud", "inscripci",
                 "abonados", "socios", "preventa", "cuándo", "cuando", "when", "how to"]
TITULAR_EXCLUIR = ["reventa ilegal", "estafa", "femenin", "women", "sub-", "club world cup",
                   "mundial de clubes", "2026"]


def norm_titulo(t):
    t = re.sub(r"\s+-\s+[^-]+$", "", t)  # quita " - Medio"
    return re.sub(r"[^a-z0-9áéíóúñü ]", "", t.lower()).strip()


def comprobar_google(e):
    vistos = set(e.get("google_vistos", []))
    primera = "google_vistos" not in e
    nuevos, fallos = [], 0
    for tipo, q in BUSQUEDAS_GOOGLE:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:30d")
               + "&hl=es&gl=ES&ceid=ES:es")
        status, xml = descargar(url)
        if status != 200 or "<rss" not in xml[:500]:
            fallos += 1
            continue
        for item in re.findall(r"(?s)<item>(.*?)</item>", xml):
            tt = re.search(r"(?s)<title>(.*?)</title>", item)
            ll = re.search(r"(?s)<link>(.*?)</link>", item)
            if not tt:
                continue
            titulo = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", tt.group(1))).strip()
            clave = norm_titulo(titulo)
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            tl = titulo.lower()
            if any(x in tl for x in TITULAR_EXCLUIR):
                continue
            if not any(x in tl for x in TITULAR_ENTRADAS) or not any(x in tl for x in TITULAR_CLAVE):
                continue
            if tipo == "mundial" and "2030" not in tl:
                continue
            nuevos.append((tipo, titulo, ll.group(1).strip() if ll else ""))

    if fallos == len(BUSQUEDAS_GOOGLE):
        e["fallos_google"] = e.get("fallos_google", 0) + 1
        print(f"[{ahora()}] Google Noticias: sin respuesta ({e['fallos_google']} seguidas)")
        if e["fallos_google"] == 12:  # ~1 hora
            avisar("⚠️ Vigía: no puedo leer Google Noticias",
                   "Llevo 1 hora sin poder leerlo. Las noticias de rfef.es se siguen vigilando.", "default",
                   "https://news.google.com")
        return
    e["fallos_google"] = 0
    print(f"[{ahora()}] Google Noticias OK · {len(nuevos)} titulares nuevos relevantes")

    if not primera and nuevos:
        hay_mundial = any(t == "mundial" for t, _, _ in nuevos)
        asunto = "🏆 FIFA / Mundial 2030: noticias de entradas" if hay_mundial else \
                 "📰 Prensa: noticias de entradas España–Francia"
        cuerpo = "\n\n".join(f"• {t}\n{l}" for _, t, l in nuevos[:10])
        avisar(asunto, cuerpo + "\n\nConfirma siempre en FIFA.com/tickets o tickets.rfef.es.",
               "high", nuevos[0][2] or "https://www.fifa.com/tickets")
    e["google_vistos"] = sorted(vistos)[-3000:]


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


def latido_mensual(e):
    """Un correo al mes ("sigo vivo"). Si algún mes no llega, el vigía se ha parado."""
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    if "latido" not in e:            # primera vez: solo apunta el mes, sin correo
        e["latido"], e["comprobaciones_mes"] = mes, 0
    if e["latido"] != mes:
        n = e.get("comprobaciones_mes", 0)
        avisar("💚 Vigía de entradas: sigo activo",
               f"Resumen del mes pasado: {n} comprobaciones hechas.\n"
               f"Sigo vigilando rfef.es y las noticias de FIFA / Mundial 2030.\n"
               f"Si algún mes no recibes este correo, entra en GitHub → Actions → Enable workflow.",
               "low", "https://rfef.es/es/noticias/seleccion-absoluta?baseFilters=79393")
        e["latido"], e["comprobaciones_mes"] = mes, 0
    e["comprobaciones_mes"] = e.get("comprobaciones_mes", 0) + 1


def comprobar():
    e = cargar_estado()
    comprobar_noticias(e)
    comprobar_google(e)
    comprobar_evento(e)
    latido_mensual(e)
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
