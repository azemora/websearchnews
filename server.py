"""
NewsSearch - servidor HTTP local que agrega RSS de fontes brasileiras
e internacionais relevantes para consultoria em desenvolvimento de
lideranças, cultura organizacional e times.

Sem dependências externas. Rode com: python3 server.py
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta
import json
import re
import html
import os
import socket
import sys
import gzip
import io

PORT = 8765
HOST = "127.0.0.1"
ROOT = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 NewsSearch/1.0"
FETCH_TIMEOUT = 8

FEEDS = [
    # Brasil, imprensa generalista, econômica e jurídica
    {"source": "JOTA", "url": "https://www.jota.info/feed", "lang": "pt"},
    {"source": "Conjur", "url": "https://www.conjur.com.br/rss.xml", "lang": "pt"},
    {"source": "Folha - Mercado", "url": "https://feeds.folha.uol.com.br/mercado/rss091.xml", "lang": "pt"},
    {"source": "Folha - Cotidiano", "url": "https://feeds.folha.uol.com.br/cotidiano/rss091.xml", "lang": "pt"},
    {"source": "G1 - Economia", "url": "https://g1.globo.com/rss/g1/economia/", "lang": "pt"},
    {"source": "G1 - Concursos e Emprego", "url": "https://g1.globo.com/rss/g1/concursos-e-emprego/", "lang": "pt"},
    {"source": "Exame", "url": "https://exame.com/feed/", "lang": "pt"},
    {"source": "Forbes Brasil", "url": "https://forbes.com.br/feed/", "lang": "pt"},
    {"source": "Você RH", "url": "https://vocerh.abril.com.br/feed/", "lang": "pt"},
    {"source": "Você S/A", "url": "https://vocesa.abril.com.br/feed/", "lang": "pt"},

    # Internacional, gestão e pesquisa aplicada
    {"source": "MIT Sloan Management Review", "url": "https://sloanreview.mit.edu/feed/", "lang": "en"},
    {"source": "McKinsey Insights", "url": "https://www.mckinsey.com/insights/rss", "lang": "en"},
]

# Termos que sinalizam ruído fora do escopo da consultoria.
# Se aparecerem no título, o item é descartado mesmo com bom score.
DENYLIST = [
    "morta", "morto", "assassinado", "assassinada", "homicídio",
    "óbito", "falecido", "falecimento", "luto",
    "neymar", "seleção brasileira", "copa do mundo", "fifa",
    "guerra", "míssil", "drone militar", "ataque russo", "ataque israel",
]

# Eixos temáticos. Cada termo gera um match contado uma vez por artigo.
# CORE = um item precisa ter ao menos um match num tema CORE para entrar.
# Modifier (IA, Conflitos, Setor cliente) amplifica mas não qualifica sozinho.
THEMES = {
    "Liderança": {
        "role": "core", "weight": 3,
        "kw": [
            "liderança", "lideranças", "líder", "líderes", "líderança",
            "leadership", "leaders", "c-level", "alta liderança",
            "desenvolvimento de líderes", "executive leadership",
        ],
    },
    "Cultura organizacional": {
        "role": "core", "weight": 3,
        "kw": [
            "cultura organizacional", "cultura corporativa", "clima organizacional",
            "valores corporativos", "propósito organizacional",
            "organizational culture", "company culture", "workplace culture",
            "corporate culture",
        ],
    },
    "Engajamento e equipes": {
        "role": "core", "weight": 3,
        "kw": [
            "engajamento", "engajado", "engajada",
            "produtividade da equipe", "alta performance", "high performance",
            "retenção de talentos", "turnover", "rotatividade",
            "employee engagement", "team performance", "employee retention",
            "psychological safety", "segurança psicológica",
            "desenvolvimento de equipes", "team building",
        ],
    },
    "Gestão de pessoas / RH": {
        "role": "core", "weight": 3,
        "kw": [
            "recursos humanos", "gestão de pessoas", "people analytics",
            "rh estratégico", "diretor de rh", "chro", "vp de pessoas",
            "human resources", "people management", "people strategy",
            "talent management", "gestão de talentos", "talentos da empresa",
        ],
    },
    "Futuro do trabalho": {
        "role": "core", "weight": 2,
        "kw": [
            "futuro do trabalho", "future of work", "trabalho híbrido",
            "remote work", "hybrid work", "home office", "semana de 4 dias",
            "four-day week", "return to office", "modelo híbrido",
        ],
    },
    "Nova geração": {
        "role": "core", "weight": 2,
        "kw": [
            "geração z", "gen z", "millennials", "geração y",
            "jovens profissionais", "entry level", "primeiro emprego",
            "novos talentos",
        ],
    },
    "Saúde mental e burnout": {
        "role": "core", "weight": 2,
        "kw": [
            "burnout", "saúde mental no trabalho", "estresse no trabalho",
            "esgotamento profissional", "mental health at work",
            "wellbeing", "bem-estar no trabalho", "saúde mental",
        ],
    },
    "IA no trabalho": {
        "role": "modifier", "weight": 3,
        "kw": [
            "inteligência artificial no trabalho", "ia generativa",
            "ia no rh", "ai at work", "generative ai at work",
            "copilot", "agentes de ia", "agentic ai",
            "ai for hr", "automação de processos",
        ],
    },
    "Conflitos com repercussão": {
        "role": "modifier", "weight": 2,
        "kw": [
            "assédio moral", "assédio sexual", "discriminação no trabalho",
            "racismo no trabalho", "processo trabalhista", "passivo trabalhista",
            "ministério público do trabalho", "mpt", "tst",
            "harassment lawsuit", "workplace discrimination",
        ],
    },
    "Setor cliente": {
        "role": "modifier", "weight": 2,
        "kw": [
            "turismo", "hotelaria", "hotel", "hospitalidade", "parques temáticos",
            "agronegócio", "agribusiness", "tourism industry", "hospitality industry",
        ],
    },
}

CORE_THEMES = {name for name, cfg in THEMES.items() if cfg["role"] == "core"}

# Pré-compila regex com fronteiras de palavra para evitar matches como "equipe" em "equipamentos".
# Aceita variação maiúscula/minúscula e fronteiras em acento/hífen.
def _build_pattern(kw):
    escaped = re.escape(kw)
    # \b funciona para ASCII; para PT-BR com acento, usamos lookarounds com não-letra
    return re.compile(r"(?<![\wÀ-ÿ])" + escaped + r"(?![\wÀ-ÿ])", re.IGNORECASE)


ALL_KEYWORDS = []
for theme, cfg in THEMES.items():
    for kw in cfg["kw"]:
        ALL_KEYWORDS.append((_build_pattern(kw), kw, theme, cfg["weight"]))


def _strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _fetch(url):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
    })
    with urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def _parse_feed(xml_bytes, source_name):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    tag = root.tag.lower()
    is_atom = tag.endswith("feed")
    ns = {"atom": "http://www.w3.org/2005/Atom",
          "content": "http://purl.org/rss/1.0/modules/content/",
          "dc": "http://purl.org/dc/elements/1.1/"}

    if is_atom:
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        for e in entries:
            title = (e.findtext("atom:title", default="", namespaces=ns) or
                     e.findtext("title", default=""))
            link_el = e.find("atom:link", ns) or e.find("link")
            link = link_el.get("href") if link_el is not None and link_el.get("href") else (link_el.text if link_el is not None else "")
            summary = (e.findtext("atom:summary", default="", namespaces=ns) or
                       e.findtext("atom:content", default="", namespaces=ns) or
                       e.findtext("summary", default="") or
                       e.findtext("content", default=""))
            published = (e.findtext("atom:published", default="", namespaces=ns) or
                         e.findtext("atom:updated", default="", namespaces=ns) or
                         e.findtext("published", default="") or
                         e.findtext("updated", default=""))
            items.append({
                "title": _strip_html(title),
                "link": link,
                "summary": _strip_html(summary)[:1200],
                "published": published,
                "source": source_name,
            })
    else:
        # RSS 2.0
        channel = root.find("channel") or root
        for it in channel.findall("item"):
            title = it.findtext("title", default="")
            link = it.findtext("link", default="")
            summary = (it.findtext("description", default="") or
                       it.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", default=""))
            published = (it.findtext("pubDate", default="") or
                         it.findtext("{http://purl.org/dc/elements/1.1/}date", default=""))
            items.append({
                "title": _strip_html(title),
                "link": link.strip() if link else "",
                "summary": _strip_html(summary)[:1200],
                "published": published,
                "source": source_name,
            })
    return items


def fetch_feed(feed_cfg):
    try:
        xml = _fetch(feed_cfg["url"])
        items = _parse_feed(xml, feed_cfg["source"])
        for it in items:
            it["lang"] = feed_cfg["lang"]
        return items
    except (HTTPError, URLError, socket.timeout, ConnectionResetError, Exception) as e:
        return {"_error": True, "source": feed_cfg["source"], "url": feed_cfg["url"], "msg": str(e)}


def score_item(item):
    """Pontuação por casamento de termo, com fronteiras de palavra.
    Conta cada tema uma vez (peso do tema), evita inflar por sinônimos.
    Devolve (score, lista_de_temas, lista_de_matches_para_debug)."""
    title = item.get("title", "")
    summary = item.get("summary", "")
    haystack_title = title
    haystack_full = title + " \n " + summary

    themes_in_title = set()
    themes_anywhere = set()
    matched_terms = []

    for pattern, kw, theme, _weight in ALL_KEYWORDS:
        if pattern.search(haystack_title):
            themes_in_title.add(theme)
            themes_anywhere.add(theme)
            matched_terms.append((theme, kw, "title"))
        elif pattern.search(haystack_full):
            themes_anywhere.add(theme)
            matched_terms.append((theme, kw, "summary"))

    score = 0
    for theme in themes_anywhere:
        w = THEMES[theme]["weight"]
        # match no título vale 2x
        score += w * (2 if theme in themes_in_title else 1)

    # Bônus de combinação: tema core + modifier (ex.: liderança + IA)
    core_hits = themes_anywhere & CORE_THEMES
    mods = themes_anywhere - CORE_THEMES
    if core_hits and mods:
        score += 2

    # Bônus se conecta direto com o setor do cliente
    if "Setor cliente" in themes_anywhere and core_hits:
        score += 3

    return score, sorted(themes_anywhere), matched_terms, bool(core_hits)


def _is_noise(item):
    title = (item.get("title") or "").lower()
    return any(term in title for term in DENYLIST)


def aggregate(days=7, min_score=5, limit=15):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    raw = []
    errors = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_feed, f): f for f in FEEDS}
        for fut in as_completed(futures):
            res = fut.result()
            if isinstance(res, dict) and res.get("_error"):
                errors.append({"source": res["source"], "msg": res["msg"]})
                continue
            raw.extend(res)

    enriched = []
    seen_links = set()
    for it in raw:
        link = it.get("link") or ""
        if not link or link in seen_links:
            continue
        seen_links.add(link)

        if _is_noise(it):
            continue
        dt = _parse_date(it.get("published"))
        if dt and dt < cutoff:
            continue
        score, themes, matched_terms, has_core = score_item(it)
        # Regra dura: precisa de pelo menos um tema CORE e score mínimo
        if not has_core or score < min_score:
            continue
        enriched.append({
            **it,
            "score": score,
            "themes": themes,
            "matched_terms": matched_terms,
            "published_iso": dt.isoformat() if dt else None,
            "published_ts": dt.timestamp() if dt else 0,
        })

    # Ordena por score desc, depois data desc
    enriched.sort(key=lambda x: (x["score"], x["published_ts"]), reverse=True)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": len(raw),
        "selected": enriched[:limit],
        "errors": errors,
        "themes_catalog": list(THEMES.keys()),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # silencia log padrão
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/index.html":
            try:
                with open(os.path.join(ROOT, "index.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, "index.html não encontrado", "text/plain; charset=utf-8")
            return
        if path == "/api/news":
            try:
                data = aggregate()
                self._send(200, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
            return
        self._send(404, "not found", "text/plain")


def build_static(output_path):
    """Gera o JSON e grava em disco, para deploy estático (GitHub Pages)."""
    data = aggregate()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    selected = len(data.get("selected", []))
    errors = len(data.get("errors", []))
    print(f"news.json gerado em {output_path} — {selected} itens, {errors} fontes com erro")


def main():
    if "--build" in sys.argv:
        out = os.path.join(ROOT, "news.json")
        build_static(out)
        return
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NewsSearch rodando em http://{HOST}:{PORT}")
    print("Abra essa URL no navegador. Ctrl+C para encerrar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando.")
        httpd.server_close()


if __name__ == "__main__":
    main()
