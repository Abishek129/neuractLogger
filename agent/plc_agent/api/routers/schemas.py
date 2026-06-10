import time
from typing import List, Dict, Any, Set

from fastapi import APIRouter, Depends, HTTPException

from ..permissions import require_logger_write

from ..store import Store

import re


router = APIRouter()

VALID_FIELD_TYPES = {
    "float32", "float", "uint16", "uint16_enum", "int16",
    "uint32", "int32", "float64", "uint64", "int64", "bool16",
}

# DP6(b): derived (formula) fields must be floating point — the engine
# evaluates them as f64; default is float64.
DERIVED_FIELD_TYPES = {"float64", "float32"}

# DP3: exactly the meval 0.2 builtin functions (vendored crate src/expr.rs,
# Context::new). NOTE: meval has NO pow/log/log2 — the old whitelist let those
# validate and then fail to NULL on every row at runtime.
_FORMULA_FUNCTIONS = {
    "sqrt", "exp", "ln", "abs",
    "sin", "cos", "tan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    "floor", "ceil", "round", "signum", "atan2", "min", "max",
}

# meval call arities: plain funcs take exactly 1 arg, atan2 exactly 2,
# min/max are variadic folds over 1+ args (expr.rs func/func2/funcn).
_FORMULA_FUNC_ARITY = {
    **{name: (1, 1) for name in (
        "sqrt", "exp", "ln", "abs",
        "sin", "cos", "tan", "asin", "acos", "atan",
        "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
        "floor", "ceil", "round", "signum",
    )},
    "atan2": (2, 2),
    "min": (1, None),
    "max": (1, None),
}

# DP3: meval Context::new predefines pi and e as VARIABLES. They are always
# referenceable in formulas; a schema field with the same key shadows the
# constant at runtime (device/derived values are ctx.var'd over them).
_FORMULA_CONSTANTS = {"pi", "e"}

# Pattern for extracting identifiers from formula strings
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# SEC-2/L19: PostgreSQL identifier length limit, enforced on field keys.
MAX_IDENT_LEN = 63

# DP6(a): formula token grammar — numbers, identifiers, + - * / % ^ ( ) ,
_FORMULA_TOKEN_RE = re.compile(
    r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"   # number literal
    r"|[A-Za-z_][A-Za-z0-9_]*"                # identifier
    r"|[-+*/%^(),]"                           # operators / punctuation
)

_FORMULA_NUMBER_RE = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _parse_formula(formula: str, key: str) -> Set[str]:
    """DP6(a): syntax-check a formula against the meval grammar and return the
    set of referenced variable names.

    Grammar: numbers, identifiers, binary ``+ - * / % ^``, unary sign,
    parentheses, and comma'd calls of whitelisted functions. An identifier is
    a function call ONLY when directly followed by ``(`` (meval tokenizer
    rule); otherwise it is a variable — even when it collides with a function
    name (meval resolves Var and Call in separate namespaces).

    Raises ``ValueError`` with FORMULA_SYNTAX_INVALID / FORMULA_UNKNOWN_FUNCTION.
    """
    tokens: List[str] = []
    pos = 0
    n = len(formula)
    while pos < n:
        if formula[pos].isspace():
            pos += 1
            continue
        m = _FORMULA_TOKEN_RE.match(formula, pos)
        if not m:
            raise ValueError(
                f"FORMULA_SYNTAX_INVALID:{key}:unexpected character {formula[pos]!r}"
            )
        tokens.append(m.group(0))
        pos = m.end()
    if not tokens:
        raise ValueError(f"FORMULA_SYNTAX_INVALID:{key}:empty formula")

    variables: Set[str] = set()
    idx = [0]

    def peek() -> Any:
        return tokens[idx[0]] if idx[0] < len(tokens) else None

    def take() -> Any:
        tok = peek()
        idx[0] += 1
        return tok

    def fail(msg: str) -> None:
        raise ValueError(f"FORMULA_SYNTAX_INVALID:{key}:{msg}")

    def parse_expr() -> None:
        parse_term()
        while peek() in ("+", "-"):
            take()
            parse_term()

    def parse_term() -> None:
        parse_factor()
        while peek() in ("*", "/", "%"):
            take()
            parse_factor()

    def parse_factor() -> None:
        while peek() in ("+", "-"):  # unary sign(s)
            take()
        parse_atom()
        if peek() == "^":
            take()
            parse_factor()  # right-associative power; exponent may carry a sign

    def parse_atom() -> None:
        tok = take()
        if tok is None:
            fail("unexpected end of formula")
        if _IDENT_RE.fullmatch(tok):
            if peek() == "(":
                if tok not in _FORMULA_FUNCTIONS:
                    raise ValueError(f"FORMULA_UNKNOWN_FUNCTION:{key}:{tok}")
                take()  # '('
                argc = 1
                parse_expr()
                while peek() == ",":
                    take()
                    parse_expr()
                    argc += 1
                if peek() != ")":
                    fail(f"missing ')' in call of {tok}")
                take()
                lo, hi = _FORMULA_FUNC_ARITY[tok]
                if argc < lo or (hi is not None and argc > hi):
                    fail(f"{tok} takes {lo if hi == lo else f'{lo}+'} argument(s), got {argc}")
            else:
                variables.add(tok)
            return
        if tok == "(":
            parse_expr()
            if peek() != ")":
                fail("missing ')'")
            take()
            return
        if _FORMULA_NUMBER_RE.fullmatch(tok):
            return
        fail(f"unexpected token {tok!r}")

    parse_expr()
    if peek() is not None:
        fail(f"unexpected trailing token {peek()!r}")
    return variables


def _extract_formula_vars(formula: str) -> Set[str]:
    """Extract variable identifiers from a formula (call targets are NOT
    variables; bare identifiers ARE, even when named like a function)."""
    return _parse_formula(formula, "_")


def _validate_and_order_derived_fields(fields: List[Dict[str, Any]]) -> None:
    """Validate derived field formulas and assign eval_order via topological sort.

    Mutates fields in-place: sets ``eval_order`` on each derived field.
    Raises ``ValueError`` on duplicate keys, formula syntax errors, unknown
    functions/variables, non-numeric references, self-references (DP1) or
    circular dependencies. Shared by every entry point: create, add/patch
    field, import and the Store-level persistence paths.
    """
    # DP6(d): duplicate keys silently corrupt the dependency graph.
    seen_keys: Set[str] = set()
    for f in fields:
        k = f.get("key")
        if k in seen_keys:
            raise ValueError(f"FIELD_KEY_DUPLICATE:{k}")
        seen_keys.add(k)

    regular_keys = {f["key"] for f in fields if not f.get("formula")}
    derived = [(i, f) for i, f in enumerate(fields) if f.get("formula")]
    if not derived:
        return

    field_types = {f["key"]: (f.get("type") or "").lower() for f in fields}
    derived_keys = {f["key"] for _, f in derived}

    # Build dependency graph: derived_key → set of derived keys it depends on
    deps: Dict[str, Set[str]] = {}
    all_keys = {f["key"] for f in fields}
    for _, f in derived:
        key = f["key"]
        formula_vars = _parse_formula(f["formula"], key)  # DP6(a): syntax check too
        # DP1: a key referenced in its own formula is a 1-node cycle — at
        # runtime the value is never in the meval ctx, so every row is NULL.
        if key in formula_vars:
            raise ValueError(f"FORMULA_SELF_REFERENCE:{key}")
        # Check that all variables reference known field keys (pi/e are meval
        # built-in constants and always known).
        unknown = formula_vars - all_keys - _FORMULA_CONSTANTS
        if unknown:
            raise ValueError(f"FORMULA_UNKNOWN_VARS:{key}:{','.join(sorted(unknown))}")
        # Referenced device fields must be numeric: Text values never enter
        # the meval ctx, so the formula would be NULL on every row.
        non_numeric = sorted(
            v for v in (formula_vars & regular_keys)
            if field_types.get(v) and field_types[v] not in VALID_FIELD_TYPES
        )
        if non_numeric:
            raise ValueError(f"FORMULA_NON_NUMERIC_FIELD:{key}:{','.join(non_numeric)}")
        # Dependencies are only on OTHER derived fields (regular fields are always available)
        deps[key] = formula_vars & derived_keys

    # Topological sort (Kahn's algorithm). (L2: dead duplicate in_degree
    # scaffolding removed.)
    in_degree: Dict[str, int] = {k: 0 for k in deps}
    for k, d in deps.items():
        for dep in d:
            if dep in deps:  # only count edges within derived fields
                in_degree[k] += 1

    queue = [k for k, deg in in_degree.items() if deg == 0]
    order: Dict[str, int] = {}
    idx = 0
    while queue:
        queue.sort()  # deterministic ordering
        node = queue.pop(0)
        order[node] = idx
        idx += 1
        for k, d in deps.items():
            if node in d:
                in_degree[k] -= 1
                if in_degree[k] == 0 and k not in order:
                    queue.append(k)

    if len(order) != len(deps):
        unresolved = set(deps.keys()) - set(order.keys())
        raise ValueError(f"FORMULA_CIRCULAR_DEPENDENCY:{','.join(sorted(unresolved))}")

    # Assign eval_order to the field dicts
    for _, f in derived:
        f["eval_order"] = order[f["key"]]


@router.get("/schemas")
def list_schemas() -> Dict[str, List[Dict[str, Any]]]:
    # Logical parent schemas from in-memory store (no DDL)
    return {"items": Store.instance().list_schemas()}


def _normalize_and_validate_fields(fields: List[Dict[str, Any]]) -> None:
    """Shared field validation for create_schema and import (DP5 parity):
    key regex/length cap, duplicate keys, type whitelist (derived types
    restricted to float32/float64, default float64). Mutates in place."""
    seen = set()
    for f in fields:
        k = (f.get("key") or "").strip()
        if not k:
            raise ValueError("FIELD_KEY_REQUIRED")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) or len(k) > MAX_IDENT_LEN:
            raise ValueError(f"FIELD_KEY_INVALID:{k}")
        if k in seen:
            raise ValueError(f"FIELD_KEY_DUPLICATE:{k}")
        seen.add(k)
        f["key"] = k
        # Derived fields default to float64; regular fields validated against VALID_FIELD_TYPES
        if f.get("formula"):
            ftype = (f.get("type") or "float64").lower()
            if ftype not in DERIVED_FIELD_TYPES:  # DP6(b)
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
            f["type"] = ftype
        else:
            ftype = (f.get("type") or "float32").lower()
            if ftype not in VALID_FIELD_TYPES:
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
            f["type"] = ftype
            f["eval_order"] = None


@router.post("/schemas", dependencies=[Depends(require_logger_write)])
def create_schema(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Expected payload: { id?: str, name: str, fields: [{ key, type, unit?, scale?, desc? }] }
    try:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("NAME_REQUIRED")
        fields = payload.get("fields") or []
        _normalize_and_validate_fields(fields)
        # Validate derived field formulas and compute eval_order
        _validate_and_order_derived_fields(fields)
        schema = Store.instance().create_schema({
            "id": payload.get("id"),
            "name": name,
            "fields": fields,
        })
        return {"success": True, "message": "schema_created", "item": schema}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/schemas/{schema_id}/fields", dependencies=[Depends(require_logger_write)])
def add_schema_field(schema_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add a single field to a schema. Payload: { key, type, unit?, scale?, desc?, formula? }"""
    try:
        key = (payload.get("key") or "").strip()
        if not key:
            raise ValueError("FIELD_KEY_REQUIRED")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) or len(key) > MAX_IDENT_LEN:
            raise ValueError(f"FIELD_KEY_INVALID:{key}")
        existing = Store.instance().get_schema(schema_id)
        if not existing:
            raise ValueError("SCHEMA_NOT_FOUND")
        # DP6(d): adding an existing key must not silently replace it.
        if any(f.get("key") == key for f in (existing.get("fields") or [])):
            raise HTTPException(status_code=409, detail=f"FIELD_KEY_EXISTS:{key}")
        formula = (payload.get("formula") or "").strip() or None
        if formula:
            ftype = (payload.get("type") or "float64").lower()
            if ftype not in DERIVED_FIELD_TYPES:  # DP6(b)
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
        else:
            ftype = (payload.get("type") or "float32").lower()
            if ftype not in VALID_FIELD_TYPES:
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
        field: Dict[str, Any] = {
            "key": key,
            "type": ftype,
            "unit": payload.get("unit"),
            "scale": payload.get("scale"),
            "desc": payload.get("desc"),
            "formula": formula,
        }
        if formula:
            # Validate formula vars against existing schema fields (DP1 self-ref
            # and cycles included). The Store persists the recomputed eval_order
            # for ALL derived fields (DP2).
            all_fields = list(existing.get("fields") or []) + [field]
            _validate_and_order_derived_fields(all_fields)
            field["eval_order"] = field.get("eval_order")
        schema = Store.instance().add_schema_field(schema_id, field)
        # DP7: push derived mapping rows to already-migrated tables of this
        # schema (the Rust engine reloads mappings only on job (re)start).
        resp: Dict[str, Any] = {"success": True, "item": schema}
        if formula:
            from .tables import sync_derived_mappings_for_schema  # local import avoids cycle
            warnings = sync_derived_mappings_for_schema(schema_id)
            if warnings:
                resp["warnings"] = warnings
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/schemas/{schema_id}/fields/{field_key}", dependencies=[Depends(require_logger_write)])
def update_schema_field(schema_id: str, field_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Update a schema field. Payload: { type?, unit?, scale?, desc?, formula? }"""
    try:
        existing = Store.instance().get_schema(schema_id)
        if not existing:
            raise HTTPException(status_code=404, detail="SCHEMA_NOT_FOUND")
        fields = existing.get("fields") or []
        field = next((f for f in fields if f.get("key") == field_key), None)
        if not field:
            raise HTTPException(status_code=404, detail="FIELD_NOT_FOUND")

        # Effective formula after this patch: an explicit empty/None formula in
        # the payload CLEARS it (derived -> regular conversion, DP6c).
        if "formula" in payload:
            formula = (payload.get("formula") or "").strip() or None
        else:
            formula = field.get("formula")

        if formula:
            ftype = (payload.get("type") or field.get("type") or "float64").lower()
            if ftype not in DERIVED_FIELD_TYPES:  # DP6(b)
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")
        else:
            ftype = (payload.get("type") or field.get("type") or "float32").lower()
            if "type" in payload and ftype not in VALID_FIELD_TYPES:
                raise ValueError(f"FIELD_TYPE_INVALID:{ftype}")

        merged = {
            "key": field_key,
            "type": ftype,
            "unit": payload.get("unit", field.get("unit")),
            "scale": payload.get("scale", field.get("scale")),
            "desc": payload.get("desc", field.get("desc")),
            "formula": formula,
        }

        updated_fields = [merged if f.get("key") == field_key else f for f in fields]
        _validate_and_order_derived_fields(updated_fields)
        merged["eval_order"] = merged.get("eval_order")

        # Store persists the FULL field set so every derived field's recomputed
        # eval_order lands in the App DB (DP2), and explicit None values (cleared
        # formula) survive the merge (DP6c).
        schema = Store.instance().update_schema_field(schema_id, field_key, merged)
        resp: Dict[str, Any] = {"success": True, "item": schema}
        # DP7: propagate the new formula/eval_orders to neuract.device_mappings
        # of every already-migrated table on this schema. Engine picks the
        # change up at next job (re)start.
        if formula or field.get("formula"):
            from .tables import sync_derived_mappings_for_schema  # local import avoids cycle
            warnings = sync_derived_mappings_for_schema(schema_id)
            if warnings:
                resp["warnings"] = warnings
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/schemas/{schema_id}", dependencies=[Depends(require_logger_write)])
def delete_schema(schema_id: str) -> Dict[str, Any]:
    """Delete a schema and all its fields. Fails if tables reference it."""
    try:
        deleted = Store.instance().delete_schema(schema_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="SCHEMA_NOT_FOUND")
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/schemas/{schema_id}/fields/{field_key}", dependencies=[Depends(require_logger_write)])
def delete_schema_field(schema_id: str, field_key: str) -> Dict[str, Any]:
    """Delete a single field from a schema."""
    try:
        schema = Store.instance().get_schema(schema_id)
        if schema:
            target = next((f for f in (schema.get("fields") or []) if f.get("key") == field_key), None)
            # DP7: deleting a field other formulas reference would leave the
            # schema permanently invalid (and dependents NULL at runtime).
            dependents = sorted(
                f["key"] for f in (schema.get("fields") or [])
                if f.get("formula") and f.get("key") != field_key
                and field_key in _extract_formula_vars(f["formula"])
            )
            if dependents:
                raise ValueError(f"FIELD_REFERENCED_BY_FORMULA:{field_key}:{','.join(dependents)}")
        else:
            target = None
        deleted = Store.instance().delete_schema_field(schema_id, field_key)
        if not deleted:
            raise HTTPException(status_code=404, detail="FIELD_NOT_FOUND")
        resp: Dict[str, Any] = {"success": True}
        # DP7: drop the orphaned derived mapping row from every migrated table
        # of this schema (otherwise the engine evaluates the ghost forever).
        if target is not None and target.get("formula"):
            from .tables import sync_derived_mappings_for_schema  # local import avoids cycle
            warnings = sync_derived_mappings_for_schema(schema_id)
            if warnings:
                resp["warnings"] = warnings
        return resp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/schemas/export")
def export_schemas() -> Dict[str, Any]:
    return {"schemas": Store.instance().list_schemas()}


@router.post("/schemas/import", dependencies=[Depends(require_logger_write)])
def import_schemas(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Import schemas with full create_schema validation parity (DP5).

    Imported eval_order values are ignored: the topological order is
    recomputed from the formulas, self-healing stale/corrupt exports.
    Any invalid item rejects the whole import (400)."""
    items = payload.get("schemas") or payload.get("items") or []
    try:
        if not isinstance(items, list):
            raise ValueError("SCHEMAS_INVALID")
        validated: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                raise ValueError("SCHEMA_INVALID")
            name = (it.get("name") or "").strip()
            if not name:
                raise ValueError("NAME_REQUIRED")
            fields = it.get("fields") or []
            _normalize_and_validate_fields(fields)
            _validate_and_order_derived_fields(fields)
            # Parity with create_schema: generate an id when the export lacks one.
            sid = it.get("id") or f"sch_{int(time.time() * 1000)}_{len(validated)}"
            validated.append({"id": sid, "name": name, "fields": fields})
        count = Store.instance().import_schemas(validated)
        return {"imported": count}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
