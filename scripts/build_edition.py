#!/usr/bin/env python3
"""Zero-cost edition builder: RSS discovery + original-page validation; no paid AI API."""
import json, os, re, sys, time, html
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse, urljoin, quote_plus
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

ROOT = os.getcwd()
SOURCES_FILE = os.path.join(ROOT, "data/sources.json")
LATEST_FILE = os.path.join(ROOT, "data/latest.json")
EDITION_DIR = os.path.join(ROOT, "data/editions")
TODAY = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
MIN_DATE = TODAY - timedelta(days=6)
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UpdateComAfetoBot/1.0; +https://studio-gh.github.io/update-com-afeto/)"}
TIMEOUT = 18
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def host(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")

def allowed_domain(url, source_url):
    h, b = host(url), host(source_url)
    return bool(h and b and (h == b or h.endswith("." + b)))

def get_html(url):
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "").lower():
            return None, None
        return r.url, BeautifulSoup(r.text, "html.parser")
    except requests.RequestException:
        return None, None

def meta(soup, pairs):
    for selector, attr in pairs:
        el = soup.select_one(selector)
        if el and el.get(attr):
            value = html.unescape(el.get(attr).strip())
            if value:
                return value
    return ""

def parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:
        return None

def page_date(soup):
    if not soup:
        return None
    for selector, attr in [
        ('meta[property="article:published_time"]', "content"),
        ('meta[name="article:published_time"]', "content"),
        ('meta[property="og:published_time"]', "content"),
        ('meta[name="date"]', "content"),
        ('meta[name="pubdate"]', "content"),
        ('meta[itemprop="datePublished"]', "content"),
        ('time[datetime]', "datetime"),
        ('script[type="application/ld+json"]', None),
    ]:
        el = soup.select_one(selector)
        if not el:
            continue
        raw = el.get(attr) if attr else el.string
        if attr and raw:
            d = parse_date(raw)
            if d:
                return d
        elif raw:
            try:
                obj = json.loads(raw)
                objs = obj if isinstance(obj, list) else [obj]
                for item in objs:
                    if isinstance(item, dict):
                        if item.get("@graph"):
                            objs.extend(x for x in item["@graph"] if isinstance(x, dict))
                        d = parse_date(item.get("datePublished") or item.get("dateCreated"))
                        if d:
                            return d
            except Exception:
                pass
    return None

def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()

def source_rss_urls(home_url, soup):
    found = []
    if soup:
        for el in soup.select('link[rel~="alternate"]'):
            typ = (el.get("type") or "").lower()
            href = el.get("href")
            if href and ("rss" in typ or "atom" in typ or "xml" in typ):
                found.append(urljoin(home_url, href))
    h = host(home_url)
    if "substack.com" in h:
        found.extend([urljoin(home_url, "feed"), urljoin(home_url, "feed/")])
    if h in ("b9.com.br", "updateordie.com", "coolhunting.com", "fastcompanybrasil.com", "thesummerhunter.com", "resumido.cc"):
        found.extend([urljoin(home_url, "feed/"), urljoin(home_url, "feed")])
    return list(dict.fromkeys(found))

def parse_feed(feed_url, source):
    items = []
    try:
        r = SESSION.get(feed_url, timeout=TIMEOUT)
        if r.status_code >= 400:
            return items
        root = ET.fromstring(r.content)
        for node in root.findall(".//item"):
            title = clean_text(node.findtext("title"))
            link = clean_text(node.findtext("link"))
            desc = clean_text(node.findtext("description"))
            pub = parse_date(node.findtext("pubDate"))
            if not pub:
                for child in node:
                    if child.tag.endswith("}published") or child.tag.endswith("}updated"):
                        pub = parse_date(child.text)
                        if pub: break
            if title and link and pub:
                items.append({"title": title, "url": link, "feed_date": pub.isoformat(), "description": BeautifulSoup(desc, "html.parser").get_text(" ", strip=True), "source": source["name"], "source_url": source["url"]})
        # Atom
        for node in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = clean_text(node.findtext("{http://www.w3.org/2005/Atom}title"))
            link_el = node.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href") if link_el is not None else ""
            rawdate = node.findtext("{http://www.w3.org/2005/Atom}published") or node.findtext("{http://www.w3.org/2005/Atom}updated")
            pub = parse_date(rawdate)
            summary = node.findtext("{http://www.w3.org/2005/Atom}summary") or node.findtext("{http://www.w3.org/2005/Atom}content") or ""
            if title and link and pub:
                items.append({"title": clean_text(title), "url": link, "feed_date": pub.isoformat(), "description": BeautifulSoup(summary, "html.parser").get_text(" ", strip=True), "source": source["name"], "source_url": source["url"]})
    except Exception:
        return items
    return items

def google_news_feeds(source):
    domain = host(source["url"])
    # Several focused queries improve coverage for sources with weak/no public RSS.
    # Keep every query restricted to the approved source domain and the 7-day window.
    topics = [
        '"campanha" OR "campaign" OR publicidade OR advertising',
        'marca OR branding OR marketing OR comunicação',
        'consumidor OR comportamento OR cultura OR tendência',
        'experiência OR ativação OR criatividade OR design',
    ]
    feeds = []
    for topic in topics:
        query = quote_plus(f"site:{domain} after:{MIN_DATE.isoformat()} ({topic})")
        feeds.append(f"https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419")
    return feeds

def category_for(text):
    t = text.casefold()
    groups = [
        ("Campanhas", ["campanha", "campaign", "filme", "comercial", "anúncio", "advertising", "publicidade", "ativação"]),
        ("Branding", ["marca", "branding", "identidade visual", "rebranding", "brand"]),
        ("Experiência de marca", ["experiência", "experiential", "evento", "pop-up", "ativação", "retail"]),
        ("Estratégia & negócios", ["negócio", "estratégia", "mercado", "empresa", "crescimento", "ceo", "vendas", "business"]),
        ("Comportamento", ["comportamento", "consumidor", "consumo", "cultura", "geração", "tendência", "pessoas"]),
        ("Cultura digital", ["internet", "digital", "social media", "tiktok", "instagram", "creator", "criador", "memes", "viral"]),
    ]
    for label, words in groups:
        if any(w in t for w in words):
            return label
    return "Criatividade"

def summary_for(description, title):
    desc = clean_text(BeautifulSoup(description or "", "html.parser").get_text(" ", strip=True))
    desc = re.sub(r"\s+", " ", desc)
    desc = re.sub(r"\s*[-|]\s*(Leia mais|Read more|Continue lendo).*?$", "", desc, flags=re.I)
    if len(desc) >= 70:
        sentences = re.split(r"(?<=[.!?])\s+", desc)
        text = " ".join(sentences[:2]).strip()
        return text[:440].rstrip() + ("…" if len(text) > 440 else "")
    return f"A matéria aborda “{title}”. Abra a publicação original para conferir os detalhes, o contexto e os exemplos apresentados pela fonte."

def discover_candidates(sources):
    candidates = []
    for source in sources:
        homepage, soup = get_html(source["url"])
        feed_urls = source_rss_urls(homepage or source["url"], soup)
        source_items = []
        for feed in feed_urls[:4]:
            source_items.extend(parse_feed(feed, source))
        # Free fallback: multiple topical Google News RSS queries, restricted to
        # each approved domain. This is discovery only; original pages are validated below.
        for search_feed in google_news_feeds(source):
            source_items.extend(parse_feed(search_feed, source))
        seen = set()
        for item in source_items:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            try:
                pub = date.fromisoformat(item["feed_date"])
            except Exception:
                continue
            if not (MIN_DATE <= pub <= TODAY):
                continue
            if not allowed_domain(item["url"], source["url"]):
                # Google News sometimes returns a redirect; resolve it before rejecting.
                final, page = get_html(item["url"])
                if not final or not allowed_domain(final, source["url"]):
                    continue
                item["url"], item["_preloaded_url"], item["_preloaded_soup"] = final, final, page
            candidates.append(item)
        time.sleep(0.15)
    return candidates

def validate_candidates(candidates):
    valid = []
    seen_urls = set()
    for item in candidates:
        url = item["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        source = item["source_url"]
        if "_preloaded_soup" in item:
            final, soup = item["_preloaded_url"], item["_preloaded_soup"]
        else:
            final, soup = get_html(url)
        if not soup or not final or not allowed_domain(final, source):
            continue
        # Prefer original page publication metadata. RSS date is fallback only when
        # the page omits publication date; the feed itself is a source-controlled date.
        published = page_date(soup)
        if not published:
            published = date.fromisoformat(item["feed_date"])
        if published < MIN_DATE or published > TODAY:
            continue
        canonical = meta(soup, [('link[rel="canonical"]', "href")])
        if canonical:
            canonical = urljoin(final, canonical)
            if allowed_domain(canonical, source):
                final = canonical
        title = meta(soup, [('meta[property="og:title"]', "content"), ('meta[name="twitter:title"]', "content")])
        if not title and soup.title:
            title = soup.title.get_text(" ", strip=True)
        title = clean_text(title or item["title"])
        if len(title) < 8:
            continue
        desc = meta(soup, [('meta[property="og:description"]', "content"), ('meta[name="description"]', "content"), ('meta[name="twitter:description"]', "content")])
        desc = clean_text(desc or item.get("description", ""))
        image_url = meta(soup, [('meta[property="og:image"]', "content"), ('meta[name="twitter:image"]', "content")])
        if image_url:
            image_url = urljoin(final, image_url)
            if not image_url.startswith("https://"):
                image_url = ""
        category = category_for(title + " " + desc)
        valid.append({
            "title": title,
            "original_title": title,
            "summary": summary_for(desc, title),
            "why_it_matters": "Vale observar o que esta publicação revela sobre " + category.lower() + " e suas implicações para marcas e comunicação.",
            "category": category,
            "source": item["source"],
            "published_date": published.isoformat(),
            "url": final,
            "image_url": image_url,
            "series": "Série A",
            "_description": desc
        })
        time.sleep(0.12)
    return valid

def choose_stories(stories, target=10, max_per_source=2, min_sources=6):
    # Deterministic editorial scoring, using only original article metadata.
    preferred = ["Campanhas", "Branding", "Experiência de marca", "Estratégia & negócios", "Comportamento", "Cultura digital", "Criatividade"]
    def score(s):
        text = (s["title"] + " " + s.get("_description", "")).casefold()
        val = 0
        for word in ["campanha", "branding", "marca", "publicidade", "consumidor", "comportamento", "experiência", "internet", "cultura digital", "criatividade", "marketing", "estratégia"]:
            if word in text: val += 2
        if s["category"] in preferred[:5]: val += 2
        if len(s.get("_description", "")) > 100: val += 1
        return val
    ordered = sorted(stories, key=lambda s: (score(s), s["published_date"]), reverse=True)
    chosen, counts = [], {}
    for s in ordered:
        if counts.get(s["source"], 0) >= max_per_source:
            continue
        chosen.append(s)
        counts[s["source"]] = counts.get(s["source"], 0) + 1
        if len(chosen) == target:
            break
    if len(chosen) != target or len(counts) < min_sources:
        raise RuntimeError(f"A pesquisa gratuita encontrou {len(chosen)} matérias elegíveis de {len(counts)} fontes. São necessárias 10 matérias e pelo menos 6 fontes. Edição anterior preservada.")
    for s in chosen:
        s.pop("_description", None)
    return chosen

def main():
    config = read_json(SOURCES_FILE)
    rules = config.get("editorial_rules", {})
    target = int(rules.get("stories_per_edition", 10))
    max_per_source = int(rules.get("max_stories_per_source", 2))
    min_sources = int(rules.get("minimum_distinct_sources", 6))
    series_a = config.get("series_a", [])
    series_b = config.get("series_b", [])
    sources = series_a + series_b
    print(f"Pesquisa gratuita: {len(series_a)} fontes Série A + {len(series_b)} fontes Série B; total {len(sources)}; janela {MIN_DATE} a {TODAY}.")
    candidates = discover_candidates(sources)
    candidate_counts = {}
    for item in candidates:
        candidate_counts[item["source"]] = candidate_counts.get(item["source"], 0) + 1
    print(f"Encontradas {len(candidates)} candidatas em feeds e busca RSS.")
    print("Candidatas por fonte: " + ", ".join(f"{name}={count}" for name, count in sorted(candidate_counts.items())))
    validated = validate_candidates(candidates)
    validated_counts = {}
    for item in validated:
        validated_counts[item["source"]] = validated_counts.get(item["source"], 0) + 1
    print(f"Validadas {len(validated)} matérias com URL original e data.")
    print("Validadas por fonte: " + ", ".join(f"{name}={count}" for name, count in sorted(validated_counts.items())))
    stories = choose_stories(validated, target, max_per_source, min_sources)
    lead = max(stories, key=lambda s: (sum(1 for w in ["campanha", "marca", "publicidade", "comportamento", "experiência"] if w in s["title"].casefold()), s["published_date"]))
    categories = {}
    for s in stories:
        categories[s["category"]] = categories.get(s["category"], 0) + 1
    top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:3]
    signals = [{"title": cat, "description": f"{count} matéria(s) desta edição exploram {cat.lower()}. Veja como as marcas e a cultura estão se movimentando neste tema.", "category": "SINAL EDITORIAL"} for cat, count in top_categories]
    while len(signals) < 3:
        signals.append({"title": "Repertório em movimento", "description": "Acompanhe as publicações originais para identificar exemplos e ideias aplicáveis à comunicação.", "category": "SINAL EDITORIAL"})
    edition = {
        "edition_date": TODAY.isoformat(),
        "status": "published",
        "notice": "Curadoria automática gratuita baseada em RSS e metadados das fontes originais.",
        "window_start": MIN_DATE.isoformat(),
        "window_end": TODAY.isoformat(),
        "edition_name": config.get("edition_name", "Update com Afeto"),
        "editor_letter": f"Esta edição reúne {len(stories)} histórias publicadas nos últimos sete dias, selecionadas entre as fontes aprovadas da Série A. A curadoria prioriza campanhas, marcas, estratégia, comportamento e cultura digital. Os resumos partem das descrições publicadas pelas próprias fontes; abra os links originais para ler o contexto completo.",
        "signals": signals,
        "lead_url": lead["url"],
        "stories": stories
    }
    os.makedirs(EDITION_DIR, exist_ok=True)
    for path in [LATEST_FILE, os.path.join(EDITION_DIR, f"{TODAY.isoformat()}.json")]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(edition, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"Edição gratuita validada: {len(stories)} matérias, {len(set(s['source'] for s in stories))} fontes.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRO EDITORIAL: {e}", file=sys.stderr)
        sys.exit(1)
