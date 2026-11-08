"""Qualify an already loaded writer against SDK templates and real REST usage."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time
import urllib.request
import sys

sys.path.insert(0, str(Path(__file__).parent))
from writer_sdk_counter import inspect, formatted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base", default="http://127.0.0.1:1234")
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    import lmstudio as lms
    fixture = Path(__file__).parents[2] / "tests/fixtures/context_r4.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    samples = []
    with lms.Client(api_host=args.base.split("://", 1)[-1]) as client:
        handles = [m for m in client.llm.list_loaded() if m.get_info().identifier == args.model]
        assert len(handles) == 1, "select exactly one already loaded model"
        model = handles[0]
        profile = inspect(model)
        model_key = profile["model_key"]
        probe_payload = {"system_prompt": "test", "input": "test", "reasoning": "off"}
        transform = formatted(model, probe_payload).endswith("<think>\n")
        for case in cases:
            for reasoning in ("off", "on", "omitted"):
                payload = {"model": args.model, "system_prompt": case["system"],
                           "input": case["input"] * case.get("repeat", 1),
                           "max_output_tokens": 1, "stream": False, "temperature": 0}
                if reasoning != "omitted":
                    payload["reasoning"] = reasoning
                start = time.perf_counter()
                raw_sdk = model.count_tokens(formatted(model, payload))
                compatible = model.count_tokens(formatted(model, payload, transform))
                sdk_ms = (time.perf_counter() - start) * 1000
                req = urllib.request.Request(args.base + "/api/v1/chat", json.dumps(payload).encode(), {"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.load(response)
                actual = result["stats"]["input_tokens"]
                upper = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) + 256
                samples.append({"id": case["id"], "reasoning": reasoning, "sdk_raw": raw_sdk,
                                "compatible_count": compatible, "provider_input_tokens": actual,
                                "native_byte_estimate": upper, "sdk_ms": sdk_ms,
                                "verified_match": compatible == actual, "estimate_safe": upper >= actual})
        assert all(s["estimate_safe"] for s in samples), "conservative calibration failed"
        profile.update({"provider_reference_passed": all(s["verified_match"] for s in samples),
                        "reasoning_modes": ["off", "on", "omitted"],
                        "reasoning_off_transform": "close_think_block" if transform else "none",
                        "sdk_version": importlib.metadata.version("lmstudio")})
        report = {"schema": "arline.writer-token-reference.v1", "model_key": model_key,
                  "profile": profile, "samples": samples,
                  "limitations": "One loaded tokenizer/template instance; profile invalidates after reload, resize or probe change. Does not qualify images or arbitrary custom templates."}
        with open(args.out, "x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        with open(args.profile, "x", encoding="utf-8") as output:
            json.dump(profile, output, indent=2)
        print(json.dumps({"model": model_key, "samples": len(samples), "verified_parity": profile["provider_reference_passed"]}))


if __name__ == "__main__":
    main()
