"""LLM（OpenAI 兼容接口）客户端。

当前只实现选课 Agent 所需的边缘能力：
  * baseURL 归一化
  * 自动探测 `/v1` 是否存在
  * 读取可用模型列表（GET {base}/models）
  * 流式对话（供后续 Agent 核心功能使用）

所有函数在失败时抛 LLMError，消息面向用户可读。
"""

from __future__ import annotations

import json

import requests

TIMEOUT = 20


class LLMError(Exception):
    """调用 LLM 服务失败，消息可直接展示给用户。"""


def normalize_base_url(raw: str) -> str:
    """去掉首尾空白与结尾斜杠。"""
    return (raw or "").strip().rstrip("/")


def candidate_urls(base_url: str) -> list:
    """按优先级给出待探测的 baseURL 候选（自动补 /v1）。

    'https://host'      -> ['https://host/v1', 'https://host']
    'https://host/v1'   -> ['https://host/v1', 'https://host']
    """
    base = normalize_base_url(base_url)
    if not base:
        return []
    if base.endswith("/v1"):
        return [base, base[:-3].rstrip("/")]
    return [base + "/v1", base]


def _headers(api_key: str) -> dict:
    return {
        "Authorization": "Bearer " + (api_key or "").strip(),
        "Accept": "application/json",
    }


def list_models(base_url: str, api_key: str) -> dict:
    """检测连通性并读取可用模型。

    返回 {"base_url": 实际可用的 baseURL, "models": [模型 id, ...]}
    失败抛 LLMError。
    """
    if not normalize_base_url(base_url):
        raise LLMError("未填写 baseURL")
    if not (api_key or "").strip():
        raise LLMError("未填写 API Key")

    headers = _headers(api_key)
    errors: list = []
    auth_failed = False

    for url in candidate_urls(base_url):
        endpoint = url + "/models"
        try:
            resp = requests.get(endpoint, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            errors.append(f"{endpoint} -> {type(exc).__name__}: {exc}")
            continue

        if resp.status_code in (401, 403):
            auth_failed = True
            errors.append(f"{endpoint} -> HTTP {resp.status_code}")
            continue
        if resp.status_code != 200:
            errors.append(f"{endpoint} -> HTTP {resp.status_code}")
            continue

        try:
            data = resp.json()
        except ValueError:
            errors.append(f"{endpoint} -> 返回内容不是 JSON")
            continue

        items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(items, list):
            errors.append(f"{endpoint} -> 返回结构中没有模型列表")
            continue

        models: list = []
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                models.append(str(item["id"]))
            elif isinstance(item, str):
                models.append(item)
        models = sorted(set(models))
        if not models:
            errors.append(f"{endpoint} -> 模型列表为空")
            continue
        return {"base_url": url, "models": models}

    if auth_failed:
        raise LLMError("认证失败（HTTP 401/403）：请检查 API Key 是否正确；详情：" + "；".join(errors))
    raise LLMError("无法连接或未找到 /models 接口；详情：" + ("；".join(errors) if errors else "无响应"))


def chat_once(base_url: str, api_key: str, model: str, messages: list,
              temperature: float = 0.2, timeout: int = 120) -> str:
    """单轮对话（OpenAI 兼容 /chat/completions），返回助手回复文本。

    选课 Agent 核心功能尚未实现，这里先提供可用的基础调用。
    """
    base = normalize_base_url(base_url)
    if not base:
        raise LLMError("未填写 baseURL")
    if not (model or "").strip():
        raise LLMError("未选择模型")

    endpoint = (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
    headers = _headers(api_key)
    headers["Content-Type"] = "application/json"
    payload = {"model": model, "messages": messages, "temperature": temperature}

    try:
        resp = requests.post(endpoint, headers=headers, data=json.dumps(payload),
                             timeout=timeout)
    except requests.RequestException as exc:
        raise LLMError(f"请求失败：{type(exc).__name__}: {exc}") from exc

    if resp.status_code != 200:
        detail = resp.text[:300] if resp.text else ""
        raise LLMError(f"HTTP {resp.status_code}：{detail}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError("返回内容不是 JSON") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("返回结构异常，缺少 choices[0].message.content") from exc
