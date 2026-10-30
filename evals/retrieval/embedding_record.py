"""Evaluation-only model provenance; declarations are not server attestation."""
import json
from pathlib import Path
import re

VERIFICATION = "not_verified_by_search_api"


def validate_embedding_record(value):
    fields = {"provider", "model", "revision", "native_dimensions", "stored_dimensions",
              "storage_config_id", "model_revision", "source", "runtime_versions", "verification"}
    if not isinstance(value, dict) or set(value) - fields:
        raise ValueError("Invalid embedding record fields; never include credentials")
    try:
        provider, model, revision = (value[k] for k in ("provider", "model", "revision"))
        native, stored = (value[k] for k in ("native_dimensions", "stored_dimensions"))
        identity, source = (value[k] for k in ("storage_config_id", "source"))
        if (provider not in {"openai", "fastembed"}
                or not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,128}", model)
                or not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", revision)
                or type(native) is not int or type(stored) is not int
                or not 1 <= native <= stored or stored != 1536
                or source not in {"operator_declared", "local_runtime_receipt"}
                or not isinstance(identity, str)):
            raise ValueError
        parts = identity.split(":")
        if (len(parts) != 4 or parts[0] != "openai" or parts[2:] != [str(stored), revision]
                or (provider == "openai" and (parts[1] != model or native != stored))):
            raise ValueError
        upstream = value.get("model_revision")
        if upstream is not None and (not isinstance(upstream, str)
                                     or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", upstream)):
            raise ValueError
        versions = value.get("runtime_versions", {})
        if (not isinstance(versions, dict) or set(versions) - {"python", "fastembed", "onnxruntime"}
                or any(v is not None and (not isinstance(v, str)
                       or not re.fullmatch(r"[A-Za-z0-9.+_-]{1,96}", v)) for v in versions.values())
                or value.get("verification", VERIFICATION) != VERIFICATION):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("Invalid embedding model, dimensions, revision or provenance") from None
    return {"provider": provider, "model": model, "revision": revision,
            "native_dimensions": native, "stored_dimensions": stored,
            "storage_config_id": identity, "model_revision": upstream,
            "source": source, "runtime_versions": dict(versions), "verification": VERIFICATION}


def load_embedding_record(path):
    try:
        return validate_embedding_record(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("Could not load a valid embedding record; check its non-secret configuration") from None
