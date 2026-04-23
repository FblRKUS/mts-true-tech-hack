from __future__ import annotations

from typing import Any
import json


def strip_code_fence(response_text: str) -> str:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
    return cleaned.strip()


def parse_json_dict(response_text: str) -> dict[str, Any]:
    cleaned = strip_code_fence(response_text)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    try:
        parsed, _ = json.JSONDecoder().raw_decode(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(cleaned[start : end + 1].strip())
        if isinstance(parsed, dict):
            return parsed

    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def parse_file_map(response_text: str) -> dict[str, str]:
    payload = parse_json_dict(response_text)
    if not payload:
        raise ValueError("Empty file map returned by agent")

    file_map: dict[str, str] = {}
    for raw_path, raw_content in payload.items():
        path = str(raw_path).strip()
        if not path:
            continue
        if "\n" in path or "\r" in path:
            continue
        if isinstance(raw_content, str):
            content = raw_content
        else:
            content = json.dumps(raw_content, ensure_ascii=False, indent=2)
        file_map[path] = content

    if not file_map:
        raise ValueError("No valid files in file map")
    return file_map
