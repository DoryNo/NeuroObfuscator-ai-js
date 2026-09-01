from __future__ import annotations

import glob
import json
import math
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import call_engine_batch
from inference import NeuroObfuscatorInference, generate_fallback_plan, validate_plan_schema

ORDER = ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]
TOKEN_RE = re.compile(r"[A-Za-z_$][\w$]*|\d+|[^\s]")

# --- Model (lazy; falls back to heuristic plans when no GGUF is available) ---

_STATE: dict = {"engine": None, "status": "not initialized"}


def _find_gguf() -> str | None:
    env = os.environ.get("NEURO_GGUF")
    if env and Path(env).exists():
        return env
    for pattern in ("models/*.gguf", "models/**/*.gguf"):
        hits = sorted(glob.glob(str(ROOT / pattern)), key=os.path.getsize, reverse=True)
        if hits:
            return hits[0]
    return None


def get_engine() -> tuple[NeuroObfuscatorInference, str]:
    if _STATE["engine"] is not None:
        return _STATE["engine"], _STATE["status"]
    gguf = _find_gguf()
    if gguf is None:
        _STATE["engine"] = NeuroObfuscatorInference(generate_fn=None)
        _STATE["status"] = "heuristic fallback mode (no GGUF found: set NEURO_GGUF env or put a *.gguf into models/)"
        return _STATE["engine"], _STATE["status"]
    from llama_cpp import Llama

    llm = Llama(model_path=gguf, n_gpu_layers=-1, n_ctx=4096, verbose=False)

    def generate(prompt: str) -> str:
        out = llm(prompt, max_tokens=256, temperature=0.0, stop=["<|im_end|>", "</s>"], echo=False)
        return out["choices"][0]["text"]

    _STATE["engine"] = NeuroObfuscatorInference(generate_fn=generate)
    _STATE["status"] = f"model: {Path(gguf).name}"
    return _STATE["engine"], _STATE["status"]


# --- Helpers ---

def shape_matches(plan: dict, target: str | None) -> bool | None:
    if target is None:
        return None
    order = set(plan.get("order", []))
    if target == "light":
        return order <= {"rename", "dead_code"}
    if target == "medium":
        return "opaque_predicates" not in order and bool(order - {"rename", "dead_code"})
    if target == "heavy":
        return "opaque_predicates" in order
    return None


def entropy(code: str) -> float:
    tokens = TOKEN_RE.findall(code)
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def compute_metrics(code: str, obfuscated: str, features: dict, after_features: dict,
                    validation: dict, plan: dict, target: str | None) -> str:
    size_before = max(len(code.encode()), 1)
    size_after = len(obfuscated.encode())
    lines = [
        f"Entropy:     {entropy(code):.2f} -> {entropy(obfuscated):.2f} (+{entropy(obfuscated) - entropy(code):.2f})",
        f"Complexity:  {features.get('cyclomatic_complexity', '?')} -> {after_features.get('cyclomatic_complexity', '?')}",
        f"Size:        {size_before} B -> {size_after} B ({size_after / size_before:.1f}x)",
        f"Validation:  {'PASSED' if validation.get('tests_passed') else 'FAILED'} "
        f"({validation.get('cases_passed', 0)} differential cases)",
    ]
    if validation.get("reason") and not validation.get("tests_passed"):
        lines.append(f"Fail reason: {validation['reason']}")
    shape = shape_matches(plan, target)
    lines.append(f"Intensity:   target={target or 'auto'} | plan={plan.get('intensity')} | "
                 f"shape={'OK' if shape else 'MISMATCH'}")
    lines.append(f"Transforms:  {' -> '.join(plan.get('order', [])) or 'none'}")
    return "\n".join(lines)


def apply_and_validate(code: str, plan: dict) -> tuple[str, dict, dict, dict]:
    feat_resp = call_engine_batch([{"operation": "extract_features", "code": code}])
    if not feat_resp or not feat_resp[0].get("ok"):
        return "", {"tests_passed": False, "reason": "parse_error"}, {}, {}
    features = feat_resp[0]["value"]["features"]

    apply_resp = call_engine_batch([{"operation": "apply", "code": code, "plan": plan}])
    if not apply_resp or not apply_resp[0].get("ok"):
        error = apply_resp[0].get("error", "unknown") if apply_resp else "no response"
        return "", {"tests_passed": False, "reason": f"apply_error: {error}"}, features, {}

    obfuscated = apply_resp[0]["value"]["code"]

    val_resp = call_engine_batch([{"operation": "validate",
                                   "original_code": code, "obfuscated_code": obfuscated}])
    validation = (val_resp[0]["value"] if val_resp and val_resp[0].get("ok")
                  else {"tests_passed": False, "reason": "validation_error"})

    feat_after = call_engine_batch([{"operation": "extract_features", "code": obfuscated}])
    after_features = feat_after[0]["value"]["features"] if feat_after and feat_after[0].get("ok") else {}
    return obfuscated, validation, features, after_features


# --- Neural tab handler ---

def neural_obfuscate(code: str, intensity: str, seed: int):
    if not code.strip():
        return "", "{}", "", "", _STATE["status"]
    engine, status = get_engine()

    feat_resp = call_engine_batch([{"operation": "extract_features", "code": code}])
    if not feat_resp or not feat_resp[0].get("ok"):
        return "", "{}", "Error: failed to parse the JavaScript input", "", status
    features = feat_resp[0]["value"]["features"]

    target = None if intensity == "auto" else intensity
    if target is None:
        cc = features.get("cyclomatic_complexity", 1)
        target = "light" if cc <= 2 else "medium" if cc <= 5 else "heavy"

    if seed and int(seed) > 0:
        plan = engine.infer_plan(code, seed=int(seed), target_intensity=target)
    else:
        plan = engine.infer_plan(code, target_intensity=target)

    if not validate_plan_schema(plan):
        return "", "{}", "Error: model produced an invalid plan (fallback exhausted)", "", status

    obfuscated, validation, features, after_features = apply_and_validate(code, plan)
    if not obfuscated:
        return "", json.dumps(plan, indent=2), f"Error: {validation.get('reason', 'unknown')}", "", status

    metrics = compute_metrics(code, obfuscated, features, after_features, validation, plan, target)
    return obfuscated, json.dumps(plan, indent=2), metrics, json.dumps(features, indent=2), status


# --- Plan JSON tab handler ---

def plan_json_obfuscate(code: str, plan_json: str):
    if not code.strip():
        return "", "", "", ""
    try:
        plan = json.loads(plan_json)
    except (json.JSONDecodeError, TypeError) as error:
        return "", f"Invalid JSON: {error}", "", ""
    if not validate_plan_schema(plan):
        return "", "Invalid plan: schema/order/transforms do not match the engine contract", "", ""
    # The model does not generate a seed (runtime injects it); same rule here.
    if not isinstance(plan.get("seed"), int) or isinstance(plan["seed"], bool) \
            or not 0 <= plan["seed"] <= 0xFFFFFFFF:
        plan["seed"] = 42

    obfuscated, validation, features, after_features = apply_and_validate(code, plan)
    if not obfuscated:
        return "", f"Error: {validation.get('reason', 'unknown')}", "", ""

    metrics = compute_metrics(code, obfuscated, features, after_features, validation, plan,
                              plan.get("intensity"))
    return obfuscated, metrics, json.dumps(features, indent=2), ""


# --- Manual tab handler ---

def manual_obfuscate(code: str, intensity: str, use_rename: bool, use_string: bool,
                     string_method: str, use_operator: bool, use_dead: bool, use_opaque: bool,
                     dead_count: int, opaque_count: int, operator_rate: float, seed_value: int):
    if not code.strip():
        return "", "{}", "", ""

    seed_value = int(seed_value) or random.randint(1, 0xFFFFFFFF)
    transforms = {
        "rename": {"enabled": use_rename, "keep": []},
        "string_encode": {"enabled": use_string, "method": string_method, "min_length": 2},
        "operator_sub": {"enabled": use_operator, "rate": float(operator_rate)},
        "dead_code": {"enabled": use_dead, "count": int(dead_count)},
        "opaque_predicates": {"enabled": use_opaque, "count": int(opaque_count)},
    }
    order = [name for name in ORDER if transforms[name]["enabled"]]
    if not order:
        return code, "{}", "No transforms enabled", ""

    plan = {"seed": seed_value, "intensity": intensity, "transforms": transforms, "order": order}

    feat_resp = call_engine_batch([{"operation": "extract_features", "code": code}])
    features = feat_resp[0]["value"]["features"] if feat_resp and feat_resp[0].get("ok") else {}

    obfuscated, validation, _, after_features = apply_and_validate(code, plan)
    if not obfuscated:
        return "", json.dumps(plan, indent=2), f"Error: {validation.get('reason', 'unknown')}", ""

    metrics = compute_metrics(code, obfuscated, features, after_features, validation, plan, intensity)
    return obfuscated, json.dumps(plan, indent=2), metrics, json.dumps(features, indent=2)


# --- Validate-only handler ---

def validate_only(original_code: str, obfuscated_code: str):
    if not original_code.strip() or not obfuscated_code.strip():
        return "Validation error: both code panels are required"
    try:
        response = call_engine_batch([{
            "operation": "validate",
            "original_code": original_code,
            "obfuscated_code": obfuscated_code,
        }])[0]
    except Exception as error:
        return f"Validation error: engine unavailable: {error}"
    if not response.get("ok"):
        return f"Validation error: {response.get('error', 'unknown engine error')}"
    result = response["value"]
    status = "PASSED" if result.get("tests_passed") else "FAILED"
    return f"{status}: {result.get('cases_passed', 0)} differential cases; reason: {result.get('reason') or 'none'}"


EXAMPLE_CODE = """function calculateDiscount(price, tier) {
  let discount = 0;
  if (tier === "gold") {
    discount = price * 0.2;
  } else if (tier === "silver") {
    discount = price * 0.1;
  } else {
    discount = price * 0.05;
  }
  const total = price - discount;
  return Math.round(total * 100) / 100;
}"""

EXAMPLE_PLAN = """{
  "intensity": "heavy",
  "transforms": {
    "rename": {"enabled": true, "keep": []},
    "string_encode": {"enabled": true, "method": "charcode_array", "min_length": 2},
    "operator_sub": {"enabled": true, "rate": 0.7},
    "dead_code": {"enabled": true, "count": 3},
    "opaque_predicates": {"enabled": true, "count": 2}
  },
  "order": ["rename", "string_encode", "operator_sub", "dead_code", "opaque_predicates"]
}"""


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="NeuroObfuscator") as demo:
        gr.Markdown(
            "# NeuroObfuscator\n"
            "Adaptive JavaScript obfuscation: a fine-tuned Qwen2.5-Coder-7B generates an "
            "obfuscation plan (JSON), a deterministic Babel engine applies it, and every "
            "result is proven behavior-preserving with a differential test."
        )
        engine_status = gr.Textbox(label="Engine status", value=_STATE["status"], interactive=False)

        with gr.Tab("Neural Mode"):
            gr.Markdown(
                "The model plans the obfuscation from your code + AST features. "
                "**Target intensity** controls the plan shape: `light` = rename + dead_code only, "
                "`medium` = no opaque predicates, `heavy` = all transforms including opaque predicates."
            )
            with gr.Row():
                with gr.Column():
                    neural_input = gr.Code(label="Input JavaScript", language="javascript",
                                           value=EXAMPLE_CODE, lines=14)
                    neural_intensity = gr.Radio(label="Target intensity",
                                                choices=["auto", "light", "medium", "heavy"],
                                                value="medium")
                    neural_seed = gr.Number(label="Seed (0 = random)", value=0, precision=0)
                    neural_btn = gr.Button("Obfuscate", variant="primary")
                with gr.Column():
                    neural_output = gr.Code(label="Obfuscated Code", language="javascript", lines=14)
                    neural_metrics = gr.Textbox(label="Metrics & Validation", lines=7)
            with gr.Row():
                neural_plan = gr.Code(label="Generated Plan", language="json", lines=10)
                neural_features = gr.Code(label="AST Features", language="json", lines=10)
            neural_validate_btn = gr.Button("Validate Before/After Again")
            neural_validate_result = gr.Textbox(label="Independent Validation", lines=2)

            neural_btn.click(
                fn=neural_obfuscate,
                inputs=[neural_input, neural_intensity, neural_seed],
                outputs=[neural_output, neural_plan, neural_metrics, neural_features, engine_status],
            )
            neural_validate_btn.click(
                fn=validate_only,
                inputs=[neural_input, neural_output],
                outputs=[neural_validate_result],
            )

        with gr.Tab("Plan JSON"):
            gr.Markdown("Apply and validate a plan JSON produced by the model or written by hand.")
            with gr.Row():
                with gr.Column():
                    plan_input = gr.Code(label="Input JavaScript", language="javascript",
                                         value=EXAMPLE_CODE, lines=14)
                    plan_json_input = gr.Code(label="Plan JSON", language="json",
                                              value=EXAMPLE_PLAN, lines=14)
                    plan_btn = gr.Button("Apply Plan", variant="primary")
                with gr.Column():
                    plan_output = gr.Code(label="Obfuscated Code", language="javascript", lines=14)
                    plan_metrics = gr.Textbox(label="Metrics & Validation", lines=7)
            plan_features = gr.Code(label="AST Features", language="json", lines=8)
            plan_btn.click(
                fn=plan_json_obfuscate,
                inputs=[plan_input, plan_json_input],
                outputs=[plan_output, plan_metrics, plan_features],
            )

        with gr.Tab("Manual Mode"):
            gr.Markdown("Configure every transform by hand.")
            with gr.Row():
                with gr.Column():
                    manual_input = gr.Code(label="Input JavaScript", language="javascript",
                                           value=EXAMPLE_CODE, lines=12)
                    with gr.Row():
                        use_rename = gr.Checkbox(label="rename", value=True)
                        use_string = gr.Checkbox(label="string_encode", value=True)
                        use_operator = gr.Checkbox(label="operator_sub", value=False)
                        use_dead = gr.Checkbox(label="dead_code", value=True)
                        use_opaque = gr.Checkbox(label="opaque_predicates", value=True)
                    with gr.Row():
                        string_method = gr.Dropdown(label="string method",
                                                    choices=["charcode_array", "charcode_concat",
                                                             "hex_escape", "unicode_escape"],
                                                    value="charcode_array")
                        dead_count = gr.Slider(label="dead_code count", minimum=1, maximum=5,
                                               step=1, value=2)
                        opaque_count = gr.Slider(label="opaque count", minimum=1, maximum=3,
                                                 step=1, value=2)
                    with gr.Row():
                        operator_rate = gr.Slider(label="operator_sub rate", minimum=0.0,
                                                  maximum=1.0, step=0.1, value=0.7)
                        seed_input = gr.Number(label="Seed (0 = random)", value=0, precision=0)
                        manual_intensity = gr.Radio(label="Plan intensity label",
                                                    choices=["light", "medium", "heavy"],
                                                    value="medium")
                    manual_btn = gr.Button("Obfuscate", variant="primary")
                with gr.Column():
                    manual_output = gr.Code(label="Obfuscated Code", language="javascript", lines=12)
            with gr.Row():
                manual_plan = gr.Code(label="Plan JSON", language="json", lines=10)
                manual_features = gr.Code(label="AST Features", language="json", lines=10)
            manual_metrics = gr.Textbox(label="Metrics & Validation", lines=7)

            manual_btn.click(
                fn=manual_obfuscate,
                inputs=[manual_input, manual_intensity, use_rename, use_string, string_method,
                        use_operator, use_dead, use_opaque, dead_count, opaque_count,
                        operator_rate, seed_input],
                outputs=[manual_output, manual_plan, manual_metrics, manual_features],
            )

        with gr.Tab("About"):
            gr.Markdown(
                "## Evaluation results (v7.1, 750 held-out test functions)\n"
                "| Metric | Result |\n|---|---|\n"
                "| JSON parse / schema valid | 100% / 100% |\n"
                "| Intensity obedience (field / plan shape) | 100% / 100% |\n"
                "| Light purity | 100% |\n"
                "| Semantic pass (differential, engine) | 100% |\n"
                "| Unique transform orders / top non-light share | 10 / 19.0% |\n\n"
                "Model: Qwen2.5-Coder-7B-Instruct, QLoRA r=32 alpha=64, 3 epochs, "
                "GGUF q8_0. Dataset: 7,500 conditional plans (900 real + 6,600 synthetic "
                "functions), 22 transform orders, zero label contradictions.\n\n"
                "### Security note\n"
                "Semantic validation runs untrusted JavaScript in Node `vm` with a timeout. "
                "This is **not** a security boundary: run the demo only with trusted input, "
                "or inside an isolated container."
            )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.queue()
    demo.launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft())
