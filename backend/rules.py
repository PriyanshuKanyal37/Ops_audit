"""The deterministic half of the audit: everything that's a lookup, a sum or a check.
Code picks the three gaps, sizes them and sets the scores from the evidence (pick_gaps); Claude only writes the
words; this file then checks Claude's answer and assembles the report (PRD §2.3, §5, §6.3, §7.6, §7.9, §8.4).
Pure functions only, no I/O, so test_rules.py can cover all of it.
"""

import re
from datetime import datetime, timezone

import library

LEAK_IDS = tuple(library.LEAKS)
RELATIONSHIP_CHANNELS = {"referrals", "personal_network", "partnerships"}

# Claude Sonnet 5 prices, USD per million tokens (cache write = 1.25× input, cache read = 0.1× input).
PRICE_INPUT, PRICE_OUTPUT, PRICE_CACHE_WRITE, PRICE_CACHE_READ = 2.00, 10.00, 2.50, 0.20


def sentence(text: str) -> str:
    """Trim and capitalise the first letter (Claude sometimes starts a field lowercase)."""
    text = text.strip()
    return text[:1].upper() + text[1:]


def band_for(q4: str) -> tuple[str, bool]:
    """Q4 answer -> (revenue band, inferred?). "I'd rather not say" defaults to $100K–200K (PRD §4)."""
    if q4 == "rather_not_say":
        return library.RATHER_NOT_SAY_BAND, True
    return q4, False


def round100(value: float) -> int:
    return int((value + 50) // 100 * 100)  # half-up, so 250 -> 300 (Python's round() would give 200)


# --- Evidence scoring: code, not Claude, picks and sizes the three gaps (26 Sept; PLAN §6) ---
# Live QA showed Claude choosing differently for identical answers and ignoring its own selection steps.
# Every PRD §5 trigger that code can check is a signal. Points follow the PRD's own wording:
#   2    "strongly triggered" (PRD §4: 1–2 relationship ticks in Q2; no website)
#   1.5  a Q3 tick ("highest-recognition question… each option maps directly to a leak")
#   1    any other trigger: a Q5 admission, "no outbound/content ticked", a website finding
#   0.5  "no inbound ticked" (only "a signal" in PRD §4), and Q1 ("a weighting signal, not a router")
#   -1   counter-evidence: case studies and testimonials found on the site (against No Proof Layer)
# A gap is eligible only with one of its DEFINING signals (core=True). Supporting ones (Q1, and a Q3 tick the
# PRD also lists under a neighbouring gap, like "chasing new business" under both L4 and L5) add strength but
# can't qualify a gap alone: live sim picked "No Systematic Outbound" for a founder who ticked outbound.
# ponytail: triggers that need a judgement of the site's wording (L1 "generic or dated positioning", L6 "stale
# last post") are left out; add a model-based check if Shiv's call feedback (PRD §12.4) shows L1 is missed.
Q3_POINTS = 1.5


def signals(answers: dict, url_type: str, site) -> dict[str, list[tuple[float, str, bool]]]:
    """Every trigger that fired, per leak, as (points, reason, core). `site` is the website read (scrape.Site)
    or None. Reasons are written to the founder: they're shown on the report and given to Claude as evidence."""
    q1, q2, q3, q5 = answers["q1"], set(answers["q2"]), set(answers["q3"]), answers["q5"]
    read = site is not None
    primary = f'You named "{library.Q1[q1]}" as your main breakdown'
    week = {key: "Your week goes to " + (text[0].lower() + text[1:]).replace("only I ", "only you ")
            for key, text in library.Q3.items()}
    referral = "You said most prospects arrive pre-sold through a referral"
    fired: dict[str, list[tuple[float, str, bool]]] = {leak_id: [] for leak_id in library.LEAKS}

    def add(leak_id: str, when: bool, reason: str, points: float = 1.0, core: bool = True) -> None:
        if when:
            fired[leak_id].append((points, reason, core and reason != primary))

    def ticked(leak_id: str, key: str, core: bool = True) -> None:
        add(leak_id, key in q3, week[key], Q3_POINTS, core)

    add("L1", q5 == "dated_site", "You said your website is a couple of years behind where the business is now")
    add("L1", q1 == "A", primary, 0.5)
    add("L2", q5 == "no_proof", "You said prospects see a decent website but no case studies or proof")
    add("L2", q5 == "referral_presold", referral)  # PRD §4 Q5 note, gap #6
    add("L2", url_type == "none", "You don't have a website to show proof on")
    add("L2", read and not site.has_case_studies and not site.has_testimonials,
        "We found no case studies or testimonials on the pages we read")
    add("L2", read and site.has_case_studies and site.has_testimonials,
        "We found case studies and testimonials on your site", -1.0, core=False)
    add("L2", q1 in ("A", "D"), primary, 0.5)
    add("L3", "inbound_website" not in q2, "You didn't tick inbound through your website as a lead source", 0.5)
    add("L3", q5 == "stale_linkedin", "You said your LinkedIn profile hasn't been touched in a while")
    add("L3", q5 == "dont_know", "You said you don't know what prospects see before they talk to you")
    add("L3", url_type == "none", "You don't have a website yet", 2.0)  # PRD §4: strongly triggered
    add("L3", url_type == "social", "You gave a social profile instead of a website")
    add("L3", url_type == "full" and not read, "We couldn't read enough of your website to see what you offer")
    # PRD §4: "1–2 ticks including referrals or personal network" is strongly triggered. 3 ticks that are all
    # relationships (referrals + network + partners) is the same situation, so it counts too.
    add("L4", bool(q2 & {"referrals", "personal_network"}) and (len(q2) <= 2 or q2 <= RELATIONSHIP_CHANNELS),
        "Your leads come only through referrals, your network or partners", 2.0)
    add("L4", q5 == "referral_presold", referral)
    ticked("L4", "chasing_new_business", core=False)
    add("L4", q1 == "A", primary, 0.5)
    add("L5", "outbound" not in q2, "You didn't tick cold email or outbound as a lead source")
    ticked("L5", "chasing_new_business", core=False)
    add("L5", q1 == "A", primary, 0.5)
    add("L6", "linkedin_content" not in q2, "You didn't tick LinkedIn or content as a lead source")
    add("L6", q5 == "stale_linkedin", "You said your LinkedIn profile hasn't been touched in a while")
    add("L6", read and not site.has_blog, "We found no blog or insights section on the pages we read")
    ticked("L7", "following_up_leads")
    add("L7", len(q2) >= 4 and "chasing_new_business" in q3,
        f"You have {len(q2)} lead channels but still chase new business personally")
    add("L7", q1 == "A", primary, 0.5)
    ticked("L8", "writing_proposals")
    ticked("L8", "unblocking_team", core=False)
    add("L8", q1 in ("A", "B"), primary, 0.5)
    ticked("L9", "unblocking_team")
    add("L9", len(q3) >= 4, f"You ticked {len(q3)} of the 7 places a week can go", core=False)
    add("L9", q1 in ("C", "E"), primary, 0.5)
    ticked("L10", "onboarding_by_hand")
    add("L10", q1 == "B", primary, 0.5)
    ticked("L11", "chasing_status")
    add("L11", q1 in ("C", "E"), primary, 0.5)
    ticked("L12", "fixing_inconsistent_work")
    add("L12", q1 in ("C", "D"), primary, 0.5)
    return fired


def size_range(strength: float, cell: tuple[int, int]) -> tuple[int, int]:
    """PRD §6.3 "more triggering signals means higher in the range": 1 point sits at the bottom of the cell,
    2 in the middle, 3+ at the top. The range is 40% of the cell wide (at least $500) so it never reads as exact."""
    lo, hi = cell
    width = min(hi - lo, max(500, round100((hi - lo) * 0.4)))
    position = (min(max(strength, 1), 3) - 1) / 2
    low = lo + round100(position * (hi - lo - width))
    return low, low + width


def impact(gap: dict) -> float:
    """Expected monthly cost: the range's midpoint, discounted when the evidence is thin (1 point counts a third,
    3+ points count fully). PRD gap: the PRD ranks by dollars alone, which lets a heavy gap with one weak signal
    ("didn't tick outbound") beat a medium gap the founder described in three answers. Needs Shiv's OK."""
    return (gap["monthly_low"] + gap["monthly_high"]) / 2 * min(gap["strength"], 3) / 3


def pick_gaps(answers: dict, url_type: str, site, band: str) -> dict:
    """The diagnosis: the three gaps (in dollar order, with ranges and evidence) and the four pillar scores.
    Selection is PRD §2.3/§8.1: rank every eligible gap, take the top two, and if they share a pillar the third
    comes from a different one."""
    candidates = []
    for order, (leak_id, found) in enumerate(signals(answers, url_type, site).items()):
        meta = library.LEAKS[leak_id]
        strength = max(sum(points for points, _, _ in found), 0)
        low, high = size_range(strength, library.BAND_TABLE[band][meta["weight"]])
        candidates.append({"leak_id": leak_id, "name": meta["name"], "pillar": meta["pillar"],
                           "weight": meta["weight"], "strength": strength, "order": order,
                           "eligible": any(points > 0 and core for points, _, core in found),
                           "signals": [reason for points, reason, _ in found if points > 0],
                           "against": [reason for points, reason, _ in found if points < 0],
                           "monthly_low": low, "monthly_high": high})
    ranked = sorted(candidates, reverse=True, key=lambda c: (
        c["eligible"], impact(c), c["strength"], library.WEIGHT_ORDER[c["weight"]], -c["order"]))
    first, second = ranked[:2]
    third = next(c for c in ranked[2:] if first["pillar"] != second["pillar"] or c["pillar"] != first["pillar"])
    chosen = order_leaks([first, second, third])
    return {"leaks": chosen, "scores": pillar_scores(chosen, candidates, url_type)}


def pillar_scores(chosen: list[dict], candidates: list[dict], url_type: str) -> dict[str, int]:
    """Scorecard numbers (PRD §8.1): a pillar with a selected gap scores 5 or below, lower with more evidence;
    a pillar without one scores 7–9, lower when its other gaps still had some evidence. With at most three
    pillars selected, all four are never low, except with no website: PRD §4's specific "Credibility 1–2" wins
    over §8.1's general "never all four low" (found by the random check in test_rules.py)."""
    selected = {gap["pillar"] for gap in chosen}
    scores = {}
    for pillar in library.PILLARS:
        strongest = max((c["strength"] for c in candidates if c["pillar"] == pillar and c["eligible"]), default=0)
        if pillar in selected:
            score = 5 if strongest < 2 else 4 if strongest < 3 else 3
        else:
            score = 9 if strongest == 0 else 8 if strongest < 2 else 7
        scores[pillar] = min(score, 2) if pillar == "credibility" and url_type == "none" else score
    return scores


SENTENCE_END_RE = re.compile(r"[.!?][\"”’')]*$")


def problems(out: dict, expected: list[str]) -> list[str]:
    """Hard errors in Claude's answer that justify a retry. Empty list = usable.
    `expected` is the leak ids code picked; Claude must write about exactly those."""
    ids = [leak["leak_id"] for leak in out.get("leaks", [])]
    found = []
    if len(ids) != 3 or set(ids) != set(expected):
        found.append(f"write exactly one leaks entry for each gap in the diagnosis: {', '.join(expected)}")
    # Live QA: a the_read ended "...still presents a generic" (a double quote closed the string early).
    # fix_* fields are phrases by design, so only the full-sentence fields are checked.
    texts = [("the_read", out.get("the_read", ""))] + [
        (f"{leak['leak_id']} {field}", leak.get(field, ""))
        for leak in out.get("leaks", []) for field in ("description", "proof_tie_in")]
    cut = [name for name, text in texts if not SENTENCE_END_RE.search(text.strip())]
    if cut:
        found.append(f"these fields stop mid-sentence, write them in full (quote with single quotes): {', '.join(cut)}")
    return found


def order_leaks(leaks: list[dict]) -> list[dict]:
    """Dollar order: by range midpoint, then heavier weight (PRD gap #1: midpoint is our tie-break rule)."""
    return sorted(
        leaks,
        key=lambda leak: (-(leak["monthly_low"] + leak["monthly_high"]), -library.WEIGHT_ORDER[leak["weight"]]),
    )


def cta_route(top_pillar: str) -> str:
    return "booking" if top_pillar == "delivery" else "client_engine"


def bridge_sentence(leaks: list[dict]) -> str:
    """CTA bridge copy (PRD §7.9), built in code so the prompt can forbid mentioning the Client Engine."""
    if cta_route(leaks[0]["pillar"]) == "booking":
        return library.CTA_BOOKING
    names = [leak["name"] for leak in leaks if leak["pillar"] in library.CLIENT_ENGINE_PILLARS]
    if len(names) == 3:
        return (f"All three of your gaps — {names[0]}, {names[1]} and {names[2]} — "
                "are exactly what the Client Engine is built to fix.")
    if len(names) == 2:
        return f"Two of your three gaps — {names[0]} and {names[1]} — are exactly what the Client Engine is built to fix."
    return f"Your biggest gap — {names[0]} — is exactly what the Client Engine is built to fix."


def cost_usd(usage) -> float:
    """Dollar cost of one Claude call from its `usage` block."""
    return (
        (usage.input_tokens or 0) * PRICE_INPUT
        + (usage.output_tokens or 0) * PRICE_OUTPUT
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * PRICE_CACHE_WRITE
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * PRICE_CACHE_READ
    ) / 1_000_000


def finalize(out: dict, diagnosis: dict, *, band: str, inferred: bool, website_url: str | None,
             domain: str | None, url_type: str, degraded: bool) -> dict:
    """Merge Claude's words (checked by `problems`) into the code's diagnosis (`pick_gaps`): the full report the
    frontend renders and the DB stores. Every number comes from the diagnosis, never from Claude."""
    written = {leak["leak_id"]: leak for leak in out["leaks"]}
    leaks = []
    for rank, gap in enumerate(diagnosis["leaks"], start=1):
        raw, meta = written[gap["leak_id"]], library.LEAKS[gap["leak_id"]]
        leaks.append({
            "rank": rank, "leak_id": gap["leak_id"], "name": meta["name"], "pillar": meta["pillar"],
            "weight": meta["weight"], "monthly_low": gap["monthly_low"], "monthly_high": gap["monthly_high"],
            "signals": gap["signals"],  # the evidence, shown on the report as "Why we flagged this"
            "description": sentence(raw["description"]),
            "non_dollar_cost": raw["non_dollar_cost"].strip(),  # stays lowercase: it follows "Also costing you:"
            "fix_name": meta["fix_name"],
            "fix_what_it_does": sentence(raw["fix_what_it_does"]),
            "fix_what_changes": sentence(raw["fix_what_changes"]),
            "fix_time_to_live": raw["fix_time_to_live"].strip(), "proof_tie_in": sentence(raw["proof_tie_in"]),
        })
    scores = {pillar: {"score": diagnosis["scores"][pillar], "rationale": sentence(out["score_rationales"][pillar])}
              for pillar in library.PILLARS}

    top = leaks[0]
    route = cta_route(top["pillar"])
    band_label = library.Q4[band]
    weights = ", ".join(leak["weight"] for leak in leaks[:2]) + f" and {leaks[2]['weight']}"
    company = out["company_name"].strip()
    # Without a readable website any descriptor is a guess from the domain name, so use a neutral word.
    website_read = url_type != "none" and not degraded
    descriptor = (out["business_descriptor"].strip() if website_read else "") or "firm"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "company_name": company,
        "business_descriptor": descriptor,
        # Banner fallbacks: no name found -> their domain; no website at all -> "Your business".
        "display_name": company or (domain if url_type == "full" else "") or "Your business",
        "verdict_subline": library.VERDICT_SUBLINE.format(descriptor=descriptor),
        "website_url": website_url, "domain": domain, "url_type": url_type,
        "band": band, "band_label": band_label, "mrr_inferred": inferred,
        "total_low": sum(leak["monthly_low"] for leak in leaks),
        "total_high": sum(leak["monthly_high"] for leak in leaks),
        "gap_count": len(leaks),
        "the_read": sentence(out["the_read"]),
        "scores": scores,
        "leaks": leaks,
        "top_leak_pillar": top["pillar"],
        "cta_route": route,
        "cta_bridge": bridge_sentence(leaks),
        "proof": {**library.CASE_STUDIES[top["pillar"]], "tie_in": top["proof_tie_in"]},
        "how_calculated": [p.format(band_label=band_label, weights=weights) for p in library.HOW_CALCULATED],
        "cant_see": [*library.CANT_SEE_STATIC, sentence(out["cant_see_item"])],
        "specificity_degraded": degraded,
    }
