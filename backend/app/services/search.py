"""任务搜索 DSL，完整移植 flower 的 result:/args:/kwargs:/state: 语法。"""
from __future__ import annotations

import re
from typing import Any, Dict

SEARCH_REGEXP = r'(?:[^\s,"]|"(?:\\.|[^"])*")+'


def preprocess_search_value(raw_value: str) -> str:
    return raw_value.strip('" ') if raw_value else ""


def parse_search_terms(raw_search_value: str) -> Dict[str, Any]:
    if not raw_search_value:
        return {}
    parsed: Dict[str, Any] = {}
    for part in re.findall(SEARCH_REGEXP, raw_search_value):
        if not part:
            continue
        if part.startswith("result:"):
            parsed["result"] = preprocess_search_value(part[len("result:"):])
        elif part.startswith("args:"):
            parsed.setdefault("args", []).append(
                preprocess_search_value(part[len("args:"):])
            )
        elif part.startswith("kwargs:"):
            try:
                key, value = [p.strip() for p in part[len("kwargs:"):].split("=")]
            except ValueError:
                continue
            parsed.setdefault("kwargs", {})[key] = preprocess_search_value(value)
        elif part.startswith("state"):
            parsed.setdefault("state", []).append(
                preprocess_search_value(part[len("state:"):])
            )
        else:
            parsed["any"] = preprocess_search_value(part)
    return parsed


def stringified_dict_contains_value(key: str, value: Any, str_dict: str) -> bool:
    """在 "{'a': 1}" 这类字符串里判断键值对，避免每个任务都反序列化。"""
    if not str_dict:
        return False
    value = str(value)
    try:
        key_index = str_dict.index(key) + len(key) + 3
    except ValueError:
        return False
    try:
        comma_index = str_dict.index(",", key_index)
    except ValueError:
        try:
            comma_index = str_dict.index("}", key_index)
        except ValueError:
            return False
    return str(value) == str_dict[key_index:comma_index].strip("\"'")


def task_args_contains_search_args(task_args, search_args) -> bool:
    if not task_args:
        return False
    return all(a in task_args for a in search_args)


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return repr(value)


def satisfies_search_terms(task, search_terms: Dict[str, Any]) -> bool:
    any_term = search_terms.get("any")
    result_term = search_terms.get("result")
    args_terms = search_terms.get("args")
    kwargs_terms = search_terms.get("kwargs")
    state_terms = search_terms.get("state")

    if not any([any_term, result_term, args_terms, kwargs_terms, state_terms]):
        return True

    haystack = "|".join(
        filter(
            None,
            [
                task.name,
                task.uuid,
                task.state,
                task.worker.hostname if task.worker else None,
                task.args,
                task.kwargs,
                _safe_str(task.result),
            ],
        )
    )

    terms = [
        bool(state_terms) and task.state in state_terms,
        bool(any_term) and any_term in haystack,
        bool(result_term) and bool(task.result) and result_term in _safe_str(task.result),
        bool(kwargs_terms)
        and all(
            stringified_dict_contains_value(k, v, task.kwargs)
            for k, v in kwargs_terms.items()
        ),
        bool(args_terms) and task_args_contains_search_args(task.args, args_terms),
    ]
    return any(terms)
