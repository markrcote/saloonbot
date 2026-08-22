#!/usr/bin/env python3
"""Operator tool: turn tracked LLM token usage into a $ cost report.

Reuses Database/SqliteDatabase's existing get_llm_usage_summary(), which
already aggregates token totals per (purpose, model, provider) over a rolling
window -- no new DB code needed. Applies a small pricing table to that summary
and extrapolates to day/week/month/year run rates, to answer "what would this
cost running 24/7?"

Usage:
    python llm_cost_report.py --days 1
"""
import argparse
import logging
import os

from cardgames.database import Database
from cardgames.sqlite_database import SqliteDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Anthropic per-million-token pricing (USD), keyed by (provider, model).
# Sourced 2026-08-22 -- prices change; re-check https://www.anthropic.com/pricing
# (and the OpenAI equivalent) before trusting this for a real budgeting decision.
PRICING = {
    ('claude', 'claude-haiku-4-5'): (1.00, 5.00),
    ('claude', 'claude-sonnet-5'): (3.00, 15.00),
    ('claude', 'claude-opus-5'): (5.00, 25.00),
    # OpenAI, approximate -- included for completeness, not the focus of this tool.
    ('openai', 'gpt-4o-mini'): (0.15, 0.60),
}


def compute_costs(rows, pricing=PRICING):
    """Given get_llm_usage_summary() rows, return (breakdown, total_cost, unpriced).

    breakdown: one dict per row (a copy of the input row) with a 'cost' key
               added -- a float in dollars, or None if (provider, model) isn't
               in the pricing table.
    total_cost: sum of all priced rows' costs, in dollars.
    unpriced: sorted list of (provider, model) pairs seen but not priced.
    """
    breakdown = []
    total_cost = 0.0
    unpriced = set()
    for row in rows:
        provider = row.get('provider') or 'unknown'
        model = row.get('model')
        rate = pricing.get((provider, model))
        entry = dict(row)
        if rate is None:
            entry['cost'] = None
            unpriced.add((provider, model))
        else:
            in_rate, out_rate = rate
            cost = (row.get('total_input', 0) or 0) / 1_000_000 * in_rate \
                + (row.get('total_output', 0) or 0) / 1_000_000 * out_rate
            entry['cost'] = cost
            total_cost += cost
        breakdown.append(entry)
    return breakdown, total_cost, sorted(unpriced)


def extrapolate(total_cost, days):
    """Project a total cost over `days` to day/week/month/year run rates."""
    if days <= 0:
        return {'day': 0.0, 'week': 0.0, 'month': 0.0, 'year': 0.0}
    daily = total_cost / days
    return {'day': daily, 'week': daily * 7, 'month': daily * 30, 'year': daily * 365}


def _get_db():
    if os.getenv("USE_SQLITE"):
        return SqliteDatabase(os.getenv("SQLITE_PATH", "saloonbot.db"))
    return Database(
        os.getenv("MYSQL_HOST", "localhost"),
        os.getenv("MYSQL_PORT", 3306),
        os.getenv("MYSQL_USER", "saloonbot"),
        os.getenv("MYSQL_PASSWORD", ""),
        os.getenv("MYSQL_DATABASE", "saloonbot"),
    )


def format_report(rows, days):
    """Render the full text report for `rows` (get_llm_usage_summary output) as a string."""
    breakdown, total_cost, unpriced = compute_costs(rows)
    lines = [f"\nLLM usage & cost -- past {days} day{'s' if days != 1 else ''}\n"]
    if not breakdown:
        lines.append("No LLM usage recorded in this window.")
        return "\n".join(lines)

    lines.append(
        f"{'purpose':<20}{'model':<22}{'provider':<10}{'calls':>8}{'in tok':>12}{'out tok':>12}{'cost':>12}"
    )
    for row in breakdown:
        cost_str = f"${row['cost']:.4f}" if row['cost'] is not None else "n/a"
        lines.append(
            f"{row.get('purpose', ''):<20}{row.get('model', ''):<22}{row.get('provider') or 'unknown':<10}"
            f"{row.get('call_count', 0):>8}{row.get('total_input', 0):>12,}{row.get('total_output', 0):>12,}"
            f"{cost_str:>12}"
        )

    if unpriced:
        missing = ", ".join(f"{p}/{m}" for p, m in unpriced)
        lines.append(f"\nNo pricing on file for: {missing} -- tokens shown above, excluded from cost totals.")

    lines.append(f"\nTotal cost this window: ${total_cost:.4f}")

    rates = extrapolate(total_cost, days)
    lines.append("\nExtrapolated run rate (assumes this window's usage rate holds 24/7):")
    lines.append(f"  per day:   ${rates['day']:.4f}")
    lines.append(f"  per week:  ${rates['week']:.2f}")
    lines.append(f"  per month: ${rates['month']:.2f}")
    lines.append(f"  per year:  ${rates['year']:.2f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Report $ cost of LLM usage over the past N days.")
    parser.add_argument("--days", type=int, default=1, help="Rolling window in days, 1-90 (default: 1).")
    args = parser.parse_args()
    days = max(1, min(90, args.days))

    db = _get_db()
    try:
        rows = db.get_llm_usage_summary(days=days)
    finally:
        db.close()

    print(format_report(rows, days))


if __name__ == "__main__":
    main()
