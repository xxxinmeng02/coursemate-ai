"""Check the bounded spike's JSON shape and exact source anchors, not all semantics."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

HERE = Path(__file__).resolve().parent


def check_schema(value, schema):
    kind = schema["type"]
    if kind == "object":
        assert isinstance(value, dict) and set(value) == set(schema["required"])
        for key, child in schema["properties"].items():
            check_schema(value[key], child)
    elif kind == "array":
        assert isinstance(value, list)
        for entry in value:
            check_schema(entry, schema["items"])
    elif kind == "integer":
        assert type(value) is int
    else:
        assert kind == "string" and isinstance(value, str) and value.strip()
    if "enum" in schema:
        assert value in schema["enum"]


def main():
    result = json.loads((HERE / "result.json").read_text())
    source = json.loads((HERE / "sources.json").read_text())
    run = json.loads((HERE / "run.json").read_text())
    check_schema(result, json.loads((HERE / "output-schema.json").read_text()))
    assert len(result["cards"]) == 3 and len(result["faq"]) == 1
    normal = lambda value: re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()
    pages = {p["page_number"]: normal(p["text"]) for p in source["pages"]}
    items = [*result["cards"], *result["faq"]]
    assert len({item["id"] for item in items}) == 4
    for item in items:
        assert item["conditions"] and all(condition.strip() for condition in item["conditions"])
        evidence = item["evidence"]
        assert evidence["source_id"] == source["source_id"]
        assert normal(evidence["quote"]) in pages[evidence["page_number"]]
        assert len(evidence["quote"].split()) <= 5
        assert len(item.get("explanation", item.get("answer", ""))) <= 350
    for card in result["cards"]:
        assert any(re.search(r"[A-Za-z]", alias) for alias in card["aliases"])
        assert any(re.search(r"[\u4e00-\u9fff]", alias) for alias in card["aliases"])
    pdf = HERE.parents[3] / "evals/retrieval/sources" / source["filename"]
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source["pdf_sha256"]
    events = [json.loads(line) for line in (HERE / "events.jsonl").read_text().splitlines() if line.strip()]
    types = Counter(e.get("item", {}).get("type") for e in events if e.get("type", "").startswith("item."))
    assert not (set(types) - {"agent_message", "reasoning"}), types
    assert sum(e.get("type") == "turn.completed" for e in events) == 1
    assert not any(e.get("type") in {"turn.failed", "error"} for e in events)
    assert run["exit_code"] == 0 and run["authentication"] == "chatgpt_saved_login"
    for name, digest in run["inputs_sha256"].items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == digest
    report = {
        "validated_at_utc": datetime.now(timezone.utc).isoformat(), "status": "passed",
        "cards": 3, "faq": 1, "exact_evidence_anchors_verified": 4,
        "pdf_sha256_verified": True, "input_hashes_verified": True,
        "tool_calls_observed": 0, "result_sha256": hashlib.sha256((HERE / "result.json").read_bytes()).hexdigest(),
        "semantic_quality_independently_validated": False,
        "limitations": ["Small smoke test, not a course-wide benchmark",
                        "Exact source anchors do not prove every generated claim",
                        "No independent human review or embedding/retrieval quality evaluation"],
    }
    (HERE / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["# Codex 真实生成样例：MIT 6.006 BFS", "",
             "这是一次独立生成 smoke test。中文内容由 Codex 生成；以下格式和引文定位已自动校验，尚未人工独立复核。",
             "来源：MIT OpenCourseWare，Erik Demaine、Jason Ku、Justin Solomon，6.006 Spring 2020 Lecture 9，第 3–4 页。CC BY-NC-SA 4.0。", ""]
    for card in result["cards"]:
        lines += ["## " + card["title"], "", card["explanation"], "",
                  "适用条件：" + "；".join(card["conditions"]), "",
                  "别名：" + "、".join(card["aliases"]), "",
                  f"来源：PDF 第 {card['evidence']['page_number']} 页；锚点：`{card['evidence']['quote']}`。", ""]
    for faq in result["faq"]:
        lines += ["## 问答：" + faq["question"], "", faq["answer"], "",
                  "适用条件：" + "；".join(faq["conditions"]), "",
                  f"来源：PDF 第 {faq['evidence']['page_number']} 页；锚点：`{faq['evidence']['quote']}`。", ""]
    (HERE / "preview.md").write_text("\n".join(lines))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
