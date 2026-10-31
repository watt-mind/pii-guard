"""Schema and metric-rate validation for benchmark run records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Where the JSON Schema and the run records live relative to the repository root.
SCHEMA_PATH = Path("eval/results/schema/run.schema.json")


class RecordError(ValueError):
    """A run record is malformed, or one can't be built from the input given."""


# --- Schema validation --------------------------------------------------------------------

#: The JSON Schema keywords :func:`validate` implements (a subset of draft 2020-12). The
#: committed schema may only use these; a test enforces it.
SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema", "$id", "$defs", "$ref", "$comment", "title", "description", "examples",
        "type", "properties", "required", "additionalProperties", "items", "enum", "const",
        "pattern", "propertyNames", "minimum", "maximum", "minLength", "anyOf", "default",
    }
)  # fmt: skip

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(value: object, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _validate_scalar(value: Any, schema: Mapping[str, Any], path: str, errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")


def _validate_object(
    value: dict[str, Any],
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    for key in schema.get("required", []):
        if key not in value:
            errors.append(f"{path}: missing {key!r}")
    props = schema.get("properties", {})
    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        if "propertyNames" in schema:
            _validate(key, schema["propertyNames"], root, f"{path}.{key}<name>", errors)
        if key in props:
            _validate(item, props[key], root, f"{path}.{key}", errors)
        elif additional is False:
            errors.append(f"{path}: unexpected field {key!r}")
        elif isinstance(additional, dict):
            _validate(item, additional, root, f"{path}.{key}", errors)


def _validate(
    value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str, errors: list[str]
) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise RecordError(f"unsupported $ref {ref!r}")
        _validate(value, root["$defs"][ref.removeprefix("#/$defs/")], root, path, errors)
        return
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            trial: list[str] = []
            _validate(value, option, root, path, trial)
            if not trial:
                break
        else:
            errors.append(f"{path}: matches none of the allowed forms")
            return
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, n) for n in names):
            errors.append(f"{path}: expected {'/'.join(names)}, got {type(value).__name__}")
            return
    _validate_scalar(value, schema, path, errors)
    if isinstance(value, dict):
        _validate_object(value, schema, root, path, errors)
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], root, f"{path}[{i}]", errors)


def load_schema(path: str | Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(record: Mapping[str, Any], schema: Mapping[str, Any] | None = None) -> list[str]:
    """Errors of ``record`` against the run-record schema (empty list = valid).

    Besides the JSON Schema, checks what a schema can't say: ``metrics`` matches ``kind``, the
    run id starts with the date, and every rate of a text run is its count / denominator
    (:func:`rate_errors`).
    """
    schema = schema if schema is not None else load_schema()
    errors: list[str] = []
    _validate(record, schema, schema, "$", errors)
    if errors:
        return errors
    kind, metrics = record["kind"], record["metrics"]
    if kind == "text" and "languages" not in metrics:
        errors.append("$.metrics: a text run needs 'overall' and 'languages'")
    if kind == "visual" and "by_region_type" not in metrics:
        errors.append("$.metrics: a visual run needs 'by_region_type'")
    if kind == "latency" and "cells" not in metrics:
        errors.append("$.metrics: a latency run needs 'cells'")
    if not str(record["run_id"]).startswith(record["date"]):
        errors.append("$.run_id: must start with the run date")
    if kind == "text" and "languages" in metrics:
        from pii_guard.eval.validity import validity_errors

        errors += rate_errors(metrics["overall"], "$.metrics.overall")
        errors += validity_errors(metrics["overall"], "$.metrics.overall")
        for lang, block in metrics["languages"].items():
            errors += rate_errors(block, f"$.metrics.languages.{lang}")
            errors += validity_errors(block, f"$.metrics.languages.{lang}")
    return errors


#: How far a stored rate may be from its counts: records keep 6 decimals, imported ones 4.
RATE_TOLERANCE = 1e-4


def _q(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1_of(p: float | None, r: float | None) -> float | None:
    if p is None and r is None:
        return None
    if not p or not r:
        return 0.0
    return 2 * p * r / (p + r)


def rate_errors(block: Mapping[str, Any], path: str) -> list[str]:
    """Rates in a text block that aren't their count / denominator (``null`` = not measured).

    A rate given for an empty denominator is an error too. Checked: precision, recall and F1
    in both match modes, leak and partial leak, over-masking, round trip, consistency, the
    outbound re-check's false-block rate.
    """
    errors: list[str] = []

    def check(name: str, got: object, want: float | None) -> None:
        if got is None:
            return
        if want is None or not isinstance(got, int | float):
            errors.append(f"{path}.{name}: {got} given, but its denominator is 0")
        elif abs(float(got) - want) > RATE_TOLERANCE:
            errors.append(f"{path}.{name}: {got} is not its counts' ratio ({want:.6f})")

    for mode in ("exact", "overlap"):
        m = block[mode]
        p, r = _q(m["tp_pred"], m["pred"]), _q(m["tp_gold"], m["gold"])
        check(f"{mode}.precision", m["precision"], p)
        check(f"{mode}.recall", m["recall"], r)
        check(f"{mode}.f1", m["f1"], _f1_of(p, r))
    leak = block["leak"]
    check("leak.rate", leak["rate"], _q(leak["leaked"], leak["values"]))
    check("leak.partial_rate", leak["partial_rate"], _q(leak["partial"], leak["values"]))
    over = block["over_masking"]
    check("over_masking.rate", over["rate"], _q(over["over_masked"], over["masked"]))
    if block.get("roundtrip"):
        rt = block["roundtrip"]
        check("roundtrip.rate", rt["rate"], _q(rt["exact"], rt["documents"]))
    if block.get("consistency"):
        c = block["consistency"]
        check("consistency.rate", c["rate"], _q(c["consistent"], c["entities"]))
        check(
            "consistency.multi_rate",
            c["multi_rate"],
            _q(c["multi_consistent"], c["multi_occurrence"]),
        )
    if block.get("outbound_check"):
        ob = block["outbound_check"]
        check("outbound_check.rate", ob["rate"], _q(ob["blocked"], ob["checked"]))
    return errors
