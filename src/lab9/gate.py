"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    for name, rep in (("PR", pr), ("baseline", base)):
        bad = [k for k, v in rep["metrics"].items() if isinstance(v, float) and not math.isfinite(v)]
        if bad:
            problems.append(f"{name} metric(s) NaN/inf: {', '.join(bad)}")
    rows = pr["rows"]
    keys = [(r["item_id"], r["seed"]) for r in rows]
    want = pr["manifest"]["items"] * len(pr["manifest"]["seeds"])
    if len(rows) != want:
        problems.append(f"{len(rows)} rows, manifest says {want} (items x seeds): rows dropped or duplicated")
    if len(set(keys)) != len(keys):
        problems.append(f"{len(keys) - len(set(keys))} duplicated (item, seed) row(s)")
    if set(keys) != {(r["item_id"], r["seed"]) for r in base["rows"]}:
        problems.append("(item, seed) set differs from the baseline's: cherry-picked items or seeds")
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), e.g. {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec["metrics"] if m["id"] in GRADERS]
    for m in graded:
        n = sum(r.get(m) is None for r in rows)
        if n:
            problems.append(f"{n} row(s) with no value for {m} (crashed grader drops out of the mean)")
    for m in graded:
        v, vals = pr["metrics"].get(m), [r[m] for r in rows if r.get(m) is not None]
        if not vals or not isinstance(v, (int, float)):
            continue
        got = sum(vals) if m in ("secret_leak", "approval_bypass") else sum(vals) / len(vals)
        if abs(got - v) > 1e-3:
            problems.append(f"{m}: report says {v}, rows give {round(got, 4)} (metrics edited by hand?)")
    tags = lambda rep: {r["item_id"]: frozenset(r.get("slices") or []) for r in rep["rows"]}
    tb = tags(base)
    problems += [f"{i}: slice tags changed from {sorted(tb[i])} to {sorted(t)}"
                 for i, t in sorted(tags(pr).items()) if i in tb and t != tb[i]]
    if base_spec and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Thresholds only get stricter: max/max_increase may not rise, min may not fall,
    no_significant_drop and blocking may not be dropped, nothing may disappear."""
    out: list[str] = []

    def cmp(kind: str, ident: str, new: dict | None, old: dict) -> None:
        if new is None:
            out.append(f"{kind} {ident} removed")
            return
        nt, ot = new.get("threshold") or {}, old.get("threshold") or {}
        for k in ("max", "max_increase"):
            if k in ot and (k not in nt or nt[k] > ot[k]):
                out.append(f"{kind} {ident}: {k} loosened {ot[k]} -> {nt.get(k)}")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            out.append(f"{kind} {ident}: min loosened {ot['min']} -> {nt.get('min')}")
        # slices keep their thresholds at the top level of the entry
        for k in ("max", "min"):
            if kind == "slice" and k in old and (k not in new or (new[k] < old[k] if k == "min" else new[k] > old[k])):
                out.append(f"slice {ident}: {k} loosened {old[k]} -> {new.get(k)}")
        if (ot.get("no_significant_drop") or old.get("no_significant_drop")) and not (
                nt.get("no_significant_drop") or new.get("no_significant_drop")):
            out.append(f"{kind} {ident}: no_significant_drop dropped")
        if old.get("blocking") and not new.get("blocking"):
            out.append(f"{kind} {ident}: no longer blocking")

    new_m = {m["id"]: m for m in spec["metrics"]}
    for m in base_spec["metrics"]:
        cmp("metric", m["id"], new_m.get(m["id"]), m)
    new_s = {s["name"]: s for s in spec.get("slices") or []}
    for s in base_spec.get("slices") or []:
        cmp("slice", s["name"], new_s.get(s["name"]), s)
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    bs = spec.get("bootstrap", {})
    blocked, lines = [], []
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        a, b = per_item(pr, metric, name), per_item(base, metric, name)
        verdict, note = "ok", ""
        if not a:
            verdict, val = "fail", None          # an empty slice hides a regression
        else:
            val = sum(a.values()) / len(a)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if sl.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        ident = f"slice:{name}/{metric}"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(ident)
        label = "ok" if verdict == "ok" else ("BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {ident:<34} {val if val is None else round(val, 4)!s:<8} {note:<30} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
