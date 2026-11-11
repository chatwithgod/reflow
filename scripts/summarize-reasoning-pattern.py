"""Read CPA/ECPA usage counters and export aggregate 518*n-2 frequencies only.

The database is opened read-only. Credentials, prompts and response bodies are
not read. Duplicate-check identifiers stay inside SQLite; only counts and model
labels are exported. No network requests or model calls are made.
"""

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import sqlite3


FORMULA = "reasoning_tokens >= 516 AND (reasoning_tokens + 2) % 518 = 0"
TIME = "timestamp_ms >= ? AND latency_ms >= 0 AND timestamp_ms + latency_ms < ?"
CHANNEL = "provider = 'codex' AND model GLOB 'gpt-[0-9]*'"
SUCCESS = "failed = 0 AND canceled = 0"
GENERATION = "generate = 1"
VALID = "typeof(reasoning_tokens) = 'integer' AND reasoning_tokens >= 0"
ELIGIBLE = " AND ".join((TIME, CHANNEL, SUCCESS, GENERATION, VALID))
COUNTERS = f"""COUNT(*) AS successful_generations,
    SUM(reasoning_tokens > 0) AS positive_reasoning_records,
    SUM(reasoning_tokens = 0) AS zero_reasoning_records,
    SUM({FORMULA}) AS pattern_matches,
    SUM(({FORMULA}) AND reasoning_tokens <= 3106) AS default_tier_window_matches,
    SUM(reasoning_tokens = 516) AS exactly_516"""


def parse_time(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("Use an explicit UTC offset, for example +08:00")
    return stamp


def percentage(numerator, denominator):
    if denominator == 0:
        return None
    return str((Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def with_rates(row):
    row = {key: (value or 0) if key != "model" else value for key, value in dict(row).items()}
    row["percent_of_positive_reasoning"] = percentage(row["pattern_matches"], row["positive_reasoning_records"])
    row["percent_of_all_successful_generations"] = percentage(row["pattern_matches"], row["successful_generations"])
    assert row["successful_generations"] == row["positive_reasoning_records"] + row["zero_reasoning_records"]
    assert 0 <= row["exactly_516"] <= row["default_tier_window_matches"] <= row["pattern_matches"] <= row["positive_reasoning_records"]
    return row


def summarize_window(connection, since, until):
    bounds = (int(since.timestamp() * 1000), int(until.timestamp() * 1000))
    where = ""
    funnel = []
    for label, condition in (("in_time_window", TIME), ("codex_gpt_channel", CHANNEL),
                             ("not_failed_or_canceled", SUCCESS), ("generation_not_prewarm", GENERATION),
                             ("nonnegative_integer_reasoning", VALID)):
        where = condition if not where else where + " AND " + condition
        count = connection.execute("SELECT COUNT(*) FROM usage_events WHERE " + where, bounds).fetchone()[0]
        funnel.append({"stage": label, "records": count,
                       "excluded_since_previous_stage": funnel[-1]["records"] - count if funnel else None})
    duplicates = connection.execute(
        "SELECT COUNT(*) FROM (SELECT event_key, timestamp_ms FROM usage_events WHERE " + ELIGIBLE +
        " GROUP BY event_key, timestamp_ms HAVING COUNT(*) > 1)", bounds).fetchone()[0]
    if duplicates:
        raise ValueError("Repeated event_key plus timestamp_ms pairs need review; refusing to guess deduplication")
    rows = [with_rates(row) for row in connection.execute(
        "SELECT model, " + COUNTERS + " FROM usage_events WHERE " + ELIGIBLE +
        " GROUP BY model ORDER BY positive_reasoning_records DESC, model", bounds)]
    if any(not re.fullmatch(r"gpt-[0-9][a-z0-9.\-]{0,80}", row["model"]) for row in rows):
        raise ValueError("Review unexpected model labels before exporting")
    totals = with_rates(connection.execute("SELECT " + COUNTERS + " FROM usage_events WHERE " + ELIGIBLE, bounds).fetchone())
    for key, value in totals.items():
        if not key.startswith("percent_"):
            assert sum(row[key] for row in rows) == value
    tiers = [dict(row) for row in connection.execute(
        "SELECT (reasoning_tokens + 2) / 518 AS n, reasoning_tokens, COUNT(*) AS records "
        "FROM usage_events WHERE " + ELIGIBLE + " AND " + FORMULA +
        " GROUP BY reasoning_tokens ORDER BY reasoning_tokens", bounds)]
    assert sum(row["records"] for row in tiers) == totals["pattern_matches"]
    auth = [dict(row) for row in connection.execute(
        "SELECT CASE WHEN auth_type IN ('oauth','apikey') THEN auth_type ELSE 'other' END AS auth_type, "
        "COUNT(*) AS records FROM usage_events WHERE " + ELIGIBLE + " GROUP BY 1 ORDER BY 1", bounds)]
    assert sum(row["records"] for row in auth) == totals["successful_generations"]
    effort_count = connection.execute(
        "SELECT COUNT(DISTINCT reasoning_effort) FROM usage_events WHERE " + ELIGIBLE +
        " AND reasoning_effort IS NOT NULL AND reasoning_effort <> ''", bounds).fetchone()[0]
    response_labels = dict(connection.execute(
        "SELECT COALESCE(SUM(response_model IS NOT NULL AND response_model <> ''),0) AS populated_records, "
        "COALESCE(SUM(response_model IS NOT NULL AND response_model <> '' AND response_model <> model),0) AS different_from_request_model "
        "FROM usage_events WHERE " + ELIGIBLE, bounds).fetchone())
    return {"since_inclusive": since.isoformat(), "until_exclusive": until.isoformat(),
            "funnel": funnel, "totals": totals, "models": rows, "pattern_tiers": tiers,
            "auth_types": auth, "distinct_nonempty_reasoning_efforts": effort_count,
            "response_model_labels": response_labels,
            "duplicate_event_key_and_timestamp_pairs": duplicates,
            "count_unit": "one recorded upstream generation; may include Reflow continuation rounds"}


def summarize(database, since, until):
    if not since < until:
        raise ValueError("since must be earlier than until")
    path = database.resolve(strict=True)
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        windows = {"retained_history": summarize_window(connection, since, until),
                   "last_30_days": summarize_window(connection, max(since, until - timedelta(days=30)), until)}
    finally:
        connection.rollback()
        connection.close()
    canonical = json.dumps(windows, sort_keys=True, separators=(",", ":")).encode()
    return {"schema_version": 1, "captured_utc": datetime.now(timezone.utc).isoformat(),
            "source": "CPA/ECPA usage_events, private local usage database",
            "read_only": True, "model_calls": 0, "raw_rows_exported": False,
            "formula": "r = 518*n - 2, integer n >= 1", "primary_denominator": "reasoning_tokens > 0",
            "secondary_denominator": "all eligible successful generations, including recorded zero reasoning",
            "time_rule": "start >= since and start + latency < until; bounds carry an explicit UTC offset",
            "model_label": "recorded request model; not independently verified upstream model identity",
            "windows": windows, "aggregate_sha256": hashlib.sha256(canonical).hexdigest(),
            "limitations": [
                "One installation and its retained history, not a random or representative model sample",
                "Upstream rounds include continuation traffic; a repeated event_key alone is not a duplicate",
                "Mixed tasks, reasoning efforts, auth types and historical plugin states or versions",
                "Does not estimate first-round probability, user-message probability or actual continuation rate",
                "Pattern matches alone do not establish truncation, quality loss or benefit from continuation",
                "Recorded zero reasoning is reported separately; absent and true-zero upstream fields cannot be distinguished here"
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--since", type=parse_time, required=True)
    parser.add_argument("--until", type=parse_time, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.database, args.since, args.until)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({key: value["totals"] for key, value in report["windows"].items()}))


if __name__ == "__main__":
    main()
