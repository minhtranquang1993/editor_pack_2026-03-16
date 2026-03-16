#!/usr/bin/env python3
"""Auto Regression Suite — smoke regression for core flows."""
import argparse
import ast
import importlib.util
import json
import py_compile
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
OUT = _ROOT / 'memory' / 'regression-last.json'
_PYTHON = sys.executable


def _check_import(path):
    """Check if a Python file can be parsed (syntax-valid) without executing it."""
    p = _ROOT / path
    if not p.exists():
        return ('WARN', f'missing file: {path}')
    try:
        ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
        return ('PASS', 'syntax ok')
    except SyntaxError as e:
        return ('FAIL', f'syntax error: {e}')
    except Exception as e:
        return ('FAIL', str(e))


def _check_import_skip(path):
    """Check syntax via py_compile, but return SKIP (not WARN) if file is missing."""
    p = _ROOT / path
    if not p.exists():
        return ('SKIP', 'file not found')
    try:
        py_compile.compile(str(p), doraise=True)
        return ('PASS', 'syntax ok')
    except py_compile.PyCompileError as e:
        return ('FAIL', f'syntax error: {e}')
    except Exception as e:
        return ('FAIL', str(e))


def _check_cmd(cmd):
    """Run a command (list) and return status based on exit code."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return ('PASS', (r.stdout or 'ok').strip()[:120])
        return ('FAIL', (r.stderr or r.stdout or f'exit {r.returncode}').strip()[:160])
    except subprocess.TimeoutExpired:
        return ('FAIL', f'timeout after 30s: {cmd[0]}')
    except FileNotFoundError:
        return ('WARN', f'command not found: {cmd[0]}')
    except Exception as e:
        return ('FAIL', str(e))


def _check_import_runtime(path, verify_fn=None):
    """Import a Python file and optionally run a verify function on the module."""
    p = _ROOT / path
    if not p.exists():
        return ('WARN', f'missing file: {path}')
    try:
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return ('FAIL', f'import error: {e}')
    if verify_fn:
        try:
            return verify_fn(mod)
        except Exception as e:
            return ('FAIL', f'verify error: {e}')
    return ('PASS', 'import ok')


def _check_import_runtime_skip(path, verify_fn=None):
    """Runtime import check, but return SKIP (not WARN) if file is missing."""
    p = _ROOT / path
    if not p.exists():
        return ('SKIP', 'file not found')
    try:
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return ('FAIL', f'import error: {e}')
    if verify_fn:
        try:
            return verify_fn(mod)
        except Exception as e:
            return ('FAIL', f'verify error: {e}')
    return ('PASS', 'import ok')


def _check_contract():
    """Run contract_check.py --json and summarize output."""
    p = _ROOT / 'tools' / 'contract_check.py'
    if not p.exists():
        return ('WARN', 'missing file: tools/contract_check.py')
    try:
        r = subprocess.run(
            [_PYTHON, str(p), '--json'],
            capture_output=True, text=True, timeout=30,
        )
        # try to parse JSON and summarize
        try:
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                results = data.get('results', data.get('checks', []))
                if isinstance(results, list):
                    total = len(results)
                    failed = [c.get('name', '?') for c in results
                              if c.get('status', '').upper() == 'FAIL']
                    if failed:
                        return ('FAIL', f'failed={",".join(failed)}')
                    return ('PASS', f'checks={total}')
            # dict but unknown shape — fallback
            if r.returncode == 0:
                return ('PASS', (r.stdout or 'ok').strip()[:80])
            return ('FAIL', (r.stderr or r.stdout or f'exit {r.returncode}').strip()[:80])
        except (json.JSONDecodeError, ValueError):
            # not JSON — use raw output
            if r.returncode == 0:
                return ('PASS', (r.stdout or 'ok').strip()[:80])
            return ('FAIL', (r.stderr or r.stdout or f'exit {r.returncode}').strip()[:80])
    except subprocess.TimeoutExpired:
        return ('FAIL', 'timeout after 30s: contract_check.py')
    except Exception as e:
        return ('FAIL', str(e))


# --- Helper: find report-ads script ---
def _find_report_ads_script():
    """Find the first .py file in skills/report-ads/scripts/."""
    scripts_dir = _ROOT / 'skills' / 'report-ads' / 'scripts'
    if not scripts_dir.exists():
        return None
    py_files = sorted(scripts_dir.glob('*.py'))
    return py_files[0] if py_files else None


def _check_report_ads_syntax():
    """Syntax check the report_ads script via py_compile, SKIP if not found."""
    script = _find_report_ads_script()
    if script is None:
        return ('SKIP', 'file not found')
    try:
        py_compile.compile(str(script), doraise=True)
        return ('PASS', 'syntax ok')
    except py_compile.PyCompileError as e:
        return ('FAIL', f'syntax error: {e}')
    except Exception as e:
        return ('FAIL', str(e))


def _check_report_ads_runtime():
    """Runtime import check for report_ads, SKIP if not found."""
    script = _find_report_ads_script()
    if script is None:
        return ('SKIP', 'file not found')
    try:
        spec = importlib.util.spec_from_file_location(script.stem, script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return ('PASS', 'import ok')
    except Exception as e:
        return ('FAIL', f'import error: {e}')


# --- Core flow checks (default suite) ---
def _check_tool_cmd(script_path, args=''):
    """Check a tool by running it, returning WARN if the script is missing."""
    p = _ROOT / script_path
    if not p.exists():
        return ('WARN', f'missing file: {script_path}')
    cmd = [_PYTHON, str(p)] + (args.split() if args else [])
    return _check_cmd(cmd)


_core_checks = {
    'fb_comment': lambda: _check_import('tools/fb_page_comment.py'),
    'kpi': lambda: _check_import('skills/kpi-tracker/scripts/kpi_tracker.py'),
    'ads_insight': lambda: _check_import('skills/ads-insight-auto/scripts/ads_insight.py'),
    'contract': lambda: _check_contract(),
    'idempotency': lambda: _check_tool_cmd('tools/idempotency_guard.py', '--action smoke --key regsuite --check'),
    'ads_budget_pacing': lambda: _check_import_skip('skills/ads-budget-pacing/scripts/ads_budget_pacing.py'),
    'lead_monitor': lambda: _check_import_skip('skills/lead-monitor/scripts/lead_monitor.py'),
    'report_ads': lambda: _check_report_ads_syntax(),
    'context_router_route': lambda: _check_import_skip('tools/context_router.py'),
    'quality_drift_no_dup': lambda: _check_import_skip('tools/quality_drift_detector.py'),
    'mem_manager_syntax': lambda: _check_import_skip('skills/persistent-memory/scripts/mem_manager.py'),
}

# --- Runtime checks (--runtime mode) ---
def _verify_callable(attr_name):
    """Return a verify_fn that checks if module has a callable attribute."""
    def _verify(mod):
        if hasattr(mod, attr_name) and callable(getattr(mod, attr_name)):
            return ('PASS', f'import ok + {attr_name}() found')
        return ('WARN', f'import ok but {attr_name}() not found')
    return _verify


def _verify_context_router(mod):
    """Verify context_router routes marketing tasks correctly."""
    if not hasattr(mod, 'route') or not callable(mod.route):
        return ('WARN', 'import ok but route() not found')
    result = mod.route(task_text="check facebook ads anomaly")
    result_str = str(result) if not isinstance(result, str) else result
    if 'packs/marketing.md' not in result_str:
        return ('FAIL', f'marketing pack missing for ads task; got: {result_str[:100]}')
    if 'AGENTS-CORE.md' not in result_str:
        return ('FAIL', f'AGENTS-CORE.md missing; got: {result_str[:100]}')
    return ('PASS', 'route ok: marketing + AGENTS-CORE')


def _verify_quality_drift_no_dup(mod):
    """Verify METRIC_NAMES has no duplicates."""
    if not hasattr(mod, 'METRIC_NAMES'):
        return ('WARN', 'import ok but METRIC_NAMES not found')
    names = mod.METRIC_NAMES
    if len(names) != len(set(names)):
        dups = [n for n in names if names.count(n) > 1]
        return ('FAIL', f'duplicate metrics: {dups}')
    return ('PASS', f'no duplicates ({len(names)} metrics)')


_runtime_checks = {
    'fb_comment': lambda: _check_import_runtime(
        'tools/fb_page_comment.py', _verify_callable('main')),
    'kpi': lambda: _check_import_runtime(
        'skills/kpi-tracker/scripts/kpi_tracker.py',
        lambda mod: (('PASS', 'import ok + load_config() callable')
                     if hasattr(mod, 'load_config') and callable(mod.load_config)
                     else ('PASS', 'import ok (no load_config)'))),
    'ads_insight': lambda: _check_import_runtime(
        'skills/ads-insight-auto/scripts/ads_insight.py',
        _verify_callable('build_message')),
    'contract': lambda: _check_contract(),
    'idempotency': lambda: _check_tool_cmd(
        'tools/idempotency_guard.py', '--action smoke --key regsuite --check'),
    'ads_budget_pacing': lambda: _check_import_runtime_skip(
        'skills/ads-budget-pacing/scripts/ads_budget_pacing.py',
        _verify_callable('main')),
    'lead_monitor': lambda: _check_import_runtime_skip(
        'skills/lead-monitor/scripts/lead_monitor.py'),
    'report_ads': lambda: _check_report_ads_runtime(),
    'context_router_route': lambda: _check_import_runtime_skip(
        'tools/context_router.py', _verify_context_router),
    'quality_drift_no_dup': lambda: _check_import_runtime_skip(
        'tools/quality_drift_detector.py', _verify_quality_drift_no_dup),
    'mem_manager_syntax': lambda: _check_import_skip(
        'skills/persistent-memory/scripts/mem_manager.py'),
}

# --- Test-only checks (excluded from default runs) ---
_test_checks = {
    'self_test': lambda: ('PASS', 'built-in self test'),
    'self_test_fail': lambda: ('FAIL', 'built-in self test fail'),
}


def run_suite(only=None, runtime=False):
    checks = _runtime_checks if runtime else _core_checks
    all_available = {**checks, **_test_checks}

    if only:
        keys = [x.strip() for x in only.split(',') if x.strip()]
        unknown = [k for k in keys if k not in all_available]
        if unknown:
            print(f"Unknown check(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"Available: {', '.join(all_available.keys())}", file=sys.stderr)
            raise SystemExit(1)
        selected = {k: v for k, v in all_available.items() if k in keys}
    else:
        selected = checks

    results = []
    for name, fn in selected.items():
        status, detail = fn()
        results.append({'name': name, 'status': status, 'detail': detail})
    return results


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    p = argparse.ArgumentParser(description='Auto Regression Suite')
    p.add_argument('--json', action='store_true', help='Output JSON')
    p.add_argument('--runtime', action='store_true', help='Runtime mode: import + verify (not just syntax)')
    p.add_argument('--only', default='', help='Comma-separated check names')
    a = p.parse_args()

    results = run_suite(a.only, runtime=a.runtime)
    out = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'mode': 'runtime' if a.runtime else 'syntax',
        'results': results,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for r in results:
            if r['status'] == 'PASS':
                icon = '✅'
            elif r['status'] == 'WARN':
                icon = '⚠️'
            elif r['status'] == 'SKIP':
                icon = '⏭️'
            else:
                icon = '❌'
            print(f"{icon} {r['name']}: {r['status']} — {r['detail']}")

    has_fail = any(r['status'] == 'FAIL' for r in results)
    has_warn = any(r['status'] == 'WARN' for r in results)

    if has_fail:
        raise SystemExit(1)
    if has_warn:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
