#!/usr/bin/env python3
"""Build a validated Update com Afeto edition from approved Series A sources."""
import json, os, re, sys, time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

ROOT = os.getcwd()
SOURCES_FILE = os.path.join(ROOT, "data/sources.json")
LATEST_FILE = os.path.join(ROOT, "data/latest.json")
EDITION_DIR = os.path.join(ROOT, "data/editions")
TODAY = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
HEADERS = {"User-Agent": "UpdateComAfetoEditorialBot/1.0 (+https://studio-gh.github.io/update-com-afeto/)"}
TIMEOUT = 18

def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def allowed_domain(url, source_url):
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
        base = (urlparse(source_url).hostname or "").lower().removeprefix("www.")
        return bool(host and base and (host == base or host.endswith("." + base)))
    except Exception:
        return False

def get_html(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return None, None
        return r.url, BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None, None

def date_from_page(soup):
    if not soup:
        return None
    candidates = []
    for selector, attr in [
        ('meta[property="article:published_time"]', "content"),
        ('meta[name="article:published_time"]', "content"),
        ('meta[property="og:published_time"]', "content"),
        ('meta[name="date"]', "content"),
        ('meta[name="pubdate"]', "content"),
        ('meta[itemprop="datePublished"]', "content"),
        ('time[datetime]', "datetime"),
    ]:
        el = soup.select_one(selector)
        if el and el.get(attr):
            candidates.append(el.get(attr).strip())
    for raw in candidates:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.date()
        except Exception:
            try:
                return date.fromisoformat(raw[:10])
            except Exception:
                pass
    return None

def meta_value(soup, selectors):
    for selector, attr in selectors:
        el = soup.select_one(selector)
        if el and el.get(attr):
            return el.get(attr).strip()
    return ""

def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não está disponível como secret do workflow.")
    config = read_json(SOURCES_FILE)
    rules = config.get("editorial_rules", {})
    window_days = int(rules.get("date_window_days", 7))
    min_date = TODAY - timedelta(days=window_days - 1)
    sources = config["series_a"]
    domains = sorted({urlparse(s["url"]).hostname.replace("www.", "") for s in sources})
    domain_to_source = {}
    for s in sources:
        host = (urlparse(s["url"]).hostname or "").replace("www.", "")
        domain_to_source[host] = s["name"]

    search_prompt = f"""
Você é a pesquisadora editorial do Update com Afeto, um jornal digital brasileiro sobre publicidade, campanhas, branding, experiências de marca, estratégia e negócios, comportamento humano e cultura da internet.
Encontre até 30 matérias reais, recentes e relevantes publicadas entre {min_date.isoformat()} e {TODAY.isoformat()} (inclusive).
Pesquise SOMENTE nos domínios autorizados pela ferramenta. Não use Série B nem outros sites.
Priorize campanhas criativas, decisões de marca, comportamento de pessoas, cultura digital, marketing e negócios. Tecnologia/IA só quando tiver impacto concreto em comunicação, criatividade, negócios ou relações entre marcas e pessoas.
Retorne JSON puro com a chave "stories", uma lista de objetos com:
"title" (título original), "url" (URL direta da matéria, não homepage), "source" (nome da fonte), "published_date" (YYYY-MM-DD), "why_it_matters" (uma frase factual e curta em português).
Não invente. Só inclua matérias cuja data e URL você consiga confirmar. Não inclua páginas de categoria, newsletters genéricas ou páginas de relatório sem matéria específica.
"""
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5"),
        "tools": [{
            "type": "web_search",
            "filters": {"allowed_domains": domains},
            "search_context_size": "high"
        }],
        "input": search_prompt
    }
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload, timeout=180
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI API falhou ({response.status_code}): {response.text[:1200]}")
    data = response.json()
    output_text = data.get("output_text")
    if not output_text:
        parts = []
        for item in data.get("output", []):
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
        output_text = "\n".join(parts)
    if not output_text:
        raise RuntimeError("A pesquisa não retornou conteúdo estruturado.")
    try:
        candidates = json.loads(output_text).get("stories", [])
    except Exception as exc:
        raise RuntimeError(f"Não foi possível interpretar o JSON da pesquisa: {exc}; início={output_text[:500]}")

    validated, seen = [], set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "")).strip()
        if not url.startswith("https://") or url in seen:
            continue
        source = next((s for s in sources if allowed_domain(url, s["url"])), None)
        if not source:
            continue
        seen.add(url)
        final_url, soup = get_html(url)
        if not soup or not final_url or not allowed_domain(final_url, source["url"]):
            continue
        pubdate = date_from_page(soup)
        # Do not trust model-provided dates when the page itself does not expose a verifiable date.
        if not pubdate or pubdate < min_date or pubdate > TODAY:
            continue
        title = meta_value(soup, [
            ('meta[property="og:title"]', "content"),
            ('meta[name="twitter:title"]', "content"),
        ]) or (soup.title.get_text(" ", strip=True) if soup.title else "")
        title = re.sub(r"\s+", " ", title).strip()
        if not title or len(title) < 8:
            continue
        description = meta_value(soup, [
            ('meta[property="og:description"]', "content"),
            ('meta[name="description"]', "content"),
            ('meta[name="twitter:description"]', "content"),
        ])
        image_url = meta_value(soup, [
            ('meta[property="og:image"]', "content"),
            ('meta[name="twitter:image"]', "content"),
        ])
        if image_url:
            image_url = urljoin(final_url, image_url)
            if not image_url.startswith("https://"):
                image_url = ""
        validated.append({
            "title_original": title,
            "url": final_url,
            "source": source["name"],
            "published_date": pubdate.isoformat(),
            "source_description": description[:900],
            "image_url": image_url,
            "why_it_matters": str(item.get("why_it_matters", "")).strip()[:500]
        })
        time.sleep(0.25)

    # Remove duplicates by canonical URL and normalized title.
    unique = []
    keys = set()
    for s in validated:
        key = (s["url"].rstrip("/"), s["title_original"].casefold())
        if key not in keys:
            keys.add(key)
            unique.append(s)
    if len(unique) < 10:
        raise RuntimeError(f"Somente {len(unique)} matérias passaram na validação de URL, domínio e data entre {min_date} e {TODAY}. Edição anterior preservada.")

    curation_prompt = {
        "role": "editorial selection",
        "language": "Brazilian Portuguese",
        "rules": [
            "Select exactly 10 stories from the supplied candidates, no others.",
            "Use only Series A source candidates provided.",
            "Max 2 stories from any source and at least 6 distinct sources.",
            "Prioritize advertising/campaigns, branding, brand experience, strategy/business, human behavior and internet culture.",
            "Do not make claims beyond candidate title, description and why_it_matters.",
            "Write a concise, clear Portuguese headline and a summary of 2-3 sentences (35-65 words) explaining what happened and why it matters.",
            "The original article title, URL, source and published date must be preserved exactly from candidate data.",
            "Return valid JSON with keys lead_index (0-9), editor_letter (70-110 words), signals (exactly 3 objects with title, description, category), and stories (exactly 10 objects).",
            "Each story object: candidate_url, headline, summary, category (one of Branding, Campanhas, Experiência de marca, Estratégia & negócios, Comportamento, Cultura digital, Criatividade), why_it_matters (one short practical editorial takeaway)."
        ],
        "candidates": unique[:60]
    }
    curated = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("OPENAI_MODEL", "gpt-5"),
            "input": json.dumps(curation_prompt, ensure_ascii=False),
            "text": {"format": {"type": "json_object"}}
        },
        timeout=180
    )
    if curated.status_code >= 400:
        raise RuntimeError(f"OpenAI curadoria falhou ({curated.status_code}): {curated.text[:1200]}")
    cdata = curated.json()
    text_out = cdata.get("output_text") or ""
    if not text_out:
        text_out = "\n".join(c.get("text", "") for o in cdata.get("output", []) for c in o.get("content", []) if c.get("type") in ("output_text", "text"))
    editorial = json.loads(text_out)
    by_url = {s["url"]: s for s in unique}
    final_stories = []
    counts, sources_used = {}, set()
    for s in editorial.get("stories", []):
        original = by_url.get(s.get("candidate_url"))
        if not original:
            continue
        src = original["source"]
        counts[src] = counts.get(src, 0) + 1
        if counts[src] > 2:
            continue
        sources_used.add(src)
        final_stories.append({
            "title": s.get("headline", original["title_original"]).strip(),
            "original_title": original["title_original"],
            "summary": s.get("summary", original["source_description"]).strip(),
            "why_it_matters": s.get("why_it_matters", original["why_it_matters"]).strip(),
            "category": s.get("category", "Cultura digital"),
            "source": src,
            "published_date": original["published_date"],
            "url": original["url"],
            "image_url": original["image_url"],
            "series": "Série A"
        })
    if len(final_stories) != 10 or len(sources_used) < 6:
        raise RuntimeError(f"Validação editorial falhou: {len(final_stories)} matérias e {len(sources_used)} fontes distintas. Edição anterior preservada.")
    if len({s["url"] for s in final_stories}) != 10:
        raise RuntimeError("Validação editorial falhou: URLs duplicadas. Edição anterior preservada.")

    lead_index = editorial.get("lead_index", 0)
    if not isinstance(lead_index, int) or lead_index < 0 or lead_index >= 10:
        lead_index = 0
    edition = {
        "edition_date": TODAY.isoformat(),
        "status": "published",
        "notice": "",
        "window_start": min_date.isoformat(),
        "window_end": TODAY.isoformat(),
        "edition_name": config.get("edition_name", "Update com Afeto"),
        "editor_letter": editorial.get("editor_letter", ""),
        "signals": editorial.get("signals", [])[:3],
        "lead_url": final_stories[lead_index]["url"],
        "stories": final_stories
    }
    os.makedirs(EDITION_DIR, exist_ok=True)
    dated_path = os.path.join(EDITION_DIR, f"{TODAY.isoformat()}.json")
    for path, content in [(LATEST_FILE, edition), (dated_path, edition)]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(f"Edição validada: {len(final_stories)} matérias, {len(sources_used)} fontes, janela {min_date}–{TODAY}.")
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRO EDITORIAL: {e}", file=sys.stderr)
        sys.exit(1)
