from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


class LMStudioError(RuntimeError):
    pass


@dataclass(slots=True)
class LMStudioChatResult:
    text: str
    reasoning: str
    stats: dict[str, Any]
    raw: dict[str, Any]


class LMStudioClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout_seconds: float = 600,
    ):
        self.base_url = self._normalize(base_url)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.strip().rstrip("/")
        for suffix in ("/v1", "/api/v1"):
            if value.endswith(suffix):
                value = value[: -len(suffix)]
        return value.rstrip("/")

    @property
    def sdk_host(self) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme:
            return parsed.netloc
        return self.base_url.replace("http://", "").replace("https://", "")

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_models(self) -> list[dict[str, Any]]:
        return [
            model
            for model in self._request("GET", "/api/v1/models").get("models", [])
            if isinstance(model, dict)
        ]

    def model_info(self, key: str) -> dict[str, Any] | None:
        for model in self.list_models():
            if key in {model.get("key"), model.get("selected_variant")} or key in (
                model.get("variants") or []
            ):
                return model
        return None

    def reasoning_config(self, key: str) -> dict[str, Any]:
        """Return the model's public reasoning settings from /api/v1/models.

        LM Studio exposes allowed reasoning modes per model. If no reasoning
        configuration is reported, Arline treats the model as non-reasoning and
        only allows the logical UI state `off` (which is omitted from the API
        payload rather than sent as an unsupported reasoning option).
        """
        info = self.model_info(key) or {}
        capabilities = info.get("capabilities") or {}
        config = capabilities.get("reasoning") or info.get("reasoning") or {}
        allowed = config.get("allowed_options") or []
        allowed = [str(item).lower() for item in allowed if str(item).strip()]
        default = config.get("default")
        return {
            "allowed_options": allowed,
            "default": str(default).lower() if default is not None else None,
            "description": config.get("description"),
            "reported": bool(config),
        }

    def vision_supported(self, key: str) -> bool:
        info = self.model_info(key) or {}
        return bool((info.get("capabilities") or {}).get("vision"))

    def resolve_reasoning_option(self, key: str, requested: str) -> str | None:
        """Validate and resolve a requested reasoning setting for one model.

        Returns None when the model exposes no reasoning controls and the user
        requested `off`; the chat endpoint will then omit the reasoning field.
        """
        requested = str(requested or "off").lower()
        config = self.reasoning_config(key)
        allowed = config["allowed_options"]
        if not allowed:
            if requested == "off":
                return None
            raise LMStudioError(
                f"Model {key!r} does not expose native reasoning controls. "
                "Use reasoning='off'."
            )
        if requested not in allowed:
            raise LMStudioError(
                f"Model {key!r} does not support reasoning={requested!r}. "
                f"Allowed options: {', '.join(allowed)}"
            )
        return requested

    def check_server(self) -> dict[str, Any]:
        return {
            "ok": True,
            "base_url": self.base_url,
            "models": [
                {
                    "key": model.get("key"),
                    "display_name": model.get("display_name"),
                    "loaded": bool(model.get("loaded_instances")),
                    "max_context_length": model.get("max_context_length"),
                    "reasoning": (model.get("capabilities") or {}).get("reasoning"),
                    "vision": bool((model.get("capabilities") or {}).get("vision")),
                }
                for model in self.list_models()
                if model.get("type") == "llm"
            ],
        }

    def unload_model(self, key: str) -> list[str]:
        info = self.model_info(key) or {}
        out: list[str] = []
        for instance in info.get("loaded_instances", []) or []:
            iid = instance.get("id")
            if iid:
                self._request(
                    "POST", "/api/v1/models/unload", payload={"instance_id": iid}
                )
                out.append(iid)
        return out

    def chat(
        self,
        *,
        model: str,
        input_text: str,
        system_prompt: str,
        images: list[str] | None = None,
        temperature: float = 0.8,
        top_p: float = 0.95,
        top_k: int | None = 40,
        min_p: float | None = 0,
        max_tokens: int = 3072,
        repeat_penalty: float | None = 1.05,
        reasoning: str | None = "off",
        context_length: int | None = None,
        seed: int | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> LMStudioChatResult:
        if not model or model.startswith("COPY_MODEL_ID_"):
            raise LMStudioError("Select/configure a model first")

        payload: dict[str, Any] = {
            "model": model,
            "input": input_text if not images else [
                {"type": "message", "content": input_text},
                *[{"type": "image", "data_url": image} for image in images],
            ],
            "system_prompt": system_prompt,
            "stream": False,
            "temperature": temperature,
            "top_p": top_p,
            "max_output_tokens": max_tokens,
        }
        if reasoning is not None:
            payload["reasoning"] = reasoning
        for key, value in (
            ("top_k", top_k),
            ("min_p", min_p),
            ("repeat_penalty", repeat_penalty),
            ("context_length", context_length),
            ("seed", seed),
        ):
            if value is not None:
                payload[key] = value
        for key, value in (extra_payload or {}).items():
            payload.setdefault(key, value)

        raw = self._request("POST", "/api/v1/chat", payload=payload)
        messages: list[str] = []
        thoughts: list[str] = []
        for item in raw.get("output", []) or []:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                continue
            if item.get("type") == "reasoning":
                thoughts.append(item["content"])
            elif item.get("type") == "message":
                messages.append(item["content"])
        if not messages:
            raise LMStudioError("LM Studio response had no message output")
        return LMStudioChatResult(
            "\n".join(messages).strip(),
            "\n".join(thoughts).strip(),
            dict(raw.get("stats") or {}),
            raw,
        )

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + endpoint
        try:
            with httpx.Client(timeout=self.timeout_seconds, headers=self.headers) as client:
                response = client.request(method, url, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LMStudioError(
                f"LM Studio HTTP {exc.response.status_code}: {exc.response.text[:1000]}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LMStudioError(f"LM Studio request failed at {url}: {exc}") from exc
        if not isinstance(data, dict):
            raise LMStudioError("Expected JSON object from LM Studio")
        return data
