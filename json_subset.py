"""The JSON-schema subset a scenario-v2 deliverable_schema may use, checked at load and validated locally.

No JSON-schema library is installed, so the scenario is limited to keywords this module validates in full. The
same rules make the schema acceptable to a provider's strict mode: every object closes additionalProperties and
requires all of its properties. Output-contract-v3 makes the whole deliverable nullable. Inside it, a property may be
nullable only in that same form, {"anyOf": [<subset schema>, {"type": "null"}]} (C-18-5, DM-72: a partial report
leaves an unknown cell null); no other anyOf.
"""
NULL = {"type": "null"}
KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "minItems", "maxItems",
            "minLength", "maxLength", "description", "title"}
TYPES = ("object", "array", "string", "integer", "number", "boolean")
LIMITS = {"minItems": "array", "maxItems": "array", "minLength": "string", "maxLength": "string"}


def check_schema(schema, path="deliverable_schema"):
    """Raise ValueError unless schema stays inside the subset (load time, never at run time)."""
    if not isinstance(schema, dict):
        raise ValueError(f"{path} must be an object")
    if "anyOf" in schema:
        inner = nullable_inner(schema)
        if inner is None or path.split(".")[-2:-1] != ["properties"]:
            raise ValueError(f"{path}: anyOf is only [<schema>, {{\"type\": \"null\"}}] on a property")
        check_schema(inner, f"{path}.anyOf[0]")
        return
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise ValueError(f"{path} uses unsupported keywords: {', '.join(sorted(unknown))}")
    kind = schema.get("type")
    if kind not in TYPES:
        raise ValueError(f"{path}.type must be one of {', '.join(TYPES)}")
    for key, owner in LIMITS.items():
        if key in schema and (kind != owner or type(schema[key]) is not int or schema[key] < 0):
            raise ValueError(f"{path}.{key} must be a non-negative integer on a {owner}")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values or any(not matches(v, kind) for v in values):
            raise ValueError(f"{path}.enum must be a non-empty list of {kind} values")
    if kind == "object":
        properties = schema.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise ValueError(f"{path}.properties must be a non-empty object")
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"{path}.additionalProperties must be false")
        if not isinstance(schema.get("required"), list) or sorted(schema["required"]) != sorted(properties):
            raise ValueError(f"{path}.required must list every property")
        for name, child in properties.items():
            check_schema(child, f"{path}.properties.{name}")
    elif "properties" in schema or "required" in schema or "additionalProperties" in schema:
        raise ValueError(f"{path}: properties, required and additionalProperties belong to an object")
    if kind == "array":
        check_schema(schema.get("items"), f"{path}.items")
    elif "items" in schema:
        raise ValueError(f"{path}.items belongs to an array")


def nullable_inner(schema):
    """The schema of a nullable property, or None unless schema is exactly {"anyOf": [<schema>, NULL]}."""
    options = schema.get("anyOf")
    if set(schema) != {"anyOf"} or not isinstance(options, list) or len(options) != 2 or options[1] != NULL:
        return None
    inner = options[0]
    return inner if isinstance(inner, dict) and "anyOf" not in inner else None


def matches(value, kind):
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def errors(value, schema, path="deliverable"):
    """Every place value breaks a schema that passed check_schema; [] means valid."""
    if "anyOf" in schema:
        return [] if value is None else errors(value, schema["anyOf"][0], path)
    kind = schema["type"]
    if not matches(value, kind):
        return [f"{path}: expected {kind}"]
    found = []
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{path}: not one of the allowed values")
    if kind == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            found.append(f"{path}: length outside the allowed range")
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            found.append(f"{path}: item count outside the allowed range")
        for index, item in enumerate(value):
            found.extend(errors(item, schema["items"], f"{path}[{index}]"))
    elif kind == "object":
        properties = schema["properties"]
        found.extend(f"{path}.{name}: missing" for name in properties if name not in value)
        found.extend(f"{path}.{name}: not allowed" for name in value if name not in properties)
        for name, child in properties.items():
            if name in value:
                found.extend(errors(value[name], child, f"{path}.{name}"))
    return found
