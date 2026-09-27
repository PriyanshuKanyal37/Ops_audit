"""Single source of truth for the audit's content: questions, the 12-leak library, the dollar table,
case studies and fixed report copy. Everything here comes from the PRD (ladder_ops_audit_prd.md);
lines marked `PRD gap:` are defaults from audit-app/PLAN.md §11 that still need Shiv's OK.

The frontend reads the questions and fixed CTA copy from frontend/lib/content.json. Regenerate it after
editing them here:  python library.py   (test_rules.py fails if the two drift apart)
"""

import json
import pathlib

PILLARS = ("credibility", "pipeline", "conversion", "delivery")
CLIENT_ENGINE_PILLARS = ("credibility", "pipeline", "conversion")  # PRD §5 pillar map
WEIGHT_ORDER = {"heavy": 3, "medium": 2, "light": 1}

# --- Questions (PRD §4). Keys are stored in the database; labels are the exact on-screen text. ---

Q1 = {
    "A": "Getting consistent leads and bookings",
    "B": "Onboarding clients without chaos",
    "C": "Delivering work on time without me jumping in",
    "D": "Keeping clients long enough to grow accounts",
    "E": "Understanding what's actually happening across the business",
}
Q2 = {
    "referrals": "Referrals and word of mouth",
    "personal_network": "My personal network",
    "inbound_website": "Inbound through our website",
    "linkedin_content": "LinkedIn or content",
    "outbound": "Cold email or outbound",
    "paid_ads": "Paid ads",
    "partnerships": "Partnerships or other agencies",
}
Q3 = {
    "chasing_new_business": "Chasing new business personally",
    "writing_proposals": "Writing proposals one at a time",
    "following_up_leads": "Following up on leads manually",
    "unblocking_team": "Unblocking the team on decisions only I can make",
    "chasing_status": "Chasing status updates on active projects",
    "onboarding_by_hand": "Onboarding new clients by hand",
    "fixing_inconsistent_work": "Fixing work that came back inconsistent",
}
Q4 = {
    "under_50k": "Under $50K",
    "50k_100k": "$50K–$100K",
    "100k_200k": "$100K–$200K",
    "200k_350k": "$200K–$350K",
    "350k_500k": "$350K–$500K",
    "500k_plus": "$500K+",
    "rather_not_say": "I'd rather not say",
}
RATHER_NOT_SAY_BAND = "100k_200k"  # PRD §4: under-promising to a larger firm is safer
Q5 = {
    "dated_site": "A website that's a couple of years behind where we are now",
    "no_proof": "A decent website, but no case studies or proof",
    "stale_linkedin": "A LinkedIn profile I haven't touched in a while",
    "referral_presold": "Most arrive pre-sold through a referral, so I'm not sure it matters",
    "dont_know": "Honestly, I don't know",
}

# The question screens, in order (PRD §4). "url" is the unnumbered website screen between Q1 and Q2.
SCREENS = [
    {"key": "q1", "title": "Where does your business break down most often?", "sub": "", "multi": False, "options": Q1},
    {"key": "url", "title": "One quick thing before we continue.",
     "sub": "What's your website? We'll read your public positioning while you answer the rest."},
    {"key": "q2", "title": "If you stopped chasing new business personally for the next 30 days, "
                           "where would leads still come from?", "sub": "Select all that apply.", "multi": True,
     "options": Q2},
    {"key": "q3", "title": "Where does your week actually go?", "sub": "Select all that apply.", "multi": True,
     "options": Q3},
    {"key": "q4", "title": "What's your average monthly revenue?",
     "sub": "We use this to size the dollar impact of each leak.", "multi": False, "options": Q4},
    {"key": "q5", "title": "What does a prospect see before they ever talk to you?", "sub": "", "multi": False,
     "options": Q5},
]

# --- The dollar model (PRD §6.1): base monthly range per leak, by revenue band and weight. ---

BAND_TABLE = {
    "under_50k": {"light": (400, 800), "medium": (700, 1300), "heavy": (1100, 2000)},
    "50k_100k": {"light": (700, 1300), "medium": (1200, 2200), "heavy": (1900, 3300)},
    "100k_200k": {"light": (1300, 2400), "medium": (2200, 4000), "heavy": (3500, 6000)},
    "200k_350k": {"light": (2200, 4000), "medium": (3700, 6800), "heavy": (5900, 10200)},
    "350k_500k": {"light": (3400, 6000), "medium": (5700, 10200), "heavy": (9000, 15300)},
    "500k_plus": {"light": (4800, 8500), "medium": (8000, 14500), "heavy": (12800, 21500)},
}

# --- Non-dollar cost lines (PRD §6.4). ---

NON_DOLLAR_LINES = {
    "time": "roughly 14–20 hours a month of your time",
    "pipeline": "an estimated 2–4 qualified conversations a month you never have",
    "conversion": "deals sitting an average of 3–5 days longer than they need to",
    "credibility": "you're absent from shortlists you'd win if you were on them",
}

# --- The revenue leak library (PRD §5). `text` is pasted verbatim into Claude's system prompt. ---

LEAKS = {
    "L1": {
        "name": "Brand Perception Gap", "pillar": "credibility", "weight": "medium",
        "fix_name": "Positioning and messaging rebuild", "non_dollar": "credibility",
        "text": (
            "The business has outgrown how it presents itself. Positioning, site, and proof describe the firm "
            "they were two years ago, so cold prospects price them against smaller competitors and the founder "
            "re-establishes credibility from scratch in every first call.\n"
            'Triggers: Q5 = "a couple of years behind"; scrape shows generic or dated positioning, no vertical '
            "focus, a service-list homepage; Q1 = A.\n"
            "Weight: Medium · Fix: Positioning and messaging rebuild — a single clear market stance carried "
            "consistently across site, proof, and outbound."
        ),
    },
    "L2": {
        "name": "No Proof Layer", "pillar": "credibility", "weight": "heavy",
        "fix_name": "Case study system", "non_dollar": "credibility",
        "text": (
            "No case studies, named outcomes, or client evidence a prospect can find. Buying groups now shortlist "
            "roughly 2.5 vendors and complete most of their evaluation before making contact, so a firm without "
            "visible proof is filtered out before a conversation is possible.\n"
            'Triggers: Q5 = "no case studies or proof"; scrape finds no case studies, testimonials, or named '
            'clients; Q1 = A or D; Q5 = "most arrive pre-sold through a referral".\n'  # PRD gap #6: last trigger added
            "Weight: Heavy · Fix: Case study system — three to five client stories with specific, measurable "
            "outcomes, structured so new ones can be produced without a rebuild."
        ),
    },
    "L3": {
        "name": "Invisible to the Right Buyers", "pillar": "credibility", "weight": "medium",
        "fix_name": "Discoverability layer", "non_dollar": "credibility",
        "text": (
            "The firm does not appear where its buyers actually research. Buyers complete 70–80% of evaluation "
            "before contacting sales, and AI answer engines have become a primary research surface, so a firm "
            "with no discoverable footprint is absent from the shortlist by default.\n"
            'Triggers: Q2 has no "inbound through our website"; Q5 = "LinkedIn I haven\'t touched" or "I don\'t '
            'know"; url_type = none or social; scrape returns thin content or no service pages.\n'
            "Weight: Medium · Fix: Discoverability layer — service and outcome pages structured to be found and "
            "cited by both search and AI answer engines."
        ),
    },
    "L4": {
        "name": "Referral Concentration", "pillar": "pipeline", "weight": "heavy",
        "fix_name": "A second acquisition channel", "non_dollar": "pipeline",
        "text": (
            "New business depends on the founder's personal network and existing relationships. This is not a "
            "marketing gap, it is a structural risk: revenue is correlated to the founder's calendar, and growth "
            "stops at the edge of their network.\n"
            'Triggers: Q2 = 1–2 ticks including referrals or personal network; Q5 = "most arrive pre-sold through '
            'a referral"; Q3 includes "chasing new business personally"; Q1 = A.\n'
            "Weight: Heavy · Fix: A second acquisition channel that runs without the founder — sourcing, "
            "sequencing, and booking handled by a system rather than by relationships."
        ),
    },
    "L5": {
        "name": "No Systematic Outbound", "pillar": "pipeline", "weight": "heavy",
        "fix_name": "Always-on outbound system", "non_dollar": "pipeline",
        "text": (
            "Outreach happens in bursts when the pipeline gets thin, then stops when delivery gets busy. Revenue "
            "tracks the founder's available attention rather than market demand, which produces the "
            "feast-or-famine cycle.\n"
            'Triggers: Q2 has no "cold email or outbound"; Q3 includes "chasing new business personally"; '
            "Q1 = A.\n"
            "Weight: Heavy · Fix: Always-on outbound system — ideal-fit prospect sourcing, personalised "
            "sequences, and reply handling that continues regardless of delivery load."
        ),
    },
    "L6": {
        "name": "No Content Engine", "pillar": "pipeline", "weight": "medium",
        "fix_name": "Content system", "non_dollar": "pipeline",  # PRD gap #5: PRD gives L6 no line
        "text": (
            "No consistent point of view in market. Buyers consume a dozen or more content assets before contact "
            "and use thought leadership to judge whether a firm understands their problem. Sporadic posting "
            "produces no compounding familiarity.\n"
            'Triggers: Q2 has no "LinkedIn or content"; Q5 = "LinkedIn I haven\'t touched"; scrape shows no blog '
            "or insights section, or one with a stale last post.\n"
            "Weight: Medium · Fix: Content system — a repeatable production process producing authority assets on "
            "a fixed cadence without founder writing time."
        ),
    },
    "L7": {
        "name": "Leads Fall Through the Cracks", "pillar": "conversion", "weight": "heavy",
        "fix_name": "Lead response and follow-up system", "non_dollar": "conversion",
        "text": (
            "Interest arrives and decays before anyone acts on it. Median B2B response time sits above 40 hours "
            "against a conversion-optimal window under five minutes, and a large share of inbound leads are never "
            "contacted at all. Every hour of delay is compounding loss on demand already paid for.\n"
            'Triggers: Q3 includes "following up on leads manually"; Q2 has 4+ ticks alongside manual chase in '
            "Q3; Q1 = A.\n"
            "Weight: Heavy · Fix: Lead response and follow-up system — instant acknowledgement, automatic "
            "routing, and multi-touch sequences that continue until a lead replies or closes."
        ),
    },
    "L8": {
        "name": "Proposal Bottleneck", "pillar": "conversion", "weight": "medium",
        "fix_name": "Proposal and quoting system", "non_dollar": "conversion",
        "text": (
            "Proposals are built one at a time from memory. Turnaround stretches into days or weeks, pricing "
            "varies by who builds it, and deals cool while the prospect waits. The firm's best estimating "
            "instincts live in a few people's heads rather than in a system.\n"
            'Triggers: Q3 includes "writing proposals one at a time"; Q1 = A or B; Q3 includes "unblocking the '
            'team on decisions only I can make".\n'
            "Weight: Medium · Fix: Proposal and quoting system — structured templates drawing on past project "
            "data so any team member produces a consistent, defensible proposal in minutes."
        ),
    },
    "L9": {
        "name": "Founder-Gated Decisions", "pillar": "delivery", "weight": "heavy",
        "fix_name": "Decision delegation framework", "non_dollar": "time",
        "text": (
            "Work stops until the founder unblocks it. Approvals, pricing calls, scope questions, and client "
            "escalations all route through one person, which caps throughput at the founder's available hours "
            "regardless of team size.\n"
            'Triggers: Q3 includes "unblocking the team on decisions only I can make"; Q1 = C or E; Q3 has 4+ '
            "ticks.\n"
            "Weight: Heavy · Fix: Decision delegation framework — documented criteria, thresholds, and escalation "
            "paths so the team can act without waiting."
        ),
    },
    "L10": {
        "name": "Manual Client Onboarding", "pillar": "delivery", "weight": "light",
        "fix_name": "Onboarding pipeline", "non_dollar": "time",
        "text": (
            "Every new client is set up by hand — a flurry of emails, folder creation, tool access, kickoff "
            "scheduling. It consumes senior time at the exact moment the client is forming their impression of "
            "the firm.\n"
            'Triggers: Q3 includes "onboarding new clients by hand"; Q1 = B.\n'
            "Weight: Light · Fix: Onboarding pipeline — triggered workflows handling access, setup, "
            "documentation, and kickoff from a single signed-contract event."
        ),
    },
    "L11": {
        "name": "Fragmented Visibility", "pillar": "delivery", "weight": "light",
        "fix_name": "Operating dashboard", "non_dollar": "time",
        "text": (
            "No reliable view of what is happening, at either project or business level. Status requires asking "
            "someone. Capacity, margin, and pipeline live in different places or in nobody's head, so decisions "
            "get made on instinct and turn out to be wrong late.\n"
            'Triggers: Q3 includes "chasing status updates on active projects"; Q1 = E or C.\n'
            "Weight: Light · Fix: Operating dashboard — one view of active work, capacity, and revenue, updated "
            "from the systems the team already uses."
        ),
    },
    "L12": {
        "name": "Inconsistent Client Experience", "pillar": "delivery", "weight": "medium",
        "fix_name": "Delivery standardisation", "non_dollar": "time",  # PRD gap #5: PRD gives L12 no line
        "text": (
            "Quality depends on who is handling the account. The same service delivered by two people produces "
            "two different experiences, which shows up later as churn, discounting, and referrals that never "
            "come.\n"
            'Triggers: Q3 includes "fixing work that came back inconsistent"; Q1 = D or C.\n'
            "Weight: Medium · Fix: Delivery standardisation — documented process, quality checkpoints, and "
            "templates so output is consistent regardless of who executes."
        ),
    },
}

# --- Proof: one case study per top-leak pillar (PRD §7.6). No outbound links (Archaius rule 3). ---

CASE_STUDIES = {
    "credibility": {
        "key": "athereal", "name": "Athereal",
        "headline": ["Vertical repositioning", "Seed conversations within 3 months", "5–6 enterprise clients"],
    },
    "pipeline": {
        "key": "hot_inbox", "name": "Hot Inbox",
        "headline": ["25k validated leads/day at 1/10 the cost", "15 clients in 60 days", "$75–120k ARR"],
    },
    "conversion": {
        "key": "storata", "name": "Storata",
        "headline": ["Proposals 1–2 weeks → 2–3 hours", "15 founder hrs/week reclaimed", "5–6 retainer clients"],
    },
    "delivery": {
        "key": "archaius", "name": "Archaius Creative",
        "headline": ["One source of truth", "±10% estimate accuracy", "300+ projects made queryable"],
    },
}

# How each case study is framed for Claude when it writes the one-line tie-in (PRD §7.6).
CASE_STUDY_BRIEFS = {
    "credibility": "Athereal: vertical repositioning; seed conversations within 3 months; 5–6 enterprise clients.",
    "pipeline": "Hot Inbox: 25k validated leads/day at 1/10 the cost; 15 clients in 60 days; $75–120k ARR.",
    "conversion": "Storata: proposals went from 1–2 weeks to 2–3 hours; 15 founder hours a week reclaimed; "
                  "5–6 retainer clients.",
    "delivery": "Archaius Creative: frame it as CONSISTENCY, not speed. Estimates used to depend on who you asked "
                "and the studio's best instincts lived in a few people's heads; now any team member runs the same "
                "query and gets the same defensible answer, with a trail back to comparable past work. One source "
                "of truth; ±10% estimate accuracy; 300+ projects made queryable.",
}

# --- Fixed report copy ---

# PRD §7.1 verdict banner: "{name} is losing an estimated $X–Y a month." + this subline.
VERDICT_SUBLINE = "Three structural gaps in how your {descriptor} wins and delivers work."

CTA_BOOKING = (
    "Your biggest gap is in how work gets delivered, not how it gets sold. "
    "That needs a conversation before anyone proposes a fix."
)
CTA_BOOKING_BUTTON = "Book 30 minutes →"
CTA_CLIENT_ENGINE_BUTTON = "Here's how it works. →"
CTA_SECONDARY = "Already know what you need? Book a call →"

# PRD §7.8: two static items; Claude writes the third from the founder's answers.
CANT_SEE_STATIC = [
    "How your team is structured, and who actually owns which decisions.",
    "Your real close rate, from first conversation to signed contract.",
]

# PRD §7.7 (static copy; only the band and weight classes are filled in).
# PRD gap #4: the PRD says "drawn from Ladder's delivery experience", but the ranges come from published
# benchmarks (PRD §3, §12.4), so this wording says benchmarks. Needs Shiv's approval.
HOW_CALCULATED = [
    "Every figure starts from your revenue band: {band_label} a month. Each gap is classed light, medium or heavy "
    "by how much of a firm's monthly revenue that kind of gap typically costs, roughly 0.8–1.5% for light, "
    "1.5–2.5% for medium and 2.5–4% for heavy. Your three gaps were classed {weights}. Where each range sits "
    "within its class depends on how much evidence your answers and your website gave us: one signal puts it at "
    "the bottom, three or more at the top.",
    "The ranges come from published benchmarks for founder-led service firms your size and are deliberately "
    "conservative. We show ranges, not single numbers, because the exact figure depends on things five "
    "questions can't see.",
]

FRONTEND_CONTENT = pathlib.Path(__file__).parent.parent / "frontend" / "lib" / "content.json"


def frontend_content() -> dict:
    """The question screens and fixed copy the frontend renders, as plain JSON."""
    screens = [
        {**screen, "options": [{"value": k, "label": v} for k, v in screen["options"].items()]}
        if "options" in screen else screen
        for screen in SCREENS
    ]
    return {
        "screens": screens,
        "rather_not_say_band": Q4[RATHER_NOT_SAY_BAND],
        "copy": {"cta_client_engine_button": CTA_CLIENT_ENGINE_BUTTON, "cta_booking_button": CTA_BOOKING_BUTTON,
                 "cta_secondary": CTA_SECONDARY},
    }


if __name__ == "__main__":
    FRONTEND_CONTENT.parent.mkdir(exist_ok=True)
    FRONTEND_CONTENT.write_text(json.dumps(frontend_content(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {FRONTEND_CONTENT}")
