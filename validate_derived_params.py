#!/usr/bin/env python3
"""
validate_derived_params.py
==========================

A self-contained validation harness for the LoggerFast "derived parameters" algorithm.

It exercises BOTH halves of the system against an adversarial test corpus:

  (1) The REAL Python validator + topological sort
      `_validate_and_order_derived_fields` from
      agent/plc_agent/api/routers/schemas.py
      -> loaded by AST extraction so we run YOUR EXACT CODE without importing
         the heavy FastAPI/store module.

  (2) A faithful Python re-implementation of the Rust runtime evaluator
      (agent/rust_jobs/src/main.rs eval_derived_fields + to_sql_literal)
      -> single-pass evaluation in the eval_order the validator assigned, with
         IEEE-754 f64 semantics AND the engine's non-finite rule: ANY result
         that is NaN or +/-Infinity (or an eval error) becomes SQL NULL and is
         NOT fed into the meval context, so downstream formulas referencing it
         see an unknown variable -> NULL (unless the name is the builtin pi/e,
         which then shadows back through).

The KEY correctness check: for every "valid" case with inputs, we evaluate the
derived fields TWO independent ways:
      A. order-independent FIXPOINT oracle (ground truth)
      B. Rust-style SINGLE-PASS using the validator's eval_order
and assert A == B (NaN/inf-aware). If they ever differ, the validator produced a
WRONG topological order -> a real algorithm bug, caught here.

We ALSO independently re-derive the dependency graph (a separate oracle, NOT the
code under test) and assert every derived field's eval_order is strictly greater
than each derived dependency's -> the order is a valid topological sort.

Usage:
    python3 validate_derived_params.py [cases.json] [--verbose]

Exit code is non-zero if any case fails.
"""

import sys
import ast
import re
import math
import json
import copy
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Config / paths                                                             #
# --------------------------------------------------------------------------- #

HERE = Path(__file__).resolve().parent
SCHEMAS_PY = HERE / "agent" / "plc_agent" / "api" / "routers" / "schemas.py"
DEFAULT_CASES = HERE / "derived_param_cases.json"

INF = float("inf")
NAN = float("nan")

# Functions the Rust meval Context exposes — the EXACT meval 0.2 builtin set
# (vendored crate src/expr.rs Context::new): sqrt exp ln abs, the trig/hyp
# family, floor ceil round signum, atan2 (2 args), variadic min/max, plus the
# predefined VARIABLES pi and e. meval has NO pow/log/log2/log10 (DP3/DP9:
# MEVAL_HAS_LOG is definitively False; constants kept for documentation).
MEVAL_LOG_IS_LOG10 = False  # moot: meval has no `log` builtin at all
MEVAL_HAS_LOG = False       # confirmed against vendored meval-0.2.x expr.rs


# --------------------------------------------------------------------------- #
#  (1) Load the REAL validator via AST extraction (no heavy imports)          #
# --------------------------------------------------------------------------- #

def load_real_validator(path: Path):
    """Extract just the derived-field helpers from schemas.py and exec them in a
    clean namespace, so we test the actual shipped code without pulling in
    fastapi / ..store / ..permissions."""
    src = path.read_text()
    tree = ast.parse(src)

    wanted_funcs = {"_extract_formula_vars", "_validate_and_order_derived_fields",
                    "_parse_formula"}
    wanted_assign = {"_FORMULA_FUNCTIONS", "_IDENT_RE", "_FORMULA_CONSTANTS",
                     "_FORMULA_FUNC_ARITY", "_FORMULA_TOKEN_RE", "_FORMULA_NUMBER_RE",
                     "VALID_FIELD_TYPES", "DERIVED_FIELD_TYPES", "MAX_IDENT_LEN"}

    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            keep.append(node)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & wanted_assign:
                keep.append(node)

    if not any(isinstance(n, ast.FunctionDef) and n.name == "_validate_and_order_derived_fields"
               for n in keep):
        raise RuntimeError("Could not find _validate_and_order_derived_fields in %s" % path)

    module = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(module)
    # PEP 585: map typing names to builtins so annotations like List[Dict[str,Any]] evaluate.
    ns = {"re": re, "List": list, "Dict": dict, "Any": object, "Set": set}
    exec(compile(module, filename=str(path), mode="exec"), ns)
    return ns["_validate_and_order_derived_fields"], ns


# --------------------------------------------------------------------------- #
#  (2) Faithful Rust/meval-style numeric evaluator (IEEE-754)                  #
# --------------------------------------------------------------------------- #

def ieee_div(a, b):
    if b == 0.0:
        if a != a or a == 0.0:      # x/0 where x is NaN, or 0/0
            return NAN
        return math.copysign(INF, a) * math.copysign(1.0, b)
    return a / b


def ieee_pow(a, b):
    # Rust f64::powf: negative base with fractional exponent -> NaN; overflow -> inf.
    try:
        r = math.pow(a, b)
        return float(r)
    except ValueError:      # e.g. (-1) ** 0.5
        return NAN
    except OverflowError:
        return INF


def _s_sqrt(x):  return math.sqrt(x) if x >= 0 else NAN
def _s_ln(x):    return math.log(x) if x > 0 else (-INF if x == 0 else NAN)
def _s_exp(x):
    try:
        return math.exp(x)
    except OverflowError:
        return INF


def _guard_nan(fn):
    """Rust f64 math functions return NaN for out-of-domain args instead of raising."""
    def wrapped(x):
        try:
            r = fn(x)
        except ValueError:
            return NAN
        except OverflowError:
            return INF
        return float(r)
    return wrapped


def _rust_min2(a, b):
    # Rust f64::min: if one operand is NaN, returns the other.
    if a != a:
        return b
    if b != b:
        return a
    return a if a < b else b


def _rust_max2(a, b):
    if a != a:
        return b
    if b != b:
        return a
    return a if a > b else b


def _meval_min(*xs):
    # meval min_array: fold from +inf with f64::min -> NaN-ABSORBING (DP9).
    m = INF
    for x in xs:
        m = _rust_min2(m, x)
    return m


def _meval_max(*xs):
    m = -INF
    for x in xs:
        m = _rust_max2(m, x)
    return m


# EXACT meval 0.2 builtin function set (expr.rs Context::new). No pow/log/log2.
MEVAL_FUNCS = {
    "sqrt": _s_sqrt, "exp": _s_exp, "ln": _s_ln, "abs": abs,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": _guard_nan(math.asin), "acos": _guard_nan(math.acos), "atan": math.atan,
    "sinh": _guard_nan(math.sinh), "cosh": _guard_nan(math.cosh), "tanh": math.tanh,
    "asinh": math.asinh, "acosh": _guard_nan(math.acosh), "atanh": _guard_nan(math.atanh),
    "floor": math.floor, "ceil": math.ceil,
    "round": lambda x: float(math.floor(x + 0.5)) if x == x and abs(x) != INF else x,  # f64::round half-away-from-zero
    "signum": lambda x: NAN if x != x else math.copysign(1.0, x),
    "atan2": math.atan2,
    "min": _meval_min, "max": _meval_max,
}

# meval Context::new predefines pi and e as VARIABLES; device/derived values
# with the same key shadow them (ctx.var overwrites).
MEVAL_CONSTS = {"pi": math.pi, "e": math.e}


class EvalError(Exception):
    pass


def _eval_node(node, ctx):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise EvalError("non-numeric constant %r" % (node.value,))
        return float(node.value)
    if isinstance(node, ast.Name):
        # meval tokenizes an identifier NOT followed by '(' as Var; vars and
        # funcs live in separate Context maps (DP9: a device field literally
        # named `min` or `log` IS usable as a plain variable — only Call
        # targets resolve in the funcs namespace).
        if node.id in ctx:
            return float(ctx[node.id])
        raise EvalError("undefined variable %r" % node.id)   # -> caught -> NaN (mirrors meval)
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand, ctx)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        raise EvalError("unsupported unary op")
    if isinstance(node, ast.BinOp):
        a = _eval_node(node.left, ctx)
        b = _eval_node(node.right, ctx)
        if isinstance(node.op, ast.Add):  return a + b
        if isinstance(node.op, ast.Sub):  return a - b
        if isinstance(node.op, ast.Mult): return a * b
        if isinstance(node.op, ast.Div):  return ieee_div(a, b)
        if isinstance(node.op, ast.Pow):  return ieee_pow(a, b)   # `^` was translated to `**`
        if isinstance(node.op, ast.Mod):                          # meval `%` is Rust f64 rem
            return math.fmod(a, b) if b != 0 else NAN
        raise EvalError("unsupported binary op %s" % type(node.op).__name__)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise EvalError("unsupported call target")
        fn = MEVAL_FUNCS.get(node.func.id)
        if fn is None:
            raise EvalError("unknown function %r" % node.func.id)  # meval lacks it -> NaN
        args = [_eval_node(a, ctx) for a in node.args]
        return float(fn(*args))
    raise EvalError("unsupported expr node %s" % type(node).__name__)


def eval_formula(formula: str, ctx: dict) -> float:
    """Evaluate a single formula the way meval would (raises EvalError on failure)."""
    expr = formula.replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return float(_eval_node(tree, ctx))


# --------------------------------------------------------------------------- #
#  Independent dependency oracle (NOT the code under test)                     #
# --------------------------------------------------------------------------- #

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def referenced_vars(formula: str):
    """Identifiers used as VARIABLES: an identifier directly followed by '('
    is a function-call target (meval tokenizer rule), everything else is a
    variable — even when it collides with a builtin function name (DP9)."""
    out = set()
    for m in _IDENT.finditer(formula):
        rest = formula[m.end():].lstrip()
        if rest.startswith("("):
            continue
        out.add(m.group(0))
    return out


def derived_deps(field, derived_keys):
    """Which OTHER derived fields this field's formula depends on."""
    return (referenced_vars(field["formula"]) & derived_keys) - {field["key"]}


# --------------------------------------------------------------------------- #
#  Evaluators: fixpoint oracle vs Rust-style single pass                       #
# --------------------------------------------------------------------------- #

def _base_ctx(device_values):
    """meval Context::new vars (pi, e) overlaid with device values (shadowing)."""
    ctx = dict(MEVAL_CONSTS)
    ctx.update({k: float(v) for k, v in device_values.items()})
    return ctx


def fixpoint_eval(fields, device_values):
    """Order-INDEPENDENT ground truth. Evaluate each derived field only once
    ALL of its derived dependencies have been ATTEMPTED; iterate to a fixpoint.

    Mirrors the NEW engine rule (main.rs eval_derived_fields): any non-finite
    result (NaN/+inf/-inf) or eval error -> recorded as NaN (SQL NULL) and NOT
    fed into the ctx, so dependents see an unknown variable -> NULL (unless
    the name is the builtin pi/e, which shadows back through).
    Returns dict of derived_key -> float (NaN == stored NULL)."""
    ctx = _base_ctx(device_values)
    derived = [f for f in fields if f.get("formula")]
    dkeys = {f["key"] for f in derived}
    done = {}
    remaining = list(derived)
    progressed = True
    while remaining and progressed:
        progressed = False
        still = []
        for f in remaining:
            deps = derived_deps(f, dkeys)
            if deps <= set(done.keys()):      # every derived dep attempted
                try:
                    val = eval_formula(f["formula"], ctx)
                except EvalError:
                    val = NAN
                if math.isfinite(val):
                    ctx[f["key"]] = val
                else:
                    val = NAN                 # non-finite -> NULL, not fed to ctx
                done[f["key"]] = val
                progressed = True
            else:
                still.append(f)
        remaining = still
    # Anything still remaining is unresolvable (cycle) -> NaN.
    for f in remaining:
        done[f["key"]] = NAN
    return done, bool(remaining)


def singlepass_eval(fields, device_values):
    """Mirror Rust eval_derived_fields: derived fields sorted by the
    validator-assigned eval_order, each evaluated once; ONLY finite results
    are fed back into the context (non-finite/error -> NaN == SQL NULL)."""
    ctx = _base_ctx(device_values)
    derived = sorted((f for f in fields if f.get("formula")),
                     key=lambda f: f.get("eval_order", 0))
    out = {}
    for f in derived:
        try:
            val = eval_formula(f["formula"], ctx)
        except EvalError:
            val = NAN
        if math.isfinite(val):
            ctx[f["key"]] = val
        else:
            val = NAN
        out[f["key"]] = val
    return out


def to_sql_literal(v):
    """Replicate Rust FieldValue::Float -> SQL literal: ANY non-finite value
    (NaN or +/-Infinity) is SQL NULL (main.rs to_sql_literal, DP4 fix)."""
    if not math.isfinite(v):
        return "NULL"
    return repr(v)


# --------------------------------------------------------------------------- #
#  Comparison helpers                                                          #
# --------------------------------------------------------------------------- #

def approx_eq(a, b, rel=1e-9, abs_=1e-12):
    na, nb = (a != a), (b != b)
    if na or nb:
        return na and nb                       # NaN == NaN for our purposes
    if math.isinf(a) or math.isinf(b):
        return a == b                          # same signed infinity
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def topo_order_valid(fields):
    """Independently verify the validator's eval_order is a real topological order:
    every derived field's eval_order must exceed each of its derived deps'."""
    derived = [f for f in fields if f.get("formula")]
    order = {f["key"]: f.get("eval_order") for f in derived}
    dkeys = set(order.keys())
    problems = []
    for f in derived:
        eo = order[f["key"]]
        if eo is None:
            problems.append("%s has no eval_order" % f["key"])
            continue
        for dep in derived_deps(f, dkeys):
            if order.get(dep) is None or order[dep] >= eo:
                problems.append("%s(eo=%s) must come after dep %s(eo=%s)"
                                % (f["key"], eo, dep, order.get(dep)))
    return problems


# --------------------------------------------------------------------------- #
#  Runner                                                                      #
# --------------------------------------------------------------------------- #

GREEN = "\033[32m"; RED = "\033[31m"; YEL = "\033[33m"; DIM = "\033[2m"; RST = "\033[0m"
def c(col, s): return f"{col}{s}{RST}" if sys.stdout.isatty() else s


VALIDATOR_ERRORS = (
    "FORMULA_UNKNOWN_VARS",
    "FORMULA_CIRCULAR_DEPENDENCY",
    "FORMULA_SELF_REFERENCE",       # DP1
    "FORMULA_SYNTAX_INVALID",       # DP6(a)
    "FORMULA_UNKNOWN_FUNCTION",     # DP3/DP6(a)
    "FORMULA_NON_NUMERIC_FIELD",    # text-typed field referenced in a formula
    "FIELD_KEY_DUPLICATE",          # DP6(d) — now also validator-level
)


def run_case(validate, case, verbose=False):
    """Return (status, lines) where status in {PASS, FAIL, SKIP}."""
    name = case["name"]
    kind = case["expect_kind"]
    fields = copy.deepcopy(case["fields"])     # validator mutates in place
    lines = []

    # Error cases the validator function itself does NOT raise (router-level) -> SKIP.
    if kind == "error":
        prefix = case.get("error_prefix", "")
        if not prefix.startswith(VALIDATOR_ERRORS):
            return "SKIP", [f"  router-level error '{prefix}' not raised by the "
                            f"validator function (out of scope for this unit)."]

    # Run the real validator.
    raised = None
    try:
        validate(fields)
    except ValueError as e:
        raised = str(e)
    except Exception as e:      # noqa  (any other exception is itself a failure)
        return "FAIL", [f"  validator raised unexpected {type(e).__name__}: {e}"]

    if kind == "error":
        prefix = case["error_prefix"]
        if raised is None:
            return "FAIL", [f"  expected error {prefix} but validator accepted the schema"]
        if not raised.startswith(prefix):
            return "FAIL", [f"  expected error prefix {prefix!r} but got {raised!r}"]
        return "PASS", [f"  correctly rejected -> {raised}"] if verbose else []

    # kind == "valid"
    if raised is not None:
        return "FAIL", [f"  expected valid schema but validator raised: {raised}"]

    # 1. eval_order must be a valid topological order (independent oracle).
    problems = topo_order_valid(fields)
    if problems:
        return "FAIL", (["  eval_order is NOT a valid topological order:"]
                        + [f"    - {p}" for p in problems])

    # 2. If we have inputs, cross-check single-pass (Rust) vs fixpoint (oracle).
    dv = case.get("device_values")
    if dv:
        regular = [f["key"] for f in fields if not f.get("formula")]
        used_regular = set()
        for f in fields:
            if f.get("formula"):
                used_regular |= referenced_vars(f["formula"]) & set(regular)
        missing = used_regular - set(dv.keys())
        if missing:
            return "SKIP", [f"  device_values missing for {sorted(missing)} -> numeric check skipped"]

        ref, ref_unresolved = fixpoint_eval(fields, dv)
        sp = singlepass_eval(fields, dv)

        mism = []
        for k in ref:
            if not approx_eq(ref[k], sp.get(k, NAN)):
                mism.append(f"    {k}: single-pass={sp.get(k)!r}  fixpoint={ref[k]!r}")
        if mism:
            return "FAIL", ["  single-pass (Rust order) != fixpoint (ground truth):"] + mism

        if verbose:
            tbl = [f"  derived values (single-pass) + SQL literal:"]
            for f in sorted((x for x in fields if x.get("formula")),
                            key=lambda x: x.get("eval_order", 0)):
                k = f["key"]; v = sp[k]
                tbl.append(f"    [{f['eval_order']:>2}] {k:<28} = {v!r:<24} -> {to_sql_literal(v)}")
            return "PASS", tbl
        return "PASS", []

    # valid, no inputs: order already verified.
    if verbose:
        order = ", ".join(f"{f['key']}={f['eval_order']}"
                          for f in fields if f.get("formula"))
        return "PASS", [f"  eval_order: {order}"]
    return "PASS", []


def main():
    args = [a for a in sys.argv[1:]]
    verbose = "--verbose" in args or "-v" in args
    args = [a for a in args if a not in ("--verbose", "-v")]
    cases_path = Path(args[0]) if args else DEFAULT_CASES

    print(c(DIM, "=" * 78))
    print(" LoggerFast derived-parameters validation harness")
    print(c(DIM, " validator : ") + str(SCHEMAS_PY))
    print(c(DIM, " meval cfg : ") + f"has_log={MEVAL_HAS_LOG} (verified against vendored "
          "meval-0.2 expr.rs); non-finite -> NULL, not fed to ctx (main.rs)")
    print(c(DIM, "=" * 78))

    try:
        validate, _ns = load_real_validator(SCHEMAS_PY)
    except Exception as e:
        print(c(RED, f"FATAL: could not load real validator: {e}"))
        return 2

    if not cases_path.exists():
        print(c(RED, f"FATAL: cases file not found: {cases_path}"))
        print("  (run the corpus workflow first, or pass a path to a cases JSON)")
        return 2

    data = json.loads(cases_path.read_text())
    cases = data["cases"] if isinstance(data, dict) and "cases" in data else data
    print(f" loaded {len(cases)} cases from {cases_path.name}\n")

    by_cat = {}
    n_pass = n_fail = n_skip = 0
    failures = []

    for case in cases:
        status, lines = run_case(validate, case, verbose=verbose)
        cat = case.get("category", "?")
        by_cat.setdefault(cat, [0, 0, 0])
        if status == "PASS":
            by_cat[cat][0] += 1; n_pass += 1; mark = c(GREEN, "PASS")
        elif status == "FAIL":
            by_cat[cat][1] += 1; n_fail += 1; mark = c(RED, "FAIL")
            failures.append(case["name"])
        else:
            by_cat[cat][2] += 1; n_skip += 1; mark = c(YEL, "SKIP")

        if status == "FAIL" or verbose or status == "SKIP":
            print(f" [{mark}] {case.get('category','?')}/{case['name']}")
            if case.get("description"):
                print(c(DIM, f"   {case['description']}"))
            for ln in lines:
                print(ln)
        else:
            print(f" [{mark}] {case.get('category','?')}/{case['name']}")

    print()
    print(c(DIM, "-" * 78))
    print(" Per-category (pass/fail/skip):")
    for cat in sorted(by_cat):
        p, f_, s = by_cat[cat]
        col = GREEN if f_ == 0 else RED
        print(f"   {c(col, cat):<40} {p:>3} / {f_:>3} / {s:>3}")
    print(c(DIM, "-" * 78))
    total = n_pass + n_fail + n_skip
    summary = f" TOTAL: {n_pass} passed, {n_fail} failed, {n_skip} skipped  (of {total})"
    print(c(GREEN if n_fail == 0 else RED, summary))
    if failures:
        print(c(RED, " failing cases: ") + ", ".join(failures))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
