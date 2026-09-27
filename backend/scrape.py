"""Reading a founder's website (PRD §9.2): Jina Reader first, Firecrawl as fallback, cached per domain for 30 days.
The homepage plus up to three pages linked from it (case studies, services, about) are trimmed to ~700 words for
Claude. The PRD reads only the homepage (~300 words); the linked pages were added after live QA showed the
homepage alone misses proof and services (26 Sept, needs Shiv's OK).
"""

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

import config
import db

log = logging.getLogger(__name__)

MIN_WORDS = 200        # real content words; below this the read counts as failed (PRD §8.3 degraded path)
CONTEXT_WORDS = 300    # homepage words Claude gets (PRD §9.2)
# Cached reads made before this moment (UTC) are ignored and re-read. Bump it whenever the cleaning below changes.
CLEANING_VERSION = "2026-09-26T06:00:00+00:00"

# Linked pages worth reading, matched on the link text or the last part of its path; one page per kind, in this
# order, with this many words each. "work"/"clients" pages are usually case studies under another name.
SUBPAGES = {
    "case_studies": re.compile(r"(our[\s_-])?(case[\s_-]?stud(y|ies)|success[\s_-]?stor(y|ies)|client[\s_-]?stor(y|ies)"
                               r"|portfolio|work|results|clients|customers)"),
    "services": re.compile(r"(our[\s_-])?(services|solutions|capabilities|offerings|what[\s_-]we[\s_-]do|expertise)"),
    "about": re.compile(r"about([\s_-]us)?|(our[\s_-])?(story|team|company)|who[\s_-]we[\s_-]are"),
}
SUBPAGE_WORDS = {"case_studies": 180, "services": 150, "about": 120}
SUBPAGE_TITLES = {"case_studies": "Case studies page", "services": "Services page", "about": "About page"}
SUBPAGE_TIMEOUT = 15   # seconds; a slow linked page is skipped, never waited for
LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)")
SOCIAL_DOMAINS = ("linkedin.com", "x.com", "twitter.com", "instagram.com", "facebook.com", "youtube.com",
                  "tiktok.com")

# ponytail: keyword guesses, tuned against scrape_check.py; a model-based check is the upgrade if they misfire.
CASE_STUDY_RE = re.compile(r"case[\s_-]?stud(y|ies)|success[\s_-]?stor(y|ies)|client[\s_-]?stor(y|ies)")
TESTIMONIAL_RE = re.compile(r"testimonial|what (our )?(clients|customers) (say|are saying)|trusted by|loved by"
                            r"|client reviews|★★★★★"
                            r"|^>\s*[\"“]|^\s*[\"“][^\"”\n]{30,}[\"”]",  # a quote on its own line (BMV, Captivate)
                            re.MULTILINE)
BLOG_RE = re.compile(r"\bblog\b|/blog|\binsights\b|/insights|\barticles\b|/articles")
LOGO_ALT_RE = re.compile(r"!\[(?:image \d+: )?([^\]]*logo[^\]]*)\]", re.IGNORECASE)
LOGO_NOISE_WORDS = {"logo", "logos", "grayscale", "greyscale", "white", "black", "color", "colour", "dark",
                    "light", "svg", "png", "webp", "client", "company", "the"}
NOT_CLIENTS = {"linkedin", "youtube", "x", "twitter", "facebook", "instagram", "tiktok", "github", "dribbble",
               "behance", "clutch", "google", "image", "icon"}  # social icons and review badges, not clients

# ponytail: in-flight reads live in this process; fine for one Railway instance (see PLAN §7).
_in_flight: dict[str, asyncio.Task] = {}


@dataclass
class Site:
    context: str
    has_case_studies: bool
    has_testimonials: bool
    has_blog: bool
    word_count: int


@dataclass
class Page:
    """One page as a reader returned it. `links` is every (text, url) on it, including menus the markdown drops."""
    title: str
    description: str
    markdown: str
    links: list[tuple[str, str]]


def normalize(raw: str) -> tuple[str, str, str]:
    """Founder input -> (url, cache_key, url_type). Raises ValueError if it isn't a web address."""
    text = raw.strip()
    if not text or " " in text:
        raise ValueError("That doesn't look like a website address.")
    if "://" not in text:
        text = "https://" + text  # PRD §4: accept bare domains
    parts = urlsplit(text)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if "." not in host or parts.scheme not in ("http", "https") or "@" in parts.netloc:
        raise ValueError("That doesn't look like a website address.")
    path = parts.path.rstrip("/")
    is_social = any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)
    if is_social:  # each profile is its own cache entry: linkedin.com/company/acme
        return f"https://{host}{path}", f"{host}{path}".lower(), "social"
    return f"{parts.scheme}://{parts.hostname.lower()}{path}", host, "full"


def _logo_names(markdown: str) -> list[str]:
    """Client names from logo-wall image alt text, e.g. "logo_workos_grayscale" -> "workos"."""
    names = []
    for alt in LOGO_ALT_RE.findall(markdown):
        words = re.sub(r"[_\-.]+", " ", alt).lower().split()
        words = [w for w in words if w not in LOGO_NOISE_WORDS]
        if words and words[0] not in NOT_CLIENTS:
            names.append(words[0])
    return list(dict.fromkeys(names))[:8]


def _clean(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", markdown)          # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)           # links -> their text
    text = re.sub(r"<[^>]+>", " ", text)                            # stray HTML
    text = re.sub(r"\\([_*#\[\]()`])", r"\1", text)                  # markdown escapes: PYTHON\_ -> PYTHON_
    text = text.replace("**", "").replace("__", "")                 # bold markers
    text = re.sub(r"(?<![\w*])[_*]([^_*\n]+)[_*](?![\w*])", r"\1", text)  # _italic_ / *italic*
    return html.unescape(text)                                      # &amp; -> &


# Lines that are never the firm's pitch: cookie/consent banners, skip links, legal footer.
BOILERPLATE_RE = re.compile(r"cookie|consent|storage duration|about this provider|collected by this provider"
                            r"|skip to (main )?content|accept all|privacy (policy|settings|preferences)"
                            r"|all rights reserved|©"
                            r"|checking the site connection|verify you are human|just a moment\.\.\.|enable javascript",
                            re.IGNORECASE)  # last line: bot-check screens returned instead of the page


def _content_lines(text: str) -> list[str]:
    """The page's real content: from the main headline down, minus menus and boilerplate.
    Everything above the H1 (nav, banners, cookie popups) is skipped; with no "# " H1, the first heading is used."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines) if re.match(r"^#\s", line)), None)
    if start is None:
        start = next((i for i, line in enumerate(lines) if re.match(r"^#{1,6}\s", line)), 0)
    kept = []
    for line in lines[start:]:
        bullet = re.match(r"^[*+-]\s+(.*)", line)
        if BOILERPLATE_RE.search(line) or (bullet and len(bullet.group(1).split()) <= 5):
            continue  # boilerplate, or a menu item
        if len(line.split()) <= 2 and not line.startswith("#"):
            continue  # stray "Menu", "Back", button labels
        kept.append(line)
    return kept


def subpage_links(page_url: str, links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """[(kind, url)] for the case studies, services and about pages among a page's (text, href) links, same site
    only. An index page ("Case Studies" -> /case-studies) wins; failing that, one case study inside a matching
    folder (/portfolio/boson-ai) stands in for it."""
    home = urlsplit(page_url)
    host = (home.hostname or "").removeprefix("www.")
    exact: dict[str, str] = {}
    inside: dict[str, str] = {}
    for text, href in links:
        parts = urlsplit(urljoin(page_url, href))
        path = parts.path.rstrip("/")
        if (parts.scheme not in ("http", "https") or (parts.hostname or "").removeprefix("www.") != host
                or not path or path == home.path.rstrip("/")):
            continue
        link = f"{parts.scheme}://{parts.netloc}{parts.path}"
        label = re.sub(r"[^\w\s-]", "", text).strip().lower()
        *folders, slug = path.lower().split("/")
        for kind, pattern in SUBPAGES.items():
            if pattern.fullmatch(label) or pattern.fullmatch(slug):
                exact.setdefault(kind, link)
                break
            if kind == "case_studies" and folders and pattern.fullmatch(folders[-1]):
                inside.setdefault(kind, link)
    found = {**inside, **exact}
    return [(kind, found[kind]) for kind in SUBPAGES if kind in found]


def _page_summary(lines: list[str], words: int) -> str:
    """A linked page in brief: its headings and text from the top, joined with " · "."""
    kept, total = [], 0
    for line in lines:
        line = re.sub(r"^#{1,6}\s+", "", line)
        kept.append(" ".join(line.split()[: words - total]))
        total += len(line.split())
        if total >= words:
            break
    return " · ".join(kept)


def build_site(title: str, description: str, markdown: str, subpages: list[tuple[str, str, str]] = (),
               link_texts: list[str] = ()) -> Site:
    """Trim the homepage (+ linked pages, as (kind, url, markdown)) to what Claude needs: title, meta description,
    H1, first two sections, a summary of each linked page, logos, flags. Flags and logos read the WHOLE pages plus
    the homepage's link texts (a "Case Studies" menu item is real evidence, even when the markdown drops the menu);
    the content and the word count use only the real content, so a page of menus or cookie popups counts as unread."""
    raw = markdown or ""
    everything = "\n".join([raw, *(page for _, _, page in subpages), *link_texts])
    lowered = everything.lower()
    flags = {
        "has_case_studies": bool(CASE_STUDY_RE.search(lowered)) or any(k == "case_studies" for k, _, _ in subpages),
        "has_testimonials": bool(TESTIMONIAL_RE.search(lowered)),
        "has_blog": bool(BLOG_RE.search(lowered)),
    }
    lines = _content_lines(_clean(raw))
    sub_lines = [(kind, url, _content_lines(_clean(page))) for kind, url, page in subpages]
    # A linked page with almost no real content (a bot-check screen, a login wall) isn't a read.
    sub_lines = [(kind, url, sl) for kind, url, sl in sub_lines if len(" ".join(sl).split()) >= 20]
    word_count = len(" ".join(lines).split()) + sum(len(" ".join(sl).split()) for _, _, sl in sub_lines)

    # Split into (heading, body) sections.
    sections, heading, body = [], "", []
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*)", line)
        if match:
            if heading or body:
                sections.append((heading, " ".join(body)))
            heading, body = match.group(2).strip(), []
        else:
            body.append(line)
    sections.append((heading, " ".join(body)))
    h1 = next((h for h, _ in sections if h), "")
    content = [f"{h}: {b}" if h else b for h, b in sections if len(b.split()) >= 15][:2]
    content_words = " ".join(content).split()[: CONTEXT_WORDS - 60]

    logos = [name for name in _logo_names(everything) if name not in title.lower()][:8]  # own logo isn't a client
    yes = lambda flag: "yes" if flag else "no"
    pages = [f"{SUBPAGE_TITLES[kind]} ({urlsplit(url).path}): {_page_summary(sl, SUBPAGE_WORDS[kind])}"
             for kind, url, sl in sub_lines]
    context = "\n".join([
        f"Page title: {html.unescape(title).strip()}",
        f"Meta description: {html.unescape(description).strip()}",
        f"H1: {h1}",
        f"Main content: {' '.join(content_words)}",
        *pages,
        # Keyword checks on the pages read: "no" means "not detected", never "doesn't exist" (live QA 26 Sept).
        f"Pages read: homepage{''.join(', ' + urlsplit(url).path for _, url, _ in sub_lines)}",
        f"Client logos named on these pages: {', '.join(logos) if logos else 'none detected (unlabelled logo images cannot be read)'}",
        f"Case studies detected (automated check of these pages, can miss things): {yes(flags['has_case_studies'])}",
        f"Testimonials detected (automated check of these pages, can miss things): {yes(flags['has_testimonials'])}",
        f"Blog or insights section detected: {yes(flags['has_blog'])}",
    ])
    return Site(context=context, word_count=word_count, **flags)


async def _jina(url: str) -> Page:
    # The links summary lists every link in the page's HTML, menus included; the markdown often drops the menu.
    headers = {"Accept": "application/json", "X-With-Links-Summary": "true"}
    if config.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {config.JINA_API_KEY}"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(f"https://r.jina.ai/{url}", headers=headers)
        if response.status_code == 429:  # keyless Jina allows ~20 requests/minute; wait once, then give up
            await asyncio.sleep(3)
            response = await client.get(f"https://r.jina.ai/{url}", headers=headers)
        response.raise_for_status()
        data = response.json().get("data") or {}
        markdown = data.get("content") or ""
        summary = data.get("links") or {}
        summary = list(summary.items()) if isinstance(summary, dict) else []
        return Page(data.get("title") or "", data.get("description") or "", markdown,
                    LINK_RE.findall(markdown) + summary)


async def _firecrawl(url: str) -> Page:
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {config.FIRECRAWL_API_KEY}"},
            # onlyMainContent=False, unlike PRD §9.2: "main content" strips the nav, which is where the Case Studies
            # and Blog links live (the yes/no flags need them), and on some sites leaves under 100 words.
            json={"url": url, "formats": ["markdown", "links"], "onlyMainContent": False},
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        meta = data.get("metadata") or {}
        markdown = data.get("markdown") or ""
        return Page(meta.get("title") or "", meta.get("description") or "", markdown,
                    LINK_RE.findall(markdown) + [("", link) for link in data.get("links") or [] if isinstance(link, str)])


async def _linked_pages(fetch, home: str, page: Page) -> list[tuple[str, str, str]]:
    """Read the case studies / services / about pages linked from the homepage, in parallel. Failures are skipped."""
    links = subpage_links(home, page.links)
    pages = await asyncio.gather(*(asyncio.wait_for(fetch(link), SUBPAGE_TIMEOUT) for _, link in links),
                                 return_exceptions=True)
    for (_, link), sub in zip(links, pages):
        if isinstance(sub, BaseException):
            log.warning("Linked page failed for %s: %r", link, sub)
    return [(kind, link, sub.markdown) for (kind, link), sub in zip(links, pages) if not isinstance(sub, BaseException)]


def _home_words(page: Page) -> int:
    return build_site(page.title, page.description, page.markdown).word_count


async def read(url: str, url_type: str) -> tuple[Site | None, str]:
    """Read a site live (no cache). Returns (site or None, which reader produced it)."""
    page, fetch, source = None, None, "none"
    try:
        page, fetch, source = await _jina(url), _jina, "jina"
    except Exception as error:  # a failed reader must never break the audit
        log.warning("Jina failed for %s: %s", url, error)
    # Firecrawl renders JavaScript (Framer, SPAs). Social profiles skip it: they sit behind a login.
    if (page is None or _home_words(page) < MIN_WORDS) and url_type == "full" and config.FIRECRAWL_API_KEY:
        try:
            fallback = await _firecrawl(url)
            if page is None or _home_words(fallback) > _home_words(page):
                page, fetch, source = fallback, _firecrawl, "firecrawl"
        except Exception as error:
            log.warning("Firecrawl failed for %s: %s", url, error)
    if page is None:
        return None, source
    # Linked pages use whichever reader worked for the homepage (a Framer homepage has Framer subpages).
    subpages = await _linked_pages(fetch, url, page) if url_type == "full" else []
    site = build_site(page.title, page.description, page.markdown, subpages, [text for text, _ in page.links])
    return (site if site.word_count >= MIN_WORDS else None), source


async def _read_and_cache(url: str, key: str, url_type: str) -> Site | None:
    site, _ = await read(url, url_type)
    if site:
        await db.save_site(key, site)  # only good reads are cached; failures retry next time
    return site


async def start(url: str | None, key: str | None, url_type: str) -> None:
    """Kick off a background read when the founder submits their URL (PRD §4)."""
    if url_type == "none" or not key or key in _in_flight or await db.get_site(key):
        return
    task = asyncio.create_task(_read_and_cache(url, key, url_type))
    _in_flight[key] = task
    task.add_done_callback(lambda _: _in_flight.pop(key, None))


async def get(url: str | None, key: str | None, url_type: str, wait: float = 8.0) -> Site | None:
    """The website context for the audit. Waits at most `wait` seconds for a read still running (PRD §4).
    8s, not 4: reading linked pages makes a read take longer, and an unread site is the worst outcome (PRD §12.2)."""
    if url_type == "none" or not key:
        return None
    if key not in _in_flight:
        cached = await db.get_site(key)
        if cached:
            return cached
        await start(url, key, url_type)
    task = _in_flight.get(key)
    if task is None:
        return await db.get_site(key)
    try:
        return await asyncio.wait_for(asyncio.shield(task), wait)
    except asyncio.TimeoutError:
        return None
