"""The audit pipeline: website context -> rules.pick_gaps (the diagnosis) -> Claude writes it up (PRD §8)
-> rules.finalize. One structured-output call, checked by rules.problems, retried once with the problems fed back.
"""

import logging
import time
from typing import Literal

import anthropic
from pydantic import BaseModel

import config
import library
import prompt
import rules
import scrape

log = logging.getLogger(__name__)

LeakId = Literal[tuple(library.LEAKS)]  # type: ignore  # built from library.py; becomes a JSON-schema enum for Claude


# What Claude returns: words only. Every number (ranges, totals, scores) and every lookup (names, route,
# case study) comes from rules.py.
class Rationales(BaseModel):
    credibility: str
    pipeline: str
    conversion: str
    delivery: str


class LeakOut(BaseModel):
    leak_id: LeakId
    description: str
    non_dollar_cost: str
    fix_what_it_does: str
    fix_what_changes: str
    fix_time_to_live: str
    proof_tie_in: str


class AuditOutput(BaseModel):
    company_name: str
    business_descriptor: str
    the_read: str
    score_rationales: Rationales
    leaks: list[LeakOut]
    cant_see_item: str


class GenerationError(Exception):
    """The report could not be produced. The message is for logs, not founders."""


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if not config.ANTHROPIC_API_KEY:
        raise GenerationError("ANTHROPIC_API_KEY is not set in backend/.env")
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def write(site: scrape.Site | None, url: str | None, url_type: str, answers: dict, band: str,
                inferred: bool, diagnosis: dict) -> tuple[dict, dict]:
    """Ask Claude to write the report around the code's diagnosis. Returns (Claude's answer as a dict, call stats)."""
    client = _get_client()  # raises GenerationError straight away if the key is missing
    system = prompt.system_prompt(website_available=site is not None)
    user = prompt.user_message(url, url_type, site.context if site else None, answers, band, inferred, diagnosis)
    expected = [gap["leak_id"] for gap in diagnosis["leaks"]]
    stats = {"cost_usd": 0.0, "attempts": 0, "input_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0,
             "output_tokens": 0}
    feedback, started = "", time.monotonic()
    for _ in range(2):
        stats["attempts"] += 1
        try:
            response = await client.messages.parse(
                model=config.CLAUDE_MODEL,
                max_tokens=8000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user + feedback}],
                output_format=AuditOutput,
                output_config={"effort": config.CLAUDE_EFFORT},
            )
        except anthropic.APIError as error:  # outages and rate limits; the SDK has already retried twice
            raise GenerationError(f"Claude API error: {error}") from error
        except Exception as error:  # output that doesn't fit the schema
            log.warning("Claude output failed to parse: %s", error)
            feedback = "\n\nYour previous answer did not match the required format. Answer again."
            continue
        usage = response.usage
        stats["cost_usd"] += rules.cost_usd(usage)
        stats["input_tokens"] += usage.input_tokens
        stats["cache_write_tokens"] += usage.cache_creation_input_tokens or 0
        stats["cache_read_tokens"] += usage.cache_read_input_tokens or 0
        stats["output_tokens"] += usage.output_tokens
        if response.stop_reason != "end_turn" or response.parsed_output is None:
            log.warning("Claude stopped with %s", response.stop_reason)
            feedback = "\n\nYour previous answer was cut off. Answer again, completely."
            continue
        out = response.parsed_output.model_dump()
        found = rules.problems(out, expected)
        if not found:
            stats["seconds"] = round(time.monotonic() - started, 1)
            return out, stats
        log.warning("Claude answer broke rules: %s", found)
        feedback = "\n\nYour previous answer broke these rules. Fix them: " + "; ".join(found) + "."
    raise GenerationError(f"No usable answer after {stats['attempts']} attempts")


async def build_report(url: str | None, key: str | None, url_type: str, answers: dict) -> tuple[dict, dict]:
    """The whole audit, minus saving: website context -> Claude -> finalized report. Returns (report, stats)."""
    band, inferred = rules.band_for(answers["q4"])
    site = await scrape.get(url, key, url_type)
    diagnosis = rules.pick_gaps(answers, url_type, site, band)
    out, stats = await write(site, url, url_type, answers, band, inferred, diagnosis)
    report = rules.finalize(out, diagnosis, band=band, inferred=inferred, website_url=url, domain=key,
                            url_type=url_type, degraded=site is None and url_type != "none")
    return report, stats
