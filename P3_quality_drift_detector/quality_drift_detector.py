#!/usr/bin/env python3
"""Quality Drift Detector — monitors output quality over time.

Tracks 5 metrics over a rolling 7-day window and alerts when
any metric deviates >20% from baseline.

Part of Project Sharpen 8 — Intelligence Layer.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

# Path setup for cross-module imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

METRICS_FILE = os.path.join(PROJECT_ROOT, "memory", "quality-metrics.json")
DRIFT_THRESHOLD = 0.20  # 20%
CRITICAL_METRIC_COUNT = 3  # ≥3 drifted metrics = critical

METRIC_NAMES = [
    "output_length",
    "revision_rounds",
    "tool_call_count",
    "fail_rate",
    "contradiction_flags",
    "task_completed",
    "session_duration_min",
]

METRIC_UNITS = {
    "output_length": "w",
    "revision_rounds": "",
    "tool_call_count": "",
    "fail_rate": "%",
    "contradiction_flags": "",
    "task_completed": "",
    "session_duration_min": "m",
}

DRIFT_DESCRIPTIONS = {
    "output_length": {"up": "outputs đang dài hơn bình thường", "down": "outputs ngắn hơn bình thường"},
    "revision_rounds": {"up": "nhiều vòng sửa hơn", "down": "ít vòng sửa hơn (tốt)"},
    "tool_call_count": {"up": "dùng nhiều tool hơn bình thường", "down": "dùng ít tool hơn"},
    "fail_rate": {"up": "tỷ lệ fail tăng", "down": "tỷ lệ fail giảm (tốt)"},
    "contradiction_flags": {"up": "output mâu thuẫn tăng", "down": "output nhất quán hơn (tốt)"},
    "task_completed": {"up": "nhiều task hoàn thành hơn", "down": "ít task hoàn thành hơn"},
    "session_duration_min": {"up": "session dài hơn", "down": "session ngắn hơn"},
}


def safe_load_json(filepath, default=None):
    """Load JSON file with error handling."""
    if default is None:
        default = []
    try:
        if not os.path.exists(filepath):
            return default
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ Warning: Could not load {filepath}: {e}", file=sys.stderr)
        return default


def safe_save_json(filepath, data):
    """Save JSON file with error handling."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    except IOError as e:
        print(f"❌ Error: Could not save {filepath}: {e}", file=sys.stderr)


def filter_by_days(metrics, days):
    """Filter metrics entries within the last N days."""
    cutoff = datetime.now() - timedelta(days=days)
    result = []
    for entry in metrics:
        try:
            entry_date = datetime.fromisoformat(entry.get("timestamp", entry.get("date", "")))
            if entry_date >= cutoff:
                result.append(entry)
        except (ValueError, TypeError):
            continue
    return result


def calculate_average(entries, metric_name):
    """Calculate average value for a metric across entries."""
    values = []
    for entry in entries:
        val = entry.get(metric_name)
        if val is not None:
            values.append(float(val))
    if not values:
        return 0.0
    return sum(values) / len(values)


def count_unique_days(entries):
    """Count unique days in entries."""
    days = set()
    for entry in entries:
        ts = entry.get("timestamp", entry.get("date", ""))
        if ts:
            days.add(ts[:10])
    return len(days)


def log_session(metrics_data, metric_values):
    """Record current session metrics."""
    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": str(uuid.uuid4())[:8],
    }

    has_values = False
    for name in METRIC_NAMES:
        val = metric_values.get(name)
        if val is not None:
            entry[name] = val
            has_values = True
        else:
            entry[name] = 0

    if not has_values:
        print("⚠️ Warning: No metric values provided, logging defaults (0)")

    metrics_data.append(entry)
    safe_save_json(METRICS_FILE, metrics_data)

    print(f"✅ Session logged ({entry['date']}, id: {entry['session_id']})")
    for name in METRIC_NAMES:
        print(f"  {name}: {entry[name]}")


def check_drift(metrics_data):
    """Compare rolling 7-day avg vs last 3 days. Return list of drifted metrics."""
    if not metrics_data:
        print("✅ No data yet — need at least 1 session to check drift")
        return [], 0

    seven_day = filter_by_days(metrics_data, 7)
    three_day = filter_by_days(metrics_data, 3)

    if not seven_day:
        print("✅ No data within 7-day window")
        return [], 0

    num_days = count_unique_days(seven_day)
    if num_days < 7:
        print(f"⚠️ Limited data ({num_days} days)")

    drifts = []
    for metric_name in METRIC_NAMES:
        avg_7d = calculate_average(seven_day, metric_name)
        avg_3d = calculate_average(three_day, metric_name) if three_day else avg_7d

        if avg_7d == 0:
            if avg_3d > 0:
                pct_change = 1.0  # 100%
            else:
                continue  # Both 0, no drift
        else:
            pct_change = (avg_3d - avg_7d) / avg_7d

        if abs(pct_change) > DRIFT_THRESHOLD:
            direction = "up" if pct_change > 0 else "down"
            drifts.append({
                "metric": metric_name,
                "pct_change": pct_change,
                "avg_7d": avg_7d,
                "avg_3d": avg_3d,
                "direction": direction,
            })

    return drifts, len(seven_day)


def format_metric_value(metric_name, value):
    """Format a metric value with unit."""
    unit = METRIC_UNITS.get(metric_name, "")
    if metric_name == "fail_rate":
        # Internal storage is 0.0-1.0, display as percentage
        return f"{value * 100:.1f}%"
    if isinstance(value, float) and value == int(value):
        return f"{int(value)}{unit}"
    if isinstance(value, float):
        return f"{value:.1f}{unit}"
    return f"{value}{unit}"


def print_drift_results(drifts, session_count):
    """Print drift check results."""
    if not drifts:
        print("✅ No quality drift detected")
        print(f"📊 All {len(METRIC_NAMES)} metrics within normal range (7-day baseline)")
        return 0

    num_drifted = len(drifts)
    if num_drifted >= CRITICAL_METRIC_COUNT:
        print(f"🚨 Critical Quality Drift Detected ({num_drifted} metrics)")
    else:
        print("⚠️ Quality Drift Detected")

    for d in drifts:
        metric = d["metric"]
        pct = d["pct_change"] * 100
        avg_7d = format_metric_value(metric, d["avg_7d"])
        avg_3d = format_metric_value(metric, d["avg_3d"])
        direction = d["direction"]
        desc = DRIFT_DESCRIPTIONS.get(metric, {}).get(direction, "")
        sign = "+" if pct > 0 else ""
        print(f"- {metric}: {sign}{pct:.0f}% (avg {avg_7d} → {avg_3d}) — {desc}")

    print("💡 Gợi ý: Check prompt complexity, consider SIMPLIFY layer")

    if num_drifted >= CRITICAL_METRIC_COUNT:
        return 2  # critical
    return 1  # drift


def generate_report(metrics_data):
    """Generate full 7-day report."""
    if not metrics_data:
        print("📊 No sessions logged yet")
        return 0

    seven_day = filter_by_days(metrics_data, 7)
    three_day = filter_by_days(metrics_data, 3)

    if not seven_day:
        print("📊 No data within 7-day window")
        return 0

    num_days = count_unique_days(seven_day)
    day_note = f" ({num_days} days of data)" if num_days < 7 else ""

    print(f"📊 Quality Report — Last 7 Days{day_note}")
    print("━" * 58)
    print(f"  {'Metric':<22} │ {'7d Avg':>8} │ {'3d Avg':>8} │ {'Change':>10}")
    print("  " + "─" * 54)

    drift_count = 0
    for metric_name in METRIC_NAMES:
        avg_7d = calculate_average(seven_day, metric_name)
        avg_3d = calculate_average(three_day, metric_name) if three_day else avg_7d

        if avg_7d == 0:
            if avg_3d > 0:
                pct_change = 100.0
            else:
                pct_change = 0.0
        else:
            pct_change = ((avg_3d - avg_7d) / avg_7d) * 100

        is_drift = abs(pct_change) > DRIFT_THRESHOLD * 100
        if is_drift:
            drift_count += 1
        icon = "⚠️" if is_drift else "✅"

        val_7d = format_metric_value(metric_name, avg_7d)
        val_3d = format_metric_value(metric_name, avg_3d)
        sign = "+" if pct_change > 0 else ""
        print(f"  {metric_name:<22} │ {val_7d:>8} │ {val_3d:>8} │ {sign}{pct_change:>5.0f}% {icon}")

    print("  " + "━" * 54)
    print(f"  Sessions logged: {len(seven_day)} | Drift alerts: {drift_count}")

    return 0


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Quality Drift Detector — monitor output quality over time"
    )
    parser.add_argument("--log-session", action="store_true",
                        help="Record current session metrics")
    parser.add_argument("--check", action="store_true",
                        help="Check for quality drift vs 7-day baseline")
    parser.add_argument("--report", action="store_true",
                        help="Generate full 7-day quality report")
    # Metric value args for --log-session
    parser.add_argument("--output-length", type=int, default=None,
                        help="Output word count for this session")
    parser.add_argument("--revision-rounds", type=int, default=None,
                        help="Number of revision rounds")
    parser.add_argument("--tool-call-count", type=int, default=None,
                        help="Number of tool calls")
    parser.add_argument("--fail-rate", type=float, default=None,
                        help="Failure rate as decimal (0.0-1.0, displayed as %%)")
    parser.add_argument("--contradiction-flags", type=int, default=None,
                        help="Number of contradiction flags")
    parser.add_argument("--tool-calls", type=int, default=None,
                        help="Number of tool calls (shorthand for --log-session)")
    parser.add_argument("--duration-min", type=float, default=None,
                        help="Session duration in minutes")
    return parser.parse_args()


def main():
    """Entry point."""
    args = parse_args()
    metrics_data = safe_load_json(METRICS_FILE, default=[])

    # Mode: log session
    if args.log_session:
        metric_values = {
            "output_length": args.output_length,
            "revision_rounds": args.revision_rounds,
            "tool_call_count": args.tool_call_count if args.tool_call_count is not None
                               else (args.tool_calls if args.tool_calls is not None else 0),
            "fail_rate": args.fail_rate,
            "contradiction_flags": args.contradiction_flags,
            "task_completed": True,
            "session_duration_min": args.duration_min if args.duration_min is not None else 0,
        }
        log_session(metrics_data, metric_values)
        return 0

    # Mode: check drift
    if args.check:
        drifts, session_count = check_drift(metrics_data)
        return print_drift_results(drifts, session_count)

    # Mode: report
    if args.report:
        return generate_report(metrics_data)

    # No mode selected
    print("Usage: python3 tools/quality_drift_detector.py --log-session [--output-length N ...]")
    print("       python3 tools/quality_drift_detector.py --check")
    print("       python3 tools/quality_drift_detector.py --report")
    return 1


if __name__ == "__main__":
    sys.exit(main())

