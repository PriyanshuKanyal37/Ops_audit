"""Gate 2 (PLAN §9): run the 15 fake founders in fixtures/inputs.json through the real pipeline
(website read -> Claude -> rules) and write each report as Markdown for Shiv to read.
Nothing is saved to the audits table. Re-run after every prompt change: it's the regression test.

Usage:  python run_fixtures.py            all 15
        python run_fixtures.py 1 7 12     only those fixture numbers
Output: fixtures/out/01-name.md … and fixtures/out/SUMMARY.md
"""

import asyncio
import json
import logging
import pathlib
import re
import sys
import time

import db
import generate
import library
import scrape

HERE = pathlib.Path(__file__).parent
OUT = HERE / "fixtures" / "out"
BANNED = [r"\bit seems\b", r"\bconsider\b", r"!", r"\bladder\b", r"client engine", r"\$3,?500", r"\bQ[1-5]\b",
          r"\d+\s?% (?:certain|confident|accurate)"]


def claude_text(report: dict) -> str:
    """Everything Claude wrote (not our fixed copy), for the tone checks."""
    parts = [report["the_read"], report["proof"]["tie_in"], report["cant_see"][-1], report["verdict_subline"]]
    parts += [s["rationale"] for s in report["scores"].values()]
    for leak in report["leaks"]:
        parts += [leak["description"], leak["non_dollar_cost"], leak["fix_what_it_does"], leak["fix_what_changes"],
                  leak["fix_time_to_live"], leak["proof_tie_in"]]
    return "\n".join(parts)


def checks(report: dict) -> list[str]:
    """Automatic checks from the PRD; Shiv still reads every report."""
    found = []
    low, high = (50, 70) if report["specificity_degraded"] or report["url_type"] == "none" else (70, 90)
    for leak in report["leaks"]:
        words = len(leak["description"].split())
        if not low - 10 <= words <= high + 10:
            found.append(f"{leak['leak_id']} description is {words} words (target {low}–{high})")
    text = claude_text(report)
    if len(re.findall(r"revenue leak", text, re.IGNORECASE)) > 1:
        found.append('"revenue leak" used more than once')
    found += [f"banned phrase: {p}" for p in BANNED if re.search(p, text, re.IGNORECASE)]
    if all(s["score"] <= 5 for s in report["scores"].values()):
        found.append("all four scores are low")
    return found


def to_markdown(n: int, fixture: dict, report: dict, stats: dict) -> str:
    a = fixture["answers"]
    lines = [
        f"# {n:02d} · {fixture['name']}",
        f"> **Input:** {fixture['url'] or 'no website'} · Q1 {a['q1']} ({library.Q1[a['q1']]}) · "
        f"Q2 {', '.join(library.Q2[k] for k in a['q2'])} · Q3 {', '.join(library.Q3[k] for k in a['q3'])} · "
        f"Q4 {library.Q4[a['q4']]} · Q5 {library.Q5[a['q5']]}",
        f"> **Run:** {stats['seconds']}s · {stats['attempts']} attempt(s) · ${stats['cost_usd']:.4f} · "
        f"cache read {stats['cache_read_tokens']} tokens · website {'UNAVAILABLE' if report['specificity_degraded'] else 'read' if report['url_type'] != 'none' else 'none given'}",
        "",
        "## 7.1 Verdict",
        f"**{report['display_name']} is losing an estimated ${report['total_low']:,}–{report['total_high']:,} a month.**",
        report["verdict_subline"],
        "", "## 7.2 The read", report["the_read"],
        "", "## 7.3 Scorecard", "| Pillar | Score | Why |", "|---|---|---|",
        *[f"| {p.title()} | {s['score']}/10 | {s['rationale']} |" for p, s in report["scores"].items()],
        "", "## 7.4 Top three leaks",
    ]
    for leak in report["leaks"]:
        lines += [f"### #{leak['rank']} {leak['name']} · {leak['pillar']} · {leak['weight']} · "
                  f"${leak['monthly_low']:,}–{leak['monthly_high']:,}/month",
                  leak["description"], f"*Also costing you: {leak['non_dollar_cost']}*", ""]
    lines.append("## 7.5 What we'd build")
    for leak in report["leaks"]:
        lines += [f"### {leak['fix_name']}", f"- **What it does:** {leak['fix_what_it_does']}",
                  f"- **What changes:** {leak['fix_what_changes']}", f"- **Time to live:** {leak['fix_time_to_live']}", ""]
    proof = report["proof"]
    lines += [f"## 7.6 Proof: {proof['name']}", *[f"- {h}" for h in proof["headline"]], "", proof["tie_in"],
              "", "## 7.7 How we calculated this", *report["how_calculated"],
              "", "## 7.8 What this report can't see", *[f"- {item}" for item in report["cant_see"]],
              "", f"## 7.9 CTA → `{report['cta_route']}`", report["cta_bridge"],
              "", "## Automatic checks", *([f"- ⚠️ {c}" for c in checks(report)] or ["- ✅ none failed"])]
    return "\n".join(lines)


async def run_one(n: int, fixture: dict, gate: asyncio.Semaphore) -> dict:
    url, key, url_type = scrape.normalize(fixture["url"]) if fixture["url"] else (None, None, "none")
    async with gate:
        try:
            report, stats = await generate.build_report(url, key, url_type, fixture["answers"])
        except generate.GenerationError as error:
            return {"n": n, "name": fixture["name"], "error": str(error)}
    path = OUT / f"{n:02d}-{fixture['name']}.md"
    path.write_text(to_markdown(n, fixture, report, stats), encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"n": n, "name": fixture["name"], "report": report, "stats": stats, "checks": checks(report)}


async def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    fixtures = json.loads((HERE / "fixtures" / "inputs.json").read_text(encoding="utf-8"))
    wanted = {int(arg) for arg in sys.argv[1:]} or set(range(1, len(fixtures) + 1))
    chosen = [(n, f) for n, f in enumerate(fixtures, start=1) if n in wanted]
    OUT.mkdir(parents=True, exist_ok=True)
    await db.init()
    # Like the real flow, where the read starts at the URL screen minutes before the audit runs.
    for _, fixture in chosen:
        if fixture["url"]:
            await scrape.start(*scrape.normalize(fixture["url"]))
    await asyncio.gather(*list(scrape._in_flight.values()), return_exceptions=True)

    started = time.monotonic()
    gate = asyncio.Semaphore(3)  # 3 Claude calls at a time
    rows = await asyncio.gather(*(run_one(n, f, gate) for n, f in chosen))
    await db.close()

    ok = [r for r in rows if "report" in r]
    lines = [f"# Fixture run ({time.strftime('%Y-%m-%d %H:%M')}) · {len(ok)}/{len(rows)} reports · "
             f"total ${sum(r['stats']['cost_usd'] for r in ok):.3f} · {time.monotonic() - started:.0f}s wall",
             "", "| # | Fixture | Leaks (rank order) | Total/month | Route | Proof | Website | $ | s | Checks |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['n']} | {r['name']} | ❌ {r['error']} | | | | | | | |")
            continue
        rep, st = r["report"], r["stats"]
        website = "none" if rep["url_type"] == "none" else "UNAVAILABLE" if rep["specificity_degraded"] else "read"
        lines.append(
            f"| {r['n']} | {r['name']} | {', '.join(l['leak_id'] + ' ' + l['name'] for l in rep['leaks'])} | "
            f"${rep['total_low']:,}–{rep['total_high']:,} | {rep['cta_route']} | {rep['proof']['name']} | {website} | "
            f"{st['cost_usd']:.3f} | {st['seconds']} | {'✅' if not r['checks'] else '⚠️ ' + '; '.join(r['checks'])} |")
    (OUT / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
