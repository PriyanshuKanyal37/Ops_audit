"""Gate 1 (PLAN §9): read real B2B service websites live and check that 95%+ return 200+ words,
with at least 5 built on Framer or Webflow. Nothing is cached or saved to the database.

Usage:  python scrape_check.py            -> prints a summary, writes fixtures/out/scrape_check.md
"""

import asyncio
import logging
import pathlib
import time

import httpx

import config
import scrape

SITES = [
    # Marketing, content and growth agencies
    "animalz.co", "siegemedia.com", "directiveconsulting.com", "growthmachine.com", "omniscientdigital.com",
    "singlegrain.com", "ninjapromo.io", "kalungi.com", "gripped.io", "velocitypartners.com", "growandconvert.com",
    "fractl.com",
    # Dev shops and design studios
    "thoughtbot.com", "10up.com", "netguru.com", "stxnext.com", "boldare.com", "metalab.com", "ustwo.com",
    "clay.global", "ramotion.com", "halo-lab.com", "focuslabllc.com",
    # Webflow / Framer agencies (platform is detected, not assumed)
    "flowninja.com", "finsweet.com", "edgarallan.com", "refokus.com", "broworks.net", "veza.digital",
    "webstacks.com", "designmonks.co", "nixtio.com",
    "goodspeed.studio", "designme.agency", "framer.com",
    # Consulting, fractional, professional services, staffing, MSPs
    "chiefoutsiders.com", "kruzeconsulting.com", "pilot.com", "ntiva.com", "dataprise.com", "toptal.com",
    "bairesdev.com",
]

MARKERS = [("framer", ("framerusercontent.com", 'content="framer')), ("webflow", ("data-wf-site", "webflow.com")),
           ("wordpress", ("wp-content",)), ("next.js", ("/_next/static",)), ("hubspot", ("hs-scripts.com",))]


async def detect_platform(client: httpx.AsyncClient, url: str) -> str:
    try:
        html = (await client.get(url)).text.lower()
    except Exception:
        return "unreachable"
    return next((name for name, needles in MARKERS if any(n in html for n in needles)), "other")


async def check(url_text: str, client: httpx.AsyncClient, gate: asyncio.Semaphore) -> dict:
    url, _, url_type = scrape.normalize(url_text)
    platform = await detect_platform(client, url)
    async with gate:
        started = time.monotonic()
        site, source = await scrape.read(url, url_type)
        seconds = round(time.monotonic() - started, 1)
    return {"site": url_text, "platform": platform, "ok": site is not None, "source": source, "seconds": seconds,
            "words": site.word_count if site else 0, "context": site.context if site else "",
            "flags": "".join(f for f, on in (("C", site and site.has_case_studies), ("T", site and site.has_testimonials),
                                             ("B", site and site.has_blog)) if on)}


async def main() -> None:
    logging.basicConfig(level=logging.ERROR)
    gate = asyncio.Semaphore(2)  # Jina without a key allows ~20 requests a minute
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
        rows = await asyncio.gather(*(check(s, client, gate) for s in SITES))

    passed = sum(r["ok"] for r in rows)
    # A site that also refuses a plain browser request is down or bot-blocked, not a reader failure.
    reachable = [r for r in rows if r["platform"] != "unreachable" or r["ok"]]
    js_sites = [r for r in rows if r["platform"] in ("framer", "webflow")]
    rate = passed / len(reachable)
    lines = [
        f"# Scrape check ({time.strftime('%Y-%m-%d %H:%M')})",
        f"Firecrawl fallback: {'ON' if config.FIRECRAWL_API_KEY else 'OFF (no key)'} · Jina key: "
        f"{'yes' if config.JINA_API_KEY else 'no'}",
        f"**Gate 1: {passed}/{len(reachable)} reachable sites returned 200+ words ({rate:.0%}) → "
        f"{'PASS ✅' if rate >= 0.95 and len(js_sites) >= 5 else 'FAIL ❌'}** (target 95%+, 5+ Framer/Webflow)",
        f"All sites incl. unreachable: {passed}/{len(rows)}. Framer/Webflow sites: {len(js_sites)} "
        f"({sum(r['ok'] for r in js_sites)} passed).",
        "", "| Site | Platform | Result | Reader | Words | Flags | Seconds |", "|---|---|---|---|---|---|---|",
        *[f"| {r['site']} | {r['platform']} | {'✅' if r['ok'] else '❌'} | {r['source']} | {r['words']} | "
          f"{r['flags'] or '—'} | {r['seconds']} |" for r in rows],
        "", "Flags: C = case studies, T = testimonials, B = blog/insights.",
    ]
    out = pathlib.Path(__file__).parent / "fixtures" / "out" / "scrape_check.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    # Exactly what Claude would receive for each site, for a human to read (quality, not just quantity).
    contexts = [f"## {r['site']} ({r['source']}, {r['words']} content words)\n```\n{r['context'] or 'UNAVAILABLE'}\n```"
                for r in rows]
    (out.parent / "scrape_contexts.md").write_text("# What Claude sees per site\n\n" + "\n\n".join(contexts),
                                                   encoding="utf-8")
    print("\n".join(lines))
    print(f"\nContexts for review: {out.parent / 'scrape_contexts.md'}")


if __name__ == "__main__":
    asyncio.run(main())
