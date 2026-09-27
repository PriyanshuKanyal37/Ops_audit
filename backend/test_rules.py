"""Checks for rules.py and the library data. Run: python test_rules.py"""

import json
import random
from types import SimpleNamespace

import library
import rules


def site(case_studies=False, testimonials=False, blog=False):
    """A website read with these yes/no flags (the only parts of scrape.Site that scoring uses)."""
    return SimpleNamespace(has_case_studies=case_studies, has_testimonials=testimonials, has_blog=blog)


def fake_out(*ids):
    """A Claude-shaped answer (words only) for these leak ids."""
    leaks = [{"leak_id": i, "description": f"desc {i}.", "non_dollar_cost": "x", "fix_what_it_does": "a",
              "fix_what_changes": "b", "fix_time_to_live": "2–3 weeks", "proof_tie_in": f"tie-in for {i}."}
             for i in ids]
    return {"company_name": " Acme ", "business_descriptor": "growth agency", "the_read": "read.",
            "score_rationales": {p: "why" for p in library.PILLARS}, "leaks": leaks, "cant_see_item": "generated item"}


def fake_diagnosis(*specs, scores=None):
    """A pick_gaps-shaped diagnosis; specs are (leak_id, low, high) in dollar order."""
    leaks = [{"leak_id": i, "name": library.LEAKS[i]["name"], "pillar": library.LEAKS[i]["pillar"],
              "weight": library.LEAKS[i]["weight"], "monthly_low": lo, "monthly_high": hi, "signals": [f"s {i}"]}
             for i, lo, hi in specs]
    return {"leaks": leaks, "scores": scores or {p: 8 for p in library.PILLARS}}


def finalize(*specs, band="200k_350k", out=None, **kwargs):
    options = {"inferred": False, "website_url": "https://acme.com", "domain": "acme.com", "url_type": "full",
               "degraded": False, **kwargs}
    return rules.finalize(out or fake_out(*[s[0] for s in specs]), fake_diagnosis(*specs), band=band, **options)


def picks(answers, url_type="full", read=None, band="100k_200k"):
    return [gap["leak_id"] for gap in rules.pick_gaps(answers, url_type, read, band)["leaks"]]


# --- Library data matches the PRD ---
assert len(library.LEAKS) == 12
assert [l for l in library.LEAKS.values() if l["weight"] == "heavy"] and all(
    l["weight"] in library.WEIGHT_ORDER and l["pillar"] in library.PILLARS and l["non_dollar"] in library.NON_DOLLAR_LINES
    for l in library.LEAKS.values())
assert {k: sum(1 for l in library.LEAKS.values() if l["pillar"] == k) for k in library.PILLARS} == \
    {"credibility": 3, "pipeline": 3, "conversion": 2, "delivery": 4}
assert set(library.BAND_TABLE) == set(library.Q4) - {"rather_not_say"}
for band, cells in library.BAND_TABLE.items():  # every cell is a valid range and light < medium < heavy
    assert cells["light"][0] < cells["medium"][0] < cells["heavy"][0], band
    assert all(lo < hi and lo % 100 == 0 and hi % 100 == 0 for lo, hi in cells.values()), band
assert set(library.CASE_STUDIES) == set(library.PILLARS)
assert (len(library.Q1), len(library.Q2), len(library.Q3), len(library.Q5)) == (5, 7, 7, 5)
assert [s["key"] for s in library.SCREENS] == ["q1", "url", "q2", "q3", "q4", "q5"]  # PRD §4 order
# The frontend's copy of the questions and CTA text must match library.py (regenerate with: python library.py)
assert json.loads(library.FRONTEND_CONTENT.read_text(encoding="utf-8")) == library.frontend_content(), \
    "frontend/lib/content.json is out of date: run `python library.py`"

# --- Revenue band (PRD §4) ---
assert rules.band_for("200k_350k") == ("200k_350k", False)
assert rules.band_for("rather_not_say") == ("100k_200k", True)

# --- Sizing by evidence (PRD §6.3: more signals = higher in the cell) ---
assert rules.round100(250) == 300 and rules.round100(249) == 200 and rules.round100(6040) == 6000
heavy = library.BAND_TABLE["200k_350k"]["heavy"]  # (5900, 10200): range width 40% = $1,700
assert rules.size_range(1, heavy) == (5900, 7600)             # 1 point: bottom of the cell
assert rules.size_range(2, heavy) == (7200, 8900)             # 2 points: middle
assert rules.size_range(3, heavy) == rules.size_range(5, heavy) == (8500, 10200)  # 3+: top
assert rules.size_range(0.5, heavy) == rules.size_range(1, heavy)
for cells in library.BAND_TABLE.values():                     # every cell, every strength: inside, $100s, readable
    for cell in cells.values():
        for strength in (0, 0.5, 1, 1.5, 2, 2.5, 3, 4.5):
            low, high = rules.size_range(strength, cell)
            assert cell[0] <= low < high <= cell[1] and low % 100 == high % 100 == 0, (cell, strength)
            assert high - low >= min(500, cell[1] - cell[0]), (cell, strength)

# --- Signals (PRD §4, §5) ---
bmv = {"q1": "A", "q2": ["referrals", "personal_network", "partnerships"],
       "q3": ["chasing_new_business", "writing_proposals"], "q4": "100k_200k", "q5": "referral_presold"}
fired = rules.signals(bmv, "full", site(True, True, True))
strength = {leak_id: sum(p for p, _, _ in found) for leak_id, found in fired.items()}
assert strength["L4"] == 2 + 1 + 1.5 + 0.5          # relationships only (strong) + referral + chasing tick + Q1
assert strength["L5"] == 1 + 1.5 + 0.5              # no outbound + chasing tick + Q1
assert strength["L2"] == 1 - 1 + 0.5                # referral, minus proof found on the site, + Q1
assert "We found case studies and testimonials on your site" in [r for _, r, _ in fired["L2"]]
assert strength["L9"] == 0 and fired["L9"] == []
assert fired["L4"][0][1] == "Your leads come only through referrals, your network or partners"
assert "Your week goes to unblocking the team on decisions only you can make" in \
    [r for _, r, _ in rules.signals({**bmv, "q3": ["unblocking_team"]}, "full", None)["L9"]]  # "I" -> "you"

# --- Picking the three gaps ---
assert picks(bmv, read=site(True, True, True)) == ["L4", "L5", "L8"]    # live QA: proof on the site keeps L2 out
assert picks(bmv, read=site()) == ["L4", "L5", "L2"]                    # no proof found -> No Proof Layer
diag = rules.pick_gaps(bmv, "full", site(True, True, True), "100k_200k")
assert diag == rules.pick_gaps(bmv, "full", site(True, True, True), "100k_200k")  # same answers, same report
assert [(g["monthly_low"], g["monthly_high"]) for g in diag["leaks"]] == [(5000, 6000), (5000, 6000), (2800, 3500)]
assert diag["scores"] == {"credibility": 8, "pipeline": 3, "conversion": 4, "delivery": 9}
many_channels = {"q1": "A", "q2": ["inbound_website", "linkedin_content", "outbound", "paid_ads", "referrals"],
                 "q3": ["chasing_new_business", "following_up_leads"], "q4": "350k_500k", "q5": "no_proof"}
assert "L5" not in picks(many_channels, read=site())   # sim bug: ticked outbound yet got "No Systematic Outbound"
assert "L4" not in picks(many_channels, read=site())   # 5 channels isn't referral concentration
boardwalk = {"q1": "C", "q2": ["inbound_website", "referrals", "paid_ads", "partnerships"],
             "q3": ["unblocking_team", "chasing_status", "onboarding_by_hand", "fixing_inconsistent_work"],
             "q4": "200k_350k", "q5": "no_proof"}
assert picks(boardwalk, read=site(case_studies=True, blog=True), band="200k_350k") == ["L9", "L2", "L12"]
# Only two gaps have defining evidence: they come first, and slot three falls back to the best-supported of the
# rest (Manual Onboarding, via Q1 = B). Q1 alone never beats a gap with real evidence.
thin = {"q1": "B", "q2": ["outbound", "inbound_website", "linkedin_content"], "q3": ["writing_proposals"],
        "q4": "50k_100k", "q5": "dated_site"}
assert picks(thin, read=site(True, True, True), band="50k_100k") == ["L8", "L1", "L10"]
none = rules.pick_gaps({**bmv, "q5": "dont_know"}, "none", None, "100k_200k")
assert none["scores"]["credibility"] <= 2 and "L3" in [g["leak_id"] for g in none["leaks"]]  # PRD §4: no website

# Every possible founder: the PRD's rules hold (3 different gaps, never one pillar, inside the cells, dollar order,
# scores in range and never all four low).
rng = random.Random(7)
for _ in range(3000):
    answers = {"q1": rng.choice(list(library.Q1)), "q4": rng.choice(list(library.BAND_TABLE)),
               "q2": rng.sample(list(library.Q2), rng.randint(1, 7)), "q3": rng.sample(list(library.Q3), rng.randint(1, 7)),
               "q5": rng.choice(list(library.Q5))}
    url_type = rng.choice(["full", "full", "social", "none"])
    read = site(*(rng.random() < 0.5 for _ in range(3))) if url_type == "full" and rng.random() < 0.8 else None
    diag = rules.pick_gaps(answers, url_type, read, answers["q4"])
    gaps = diag["leaks"]
    assert len({g["leak_id"] for g in gaps}) == 3 and len({g["pillar"] for g in gaps}) > 1, answers
    for g in gaps:
        cell = library.BAND_TABLE[answers["q4"]][g["weight"]]
        assert cell[0] <= g["monthly_low"] < g["monthly_high"] <= cell[1], (answers, g)
    mids = [g["monthly_low"] + g["monthly_high"] for g in gaps]
    assert mids == sorted(mids, reverse=True), answers
    scores = diag["scores"]
    assert all(1 <= s <= 10 for s in scores.values()), answers
    assert url_type == "none" or not all(s <= 5 for s in scores.values()), answers  # no website: Credibility 1–2 wins
    assert all(scores[g["pillar"]] <= 5 for g in gaps), answers  # PRD §8.1

# --- Hard problems in Claude's answer that trigger a retry ---
assert rules.problems(fake_out("L4", "L5", "L2"), ["L4", "L5", "L2"]) == []
assert rules.problems(fake_out("L2", "L4", "L5"), ["L4", "L5", "L2"]) == []  # order doesn't matter
assert "L4, L5, L2" in rules.problems(fake_out("L4", "L5"), ["L4", "L5", "L2"])[0]
assert "L4, L5, L2" in rules.problems(fake_out("L4", "L5", "L6"), ["L4", "L5", "L2"])[0]  # a swapped gap
cut_off = fake_out("L4", "L5", "L2")
cut_off["the_read"] = "Your homepage still presents a generic"                  # live QA: string closed early
cut_off["leaks"][1]["proof_tie_in"] = 'Like Hot Inbox, you\'d "stop chasing."'  # closing quote after the stop is fine
assert rules.problems(cut_off, ["L4", "L5", "L2"]) == \
    ["these fields stop mid-sentence, write them in full (quote with single quotes): the_read"]

# --- Example A from PRD_EXPLAINED.md: Pipeline top leak -> Client Engine, Hot Inbox ---
report = finalize(("L4", 8000, 10200), ("L5", 7500, 10000), ("L2", 6500, 9000),
                  out=fake_out("L2", "L4", "L5"))                              # Claude's order is ignored
assert [l["leak_id"] for l in report["leaks"]] == ["L4", "L5", "L2"] and [l["rank"] for l in report["leaks"]] == [1, 2, 3]
assert (report["total_low"], report["total_high"]) == (22000, 29200)
assert report["top_leak_pillar"] == "pipeline" and report["cta_route"] == "client_engine"
assert report["proof"]["key"] == "hot_inbox" and report["proof"]["tie_in"] == "Tie-in for L4."
assert report["cta_bridge"].startswith("All three of your gaps — Referral Concentration, No Systematic Outbound")
assert report["company_name"] == "Acme" and report["gap_count"] == 3
assert report["leaks"][0]["name"] == "Referral Concentration" and report["leaks"][0]["fix_name"]
assert report["leaks"][0]["signals"] == ["s L4"]                               # evidence reaches the report
assert report["cant_see"][-1] == "Generated item" and len(report["cant_see"]) == 3
assert "$200K–$350K" in report["how_calculated"][0] and "heavy, heavy and heavy" in report["how_calculated"][0]
assert report["scores"]["credibility"] == {"score": 8, "rationale": "Why"}      # number from code, words from Claude

# --- Example B: Delivery top leak -> booking, Archaius, fixed booking copy ---
report = finalize(("L9", 4500, 6000), ("L2", 4000, 5800), ("L5", 3500, 4800), band="100k_200k")
assert report["top_leak_pillar"] == "delivery" and report["cta_route"] == "booking"
assert report["proof"]["key"] == "archaius" and report["cta_bridge"] == library.CTA_BOOKING
assert (report["total_low"], report["total_high"]) == (12000, 16600)

# --- Bridge sentence variants (PRD gap #3) ---
two = finalize(("L4", 8000, 10200), ("L9", 7000, 9000), ("L2", 6500, 9000))
assert two["cta_bridge"] == ("Two of your three gaps — Referral Concentration and No Proof Layer — "
                             "are exactly what the Client Engine is built to fix.")
one = finalize(("L7", 8000, 10200), ("L9", 7000, 9000), ("L12", 4000, 6000))
assert one["cta_bridge"] == "Your biggest gap — Leads Fall Through the Cracks — is exactly what the Client Engine is built to fix."

# --- Midpoint ordering with a weight tie-break (PRD gap #1) ---
ordered = rules.order_leaks([{"monthly_low": 4000, "monthly_high": 6000, "weight": "medium", "id": "m"},
                             {"monthly_low": 4000, "monthly_high": 6000, "weight": "heavy", "id": "h"},
                             {"monthly_low": 3000, "monthly_high": 8000, "weight": "light", "id": "l"}])
assert [l["id"] for l in ordered] == ["l", "h", "m"]

# --- Verdict banner fallbacks (PRD §7.1) ---
specs = (("L4", 8000, 10200), ("L5", 7500, 10000), ("L2", 6500, 9000))
assert report["display_name"] == "Acme"
assert finalize(*specs)["verdict_subline"] == "Three structural gaps in how your growth agency wins and delivers work."
nameless = fake_out("L4", "L5", "L2")
nameless["company_name"], nameless["business_descriptor"] = "", " "
assert finalize(*specs, out=nameless)["display_name"] == "acme.com"             # no name found -> domain
none = finalize(*specs, out=nameless, band="100k_200k", inferred=True, website_url=None, domain=None, url_type="none")
assert none["display_name"] == "Your business" and none["verdict_subline"].endswith("your firm wins and delivers work.")
assert none["mrr_inferred"] is True and none["band_label"] == "$100K–$200K"
guessed = fake_out("L4", "L5", "L2")
guessed["company_name"], guessed["business_descriptor"] = "Growth Machine", "growth marketing agency"
unread = finalize(*specs, out=guessed, website_url="https://growthmachine.com", domain="growthmachine.com", degraded=True)
assert unread["display_name"] == "Growth Machine"                               # a name from the domain is fine
assert unread["verdict_subline"] == "Three structural gaps in how your firm wins and delivers work."  # no guessed industry

# --- Capitalising Claude's text ---
assert rules.sentence("  whether the team has capacity. ") == "Whether the team has capacity."
assert rules.sentence("") == ""
lower = fake_out("L4", "L5", "L2")
lower["cant_see_item"], lower["leaks"][0]["fix_what_it_does"] = "whether x", "a system that y"
lower["leaks"][0]["non_dollar_cost"] = "an estimated 2–4 conversations"
capped = finalize(*specs, out=lower)
assert capped["cant_see"][-1] == "Whether x" and capped["leaks"][0]["fix_what_it_does"] == "A system that y"
assert capped["leaks"][0]["non_dollar_cost"] == "an estimated 2–4 conversations"  # follows "Also costing you:"

# --- Cost ---
usage = SimpleNamespace(input_tokens=1000, output_tokens=2000, cache_creation_input_tokens=0,
                        cache_read_input_tokens=5000)
assert abs(rules.cost_usd(usage) - (0.002 + 0.02 + 0.001)) < 1e-9

print("test_rules.py: all checks passed")
