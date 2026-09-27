"""The PRD §12 numbers: every funnel step against its target, and the watch items.

Usage:  python funnel_report.py        last 30 days
        python funnel_report.py 7      last 7 days
"""

import asyncio
import sys

import db


def rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def rows(c: dict) -> list[tuple[str, float | None, str, float | None]]:
    """(step, actual rate, target as text, the minimum that counts as on target)."""
    return [
        ("Landing → started Q1", rate(c["q1_answered"], c["landing_view"]), "45%", 0.45),
        ("Started → gave website", rate(c["url_given"], c["q1_answered"]), "85%", 0.85),
        ("Gave website → reached Q4", rate(c["q4_reached"], c["url_given"]), "80%", 0.80),
        ("Q4 → Q5 (answered revenue)", rate(c["q4_answered"], c["q4_reached"]), "90%", 0.90),
        ("Completed report (of starts)", rate(c["audits"], c["q1_answered"]), "70%", 0.70),
        ("Report → button click", rate(c["clicked"], c["audits"]), "30%", 0.30),
        ("Audit → booked call (on /audit/book)", rate(c["booked"], c["audits"]), "8–10%", 0.08),
    ]


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def report(c: dict, days: int) -> str:
    lines = [f"# Ops Clarity Audit funnel, last {days} days", "",
             f"Visitors per step: landing {c['landing_view']} · Q1 {c['q1_answered']} · website {c['url_given']} · "
             f"Q2 {c['q2_answered']} · Q3 {c['q3_answered']} · reached Q4 {c['q4_reached']} · answered Q4 "
             f"{c['q4_answered']} · Q5 {c['q5_answered']} · pressed submit {c['submitted']} · reports {c['audits']} · "
             f"clicked {c['clicked']} · Client Engine page {c['ce_visits']} · booked {c['booked']}", "",
             "| Step | Actual | PRD target | |", "|---|---|---|---|"]
    for step, actual, target, floor in rows(c):
        status = "" if actual is None else "✅" if actual >= floor else "⚠️ below target"
        lines.append(f"| {step} | {pct(actual)} | {target} | {status} |")
    q4 = rate(c["q4_answered"], c["q4_reached"])
    degraded = rate(c["degraded"], c["audits"])
    delivery = rate(c["delivery_top"], c["audits"])
    lines += [
        "", "Watch items (PRD §12.2–12.4):",
        f"- Q4 drop-off: {pct(q4)} answer revenue. "
        + ("⚠️ Under 85%: move the revenue question to position 5." if q4 is not None and q4 < 0.85 else "OK (85%+)."),
        f"- Website unreadable: {pct(degraded)} of reports. "
        + ("⚠️ Over 10%: the website reader is failing and reports go out generic." if degraded and degraded > 0.10
           else "OK (10% or less)."),
        f"- Delivery as the top gap: {pct(delivery)} of reports. "
        + ("⚠️ Over 35%: time to productise an ops sprint." if delivery and delivery > 0.35 else "OK (35% or less)."),
        f"- Shiv's call feedback: {c['feedback']} answered, {c['feedback_yes']} said the top gap was right. "
        "Recalibrate the scoring at 20 answers.",
        "- Client Engine page → booking (target 50%) can't be measured yet: bookings made on that page don't come "
        "back to us (needs the Calendly webhook, paid plan).",
    ]
    return "\n".join(lines)


async def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    await db.init()
    counts = await db.funnel_counts(days)
    await db.close()
    print(report(counts, days))


if __name__ == "__main__":
    asyncio.run(main())
