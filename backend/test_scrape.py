"""Offline checks for scrape.py's pure functions and guard.py's session tokens. Run: python test_scrape.py"""

import time

import guard
import scrape

# --- URL normalising (PRD §4 URL screen) ---
assert scrape.normalize("acme.com") == ("https://acme.com", "acme.com", "full")                 # bare domain
assert scrape.normalize("  https://www.Acme.com/ ") == ("https://www.acme.com", "acme.com", "full")
assert scrape.normalize("http://acme.co.uk/services") == ("http://acme.co.uk/services", "acme.co.uk", "full")
assert scrape.normalize("linkedin.com/company/Acme/") == (
    "https://linkedin.com/company/Acme", "linkedin.com/company/acme", "social")                 # social, own cache key
assert scrape.normalize("https://www.linkedin.com/in/jane")[2] == "social"
assert scrape.normalize("instagram.com/acme")[2] == "social"
assert scrape.normalize("notlinkedin.com")[2] == "full"                                          # no false social match
for bad in ["", "   ", "hello", "acme com", "ftp://acme.com", "mailto:x@acme.com"]:
    try:
        scrape.normalize(bad)
        raise AssertionError(f"should reject {bad!r}")
    except ValueError:
        pass

# --- Trimming a page for Claude (PRD §9.2) ---
page = """[Home](/) [Services](/services) [Case Studies](/case-studies) [Blog](/blog)

## Intelligent content for compounding growth

![Image 1: logo_workos_grayscale](https://x/logo_workos.svg) ![Image 2: logo_airtable_grayscale](https://x/a.svg)
![Image 3: Airtable logo](https://x/b.svg) ![Image 4: team photo](https://x/team.jpg)

## A content marketing agency for B2B SaaS brands

We build content programs that compound, combining original research, product-led storytelling and
search strategy for SaaS teams that need pipeline, not pageviews. Our editors work as an extension of your team.

## What clients say

"They doubled our organic signups in nine months and made our founders sound like themselves," said the VP of marketing at a
Series B company, one of many testimonials we are proud of across a decade of work with software businesses.
""" + " filler" * 200
site = scrape.build_site("Animalz | Content Marketing", "A content agency for SaaS.", page)
assert site.has_case_studies and site.has_blog and site.has_testimonials
assert site.word_count > 200
ctx = site.context
assert "Page title: Animalz | Content Marketing" in ctx and "Meta description: A content agency for SaaS." in ctx
assert "H1: Intelligent content for compounding growth" in ctx          # first heading stands in for a missing H1
assert "Client logos named on these pages: workos, airtable" in ctx     # alt text -> names, deduplicated
assert "A content marketing agency for B2B SaaS brands: We build content programs" in ctx
assert "team photo" not in ctx and "](" not in ctx                     # images and link syntax stripped
assert len(ctx.split()) <= 320                                          # ~300 words for Claude

# Real-world junk found in Phase 4 QA: nav before the H1 (thoughtbot) and a cookie popup instead of content (stxnext).
nav_then_h1 = ("[Skip to main content](#main)\nClose Menu\n* [Case Studies](/case-studies)\n* [Blog](/blog)\nMenu\n"
               "* Ruby on Rails\n* Hotwire\n# When the stakes are high, experience matters\n"
               "We are a design and development consultancy that has shipped products for founders and enterprise "
               "teams since 2003, pairing senior designers and developers with your team.\n"
               "Cookie settings: we use cookies to improve your experience. Accept all\n© 2026 thoughtbot, inc.")
site = scrape.build_site("thoughtbot", "Design &amp; development", nav_then_h1)
assert "H1: When the stakes are high, experience matters" in site.context
assert "Main content: When the stakes are high, experience matters: We are a design" in site.context  # nav skipped
assert "Menu" not in site.context and "Cookie" not in site.context and "©" not in site.context
assert "Meta description: Design & development" in site.context                                       # &amp; decoded
assert site.has_case_studies and site.has_blog                    # flags still see the nav links above the H1
assert site.word_count < 60                                       # only real content counts towards MIN_WORDS
cookie_popup = "\n".join(["* Necessary cookies help make a website usable by enabling basic functions.",
                          "**Maximum Storage Duration**: 1 year**Type**: HTTP Cookie"] * 150)
assert scrape.build_site("STX Next", "", cookie_popup).word_count == 0   # 2,000+ raw words of cookie text = unread
provider_popup = "* Google 1Learn more about this provider Some of the data collected by this provider is for personalization\n" * 90
assert scrape.build_site("STX Next", "", provider_popup).word_count == 0  # consent text without the word "cookie"
assert "H1: AI-native commerce" in scrape.build_site("", "", "# **AI-native** commerce\nx").context  # bold markers gone
assert "H1: Managed IT Services Built Around You" in scrape.build_site("", "", "# _Managed IT Services_ Built Around You").context

own_logo = "![Image 1: zeritaz logo](z.svg) ![Image 2: logo_paddle](p.svg)\n# CFO & Accounting Consultancy"
assert "Client logos named on these pages: paddle" in scrape.build_site("Home | Zeritaz Advisors", "", own_logo).context
social = "![Image 1: LinkedIn logo](l.svg) ![Image 2: logo_youtube](y.svg) ![Image 3: Babbel logo](b.svg)\n# Recruiting"
assert "Client logos named on these pages: babbel" in scrape.build_site("", "", social).context  # icons aren't clients

# --- Linked pages: case studies, services, about (26 Sept) ---
home = "https://acme.com"
links = [("Home", "/"), ("Services", "/services/"), ("Seed Stories", "/seedstories/"), ("Boson AI", "/portfolio/boson-ai/"),
         ("Case Studies", "https://www.acme.com/learn/case-studies/"), ("About Us", "/about-us#team"),
         ("Blog", "/blog"), ("Twitter", "https://twitter.com/acme"), ("Partner Login", "https://partners.other.com/")]
assert scrape.subpage_links(home, links) == [
    ("case_studies", "https://www.acme.com/learn/case-studies/"),  # the index page beats one case study in a folder
    ("services", "https://acme.com/services/"), ("about", "https://acme.com/about-us")]  # the site's own link, no #
assert scrape.subpage_links(home, [("Boson AI", "/portfolio/boson-ai/")]) == \
    [("case_studies", "https://acme.com/portfolio/boson-ai/")]    # BMV: no index page, one case study stands in
assert scrape.subpage_links(home, [("Our Work", "/w"), ("What We Do", "/x"), ("Who We Are", "/y")]) == \
    [("case_studies", "https://acme.com/w"), ("services", "https://acme.com/x"), ("about", "https://acme.com/y")]
assert scrape.subpage_links(home, [("Work with us", "/contact"), ("", "/"), ("Services", "https://other.com/services")]) == []
assert scrape.subpage_links(home, [("", "https://acme.com/clients/")]) == [("case_studies", "https://acme.com/clients/")]

case_page = "Menu\n# Our clients\n## Harmonya hires a CRO\n\"They sharpened the search in real time.\"\nRead more\n" + "word " * 400
about_page = "# digitalboardwalk.com\nChecking the site connection security"   # a bot-check screen, not the page
with_pages = scrape.build_site("Acme", "", "# Acme\nWe recruit revenue leaders for SaaS startups.",
                               [("case_studies", "https://acme.com/clients", case_page),
                                ("about", "https://acme.com/about", about_page)], ["Case Studies", "Blog"])
ctx = with_pages.context
assert "Case studies page (/clients): Our clients · Harmonya hires a CRO · \"They sharpened" in ctx
assert "About page" not in ctx and "connection security" not in ctx               # the bot check is dropped
assert "Pages read: homepage, /clients" in ctx and "Read more" not in ctx
assert with_pages.has_case_studies and with_pages.has_testimonials and with_pages.has_blog  # from the pages + menu text
assert with_pages.word_count > scrape.MIN_WORDS                                   # linked pages count towards a read
assert len(ctx.split("Case studies page (/clients): ")[1].split("\n")[0].split()) <= scrape.SUBPAGE_WORDS["case_studies"] + 10

# Live QA: BMV's testimonials are bare blockquotes with no "testimonial" heading.
quoted = "# B2B Tech PR\n> “Kyle and the BMV team have been an extension of our marketing team.”\n"
assert scrape.build_site("", "", quoted).has_testimonials
assert not scrape.build_site("", "", "# Acme\n> Note: we are closed on Fridays.").has_testimonials  # unquoted callout

from datetime import datetime, timezone  # noqa: E402
assert datetime.fromisoformat(scrape.CLEANING_VERSION).tzinfo is not None  # must parse, with a UTC offset
# A version in the future silently disables the cache: every read counts as stale (happened twice on 26 Sept).
assert datetime.fromisoformat(scrape.CLEANING_VERSION) <= datetime.now(timezone.utc), "CLEANING_VERSION is in the future"

bare = scrape.build_site("", "", "# Acme Consulting\n\nWe advise founders on growth strategy and operations.")
assert "H1: Acme Consulting" in bare.context and not (bare.has_case_studies or bare.has_blog or bare.has_testimonials)
assert "Client logos named on these pages: none detected" in bare.context and bare.word_count < scrape.MIN_WORDS
assert "Testimonials detected (automated check of these pages, can miss things): no" in bare.context
assert "Pages read: homepage\n" in bare.context

# --- Session tokens (guard.py) ---
token = guard.make_session({"url": "https://acme.com", "key": "acme.com", "url_type": "full"})
assert guard.read_session(token)["key"] == "acme.com"
payload, sig = token.split(".")
for forged in [payload + "." + "0" * len(sig), payload[:-2] + "xx." + sig, payload, ""]:
    try:
        guard.read_session(forged)
        raise AssertionError("forged token accepted")
    except (ValueError, KeyError):
        pass
guard.SESSION_TTL_SECONDS = -1                                          # expired token is rejected
try:
    guard.read_session(guard.make_session({"key": "x"}))
    raise AssertionError("expired token accepted")
except ValueError:
    pass
assert guard.ip_hash("1.2.3.4") == guard.ip_hash("1.2.3.4") != guard.ip_hash("1.2.3.5")
assert len(guard.ip_hash("1.2.3.4")) == 64 and "1.2.3.4" not in guard.ip_hash("1.2.3.4")

# --- Spend alert levels (PRD §9.4: Slack at 80%, and when the cap is hit) ---
assert guard.spend_alert_level(0, 20) is None and guard.spend_alert_level(15.99, 20) is None
assert guard.spend_alert_level(16, 20) == 80 and guard.spend_alert_level(19.99, 20) == 80
assert guard.spend_alert_level(20, 20) == 100 and guard.spend_alert_level(25, 20) == 100

print("test_scrape.py: all checks passed")
