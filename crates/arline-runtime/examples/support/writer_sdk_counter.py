"""Optional JSON-lines counter using the documented, separately installed SDK.

No model() calls: enumerate already loaded handles so counting never JIT-loads
weights. Without a matching qualification profile, counts remain estimates.
Native Arline does not require Python or this helper for conservative counting.
"""
import argparse
import hashlib
import json
import sys
from urllib.parse import urlparse

PROBE = "Nafila membeli obat. English. 日本語。 👩🏽‍🚀 <Canon>{\"x\":1}</Canon>"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def inspect(model):
    import lmstudio as lms
    info = model.get_info().to_dict()
    probe = lms.Chat("Arline tokenizer qualification.")
    probe.add_user_message(PROBE)
    template = model.apply_prompt_template(probe)
    return {
        "model_key": info["modelKey"],
        "instance_reference": info["instanceReference"],
        "loaded_context_length": model.get_context_length(),
        "template_sha256": digest(template),
        "tokenizer_probe_sha256": digest(json.dumps(model.tokenize(PROBE))),
    }


def formatted(model, payload, transform=False):
    import lmstudio as lms
    chat = lms.Chat(payload.get("system_prompt", ""))
    chat.add_user_message(payload["input"])
    value = model.apply_prompt_template(chat)
    if transform and payload.get("reasoning") == "off":
        if not value.endswith("<think>\n"):
            raise ValueError("qualified reasoning template changed")
        value += "</think>\n\n"
    return value


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    args = parser.parse_args()
    profile = json.load(open(args.profile, encoding="utf-8")) if args.profile else {}
    import lmstudio as lms
    client = None
    host = None
    try:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                parsed = urlparse(request["base_url"])
                if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                    raise ValueError("counter requires a loopback host")
                if client is None or host != parsed.netloc:
                    if client is not None:
                        client.close()
                    host = parsed.netloc
                    client = lms.Client(api_host=host)
                    client.__enter__()
                handles = [m for m in client.llm.list_loaded()
                           if m.get_info().identifier == request["model"]]
                if len(handles) != 1:
                    raise ValueError("loaded instance unavailable or ambiguous")
                model = handles[0]
                identity = inspect(model)
                qualified = (profile.get("provider_reference_passed") is True
                             and all(profile.get(k) == v for k, v in identity.items())
                             and request["payload"].get("reasoning", "omitted") in profile.get("reasoning_modes", []))
                transform = qualified and profile.get("reasoning_off_transform") == "close_think_block"
                value = formatted(model, request["payload"], transform)
                tokens = model.count_tokens(value)
                allowance = 0 if qualified else 256
                print(json.dumps({
                    "instance_id": request["model"],
                    "loaded_context_length": identity["loaded_context_length"],
                    "count": {
                        "state": "verified_model_compatible" if qualified else "conservative_estimated",
                        "tokens": tokens + allowance,
                        "method": "lmstudio_sdk_qualified_chat_template" if qualified else "lmstudio_sdk_with_unqualified_template_allowance",
                        "template_allowance_tokens": allowance,
                        "confidence": "instance/tokenizer/template-bound provider reference parity" if qualified else "SDK tokenization; REST formatting parity unverified",
                    },
                }), flush=True)
            except Exception:
                print(json.dumps({"error": "SDK count unavailable or identity changed"}), flush=True)
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    main()
