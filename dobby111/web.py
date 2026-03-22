import os
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from threading import Lock

# dotenv is optional for running in minimal environments; fallback to no-op if unavailable.
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return None

from flask import Flask, render_template, request, jsonify
from llm_provider import LLMProviderFactory, MockProvider
from config import SYSTEM_PROMPT, get_provider_name
from validation import validate_textile_payload

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')

SESSION_STATE: Dict[str, Dict[str, Any]] = {}
SESSION_LOCK = Lock()


def _normalize_messages(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Keep conversation history, but always enforce backend system prompt as source of truth."""
    safe_messages: List[Dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            safe_messages.append({"role": role, "content": content.strip()})

    return [{"role": "system", "content": SYSTEM_PROMPT}, *safe_messages]


def _get_or_create_session_state(session_id: str) -> Dict[str, Any]:
    with SESSION_LOCK:
        if session_id not in SESSION_STATE:
            SESSION_STATE[session_id] = {
                "user_slots": {},
                "inferred_slots": {},
                "turn_count": 0,
            }
        return SESSION_STATE[session_id]


def _extract_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from model output, including fenced markdown payloads."""
    clean_reply = (raw_text or "").strip()
    clean_reply = re.sub(r'^```json\s*', '', clean_reply)
    clean_reply = re.sub(r'^```\s*', '', clean_reply)
    clean_reply = re.sub(r'\s*```$', '', clean_reply)
    clean_reply = clean_reply.strip()

    json_match = re.search(r'\{[\s\S]*\}', clean_reply)
    if json_match:
        clean_reply = json_match.group()

    try:
        parsed = json.loads(clean_reply)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_structured_payload(payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Perform lightweight schema validation for core production fields."""
    required_top = ["design", "stripe", "colors", "visual", "market", "technical"]
    for key in required_top:
        if key not in payload:
            return False, f"Missing top-level key: {key}"

    design = payload.get("design") or {}
    stripe = payload.get("stripe") or {}
    visual = payload.get("visual") or {}
    market = payload.get("market") or {}
    technical = payload.get("technical") or {}
    colors = payload.get("colors")

    design_required = ["designSize", "designSizeRangeCm", "designStyle", "weave"]
    for key in design_required:
        if key not in design:
            return False, f"Missing design.{key}"

    size_range = design.get("designSizeRangeCm") or {}
    if not (_is_number(size_range.get("min")) and _is_number(size_range.get("max"))):
        return False, "Invalid design.designSizeRangeCm"

    stripe_size = stripe.get("stripeSizeRangeMm") or {}
    stripe_mult = stripe.get("stripeMultiplyRange") or {}
    if not (_is_number(stripe_size.get("min")) and _is_number(stripe_size.get("max"))):
        return False, "Invalid stripe.stripeSizeRangeMm"
    if not (_is_number(stripe_mult.get("min")) and _is_number(stripe_mult.get("max"))):
        return False, "Invalid stripe.stripeMultiplyRange"
    if not isinstance(stripe.get("isSymmetry"), bool):
        return False, "Invalid stripe.isSymmetry"

    if not isinstance(colors, list) or len(colors) == 0:
        return False, "colors must be a non-empty array"
    for color in colors:
        if not isinstance(color, dict):
            return False, "Invalid colors entry"
        if not isinstance(color.get("name"), str) or not _is_number(color.get("percentage")):
            return False, "Invalid color format"

    if not isinstance(visual.get("contrastLevel"), str):
        return False, "Missing visual.contrastLevel"
    if not isinstance(market.get("occasion"), str):
        return False, "Missing market.occasion"

    tech_required = ["yarnCount", "construction", "gsm", "epi", "ppi"]
    for key in tech_required:
        if key not in technical:
            return False, f"Missing technical.{key}"

    return True, None


def _extract_slots_from_user_text(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    user_messages = [
        m.get("content", "") for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)
    ]

    slot_values: Dict[str, Any] = {}

    # Process messages in order so newer user inputs override older ones.
    for content in user_messages:
        if _is_side_question(content):
            # Avoid interpreting explanatory questions (e.g., "What is dobby?")
            # as slot answers.
            continue

        user_text = content.lower()

        if any(k in user_text for k in ["formal", "office", "business", "wedding"]):
            slot_values["occasion"] = "Formal"
        elif "casual" in user_text:
            slot_values["occasion"] = "Casual"
        elif "party" in user_text:
            slot_values["occasion"] = "Party Wear"

        for weave in ["plain", "twill", "oxford", "dobby"]:
            if weave in user_text:
                slot_values["weave"] = weave.capitalize()
                break

        if "fil-a-fil" in user_text:
            slot_values["design_style"] = "Fil-a-Fil"
        elif "gradational" in user_text or "gradient" in user_text:
            slot_values["design_style"] = "Gradational"
        elif "counter" in user_text:
            slot_values["design_style"] = "Counter"
        elif "multicolor" in user_text:
            slot_values["design_style"] = "Multicolor"
        elif "solid" in user_text:
            slot_values["design_style"] = "Solid"
        elif "regular" in user_text or "stripe" in user_text or "check" in user_text:
            slot_values["design_style"] = "Regular"

        extracted_colors = _extract_color_preferences(content)
        if extracted_colors:
            slot_values["color"] = extracted_colors

    return slot_values


def _is_side_question(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False

    if "?" in lowered:
        return True

    question_starters = (
        "what ", "what's ", "whats ", "why ", "how ", "which ", "who ", "when ",
        "where ", "can you ", "could you ", "do you ", "is ", "are ", "tell me"
    )
    return lowered.startswith(question_starters)


def _answer_side_question(text: str) -> str:
    lowered = (text or "").lower()

    if "dobby" in lowered:
        return "Dobby is a weave structure made on a dobby loom that creates small geometric patterns. It gives extra texture and detail compared to a plain weave."
    if "twill" in lowered:
        return "Twill is a weave with a diagonal surface effect. It is generally durable, drapes well, and can feel slightly heavier than plain weave."
    if "oxford" in lowered:
        return "Oxford is a basket-style weave that gives a textured and durable fabric, commonly used for casual and smart-casual shirts."
    if "fil-a-fil" in lowered or "fil a fil" in lowered:
        return "Fil-a-Fil is a fine two-color effect created by alternating single yarns, giving a subtle micro-pattern often used in formal shirting."
    if "warp" in lowered and "weft" in lowered:
        return "Warp yarns run lengthwise, and weft yarns run crosswise. Their interlacing defines the weave and fabric behavior."
    if "warp" in lowered:
        return "Warp refers to the lengthwise yarns held under tension on the loom."
    if "weft" in lowered:
        return "Weft refers to the crosswise yarns inserted through the warp during weaving."

    return "I can explain textile terms while we design. You can ask about dobby, twill, oxford, warp, weft, or fil-a-fil."


def _answer_side_question_with_llm(provider: Any, text: str) -> Optional[str]:
    """Generate natural side-question answers using the active LLM provider."""
    if not provider:
        return None

    try:
        side_messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful textile assistant. "
                    "Answer the user's question in plain natural language in 1-3 sentences. "
                    "Do not output JSON, markdown, lists, or code."
                ),
            },
            {"role": "user", "content": text},
        ]
        answer = (provider.get_response(side_messages) or "").strip()
        if not answer:
            return None

        # Guardrail: if provider returns JSON-style output, use rule-based fallback.
        if answer.startswith("{") or answer.startswith("["):
            return None
        return answer
    except Exception:
        return None


def _extract_color_preferences(text: str) -> List[Dict[str, float]]:
    color_catalog = [
        "navy blue", "light blue", "dark blue", "blue", "white", "black", "red", "green", "grey", "gray",
        "pink", "beige", "brown", "maroon", "yellow", "orange", "purple", "gold", "silver"
    ]

    lowered = text.lower()
    detected: List[str] = []
    for color in color_catalog:
        if re.search(rf"\b{re.escape(color)}\b", lowered):
            detected.append(color)

    # Remove duplicates while preserving order.
    deduped: List[str] = []
    for color in detected:
        if color not in deduped:
            deduped.append(color)

    if not deduped:
        return []

    percentages: Dict[str, float] = {}
    for color in deduped:
        match = re.search(rf"\b{re.escape(color)}\b\s*[:\-]?\s*(\d{{1,3}})\s*%", lowered)
        if match:
            percentages[color] = float(match.group(1))

    if len(percentages) == len(deduped):
        return [
            {"name": _to_display_color(color), "percentage": percentages[color]}
            for color in deduped
        ]

    equal_share = round(100.0 / len(deduped), 2)
    colors_payload = [
        {"name": _to_display_color(color), "percentage": equal_share}
        for color in deduped
    ]

    # Adjust last entry to keep exact total at 100.
    running = sum(item["percentage"] for item in colors_payload[:-1])
    colors_payload[-1]["percentage"] = round(100.0 - running, 2)
    return colors_payload


def _to_display_color(raw: str) -> str:
    return " ".join(part.capitalize() for part in raw.split())


def _apply_user_slots_to_structured(structured: Dict[str, Any], user_slots: Dict[str, Any]) -> Dict[str, Any]:
    """Make user-provided constraints authoritative over model defaults."""
    if not structured:
        return structured

    if user_slots.get("occasion"):
        structured.setdefault("market", {})["occasion"] = user_slots["occasion"]

    if user_slots.get("weave"):
        structured.setdefault("design", {})["weave"] = user_slots["weave"]

    if user_slots.get("design_style"):
        structured.setdefault("design", {})["designStyle"] = user_slots["design_style"]

    if user_slots.get("color"):
        # Color slot stores [{name, percentage}] from user input extraction.
        structured["colors"] = user_slots["color"]

    return structured


def _extract_slots_from_structured(payload: Dict[str, Any]) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    try:
        if payload.get("market", {}).get("occasion"):
            slots["occasion"] = payload["market"]["occasion"]
        if payload.get("design", {}).get("weave"):
            slots["weave"] = payload["design"]["weave"]
        if payload.get("design", {}).get("designStyle"):
            slots["design_style"] = payload["design"]["designStyle"]
        if payload.get("colors"):
            slots["color"] = [c.get("name") for c in payload["colors"] if isinstance(c, dict) and c.get("name")]
    except Exception:
        return slots
    return slots


def _missing_critical_slots(collected_slots: Dict[str, Any]) -> List[str]:
    critical = ["occasion", "color", "weave", "design_style"]
    return [slot for slot in critical if not collected_slots.get(slot)]


def _effective_slots_for_missing(user_slots: Dict[str, Any], structured_reply: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Use user slots first; if a slot exists in structured output, treat it as resolved for follow-up flow."""
    effective = dict(user_slots or {})
    if structured_reply:
        inferred = _extract_slots_from_structured(structured_reply)
        for key, value in inferred.items():
            if not effective.get(key) and value:
                effective[key] = value
    return effective


def _infer_missing_slots(messages: List[Dict[str, str]]) -> List[str]:
    """Infer missing critical inputs from user language, one slot at a time."""
    user_text = " ".join(
        m.get("content", "") for m in messages if m.get("role") == "user"
    ).lower()

    checks = [
        ("occasion", ["formal", "casual", "party", "office", "business", "wedding"]),
        ("color", ["blue", "white", "black", "red", "green", "grey", "gray", "navy", "pink", "beige", "brown"]),
        ("weave", ["plain", "twill", "oxford", "dobby"]),
        ("design_style", ["regular", "gradational", "fil-a-fil", "counter", "multicolor", "solid", "stripe", "check"]),
    ]

    missing: List[str] = []
    for slot, keywords in checks:
        if not any(k in user_text for k in keywords):
            missing.append(slot)

    return missing


def _follow_up_question(slot_name: str) -> str:
    prompts = {
        "occasion": "Which occasion is this design for: Formal, Casual, or Party Wear?",
        "color": "What colors would you like for the shirt, and if possible what percentage split should each color have?",
        "weave": "Which weave do you prefer for this design: Plain, Twill, Oxford, or Dobby?",
        "design_style": "Which style direction do you want: Regular, Solid, Gradational, Fil-a-Fil, Counter, or Multicolor?",
    }
    return prompts.get(slot_name, "Could you clarify a bit more about the design so I can complete the parameters?")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'provider': get_provider_name()})


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json() or {}
    session_id = str(data.get('session_id') or 'default')
    messages = _normalize_messages(data.get('messages', []))
    session_state = _get_or_create_session_state(session_id)
    session_state['turn_count'] = int(session_state.get('turn_count', 0)) + 1

    user_slots = _extract_slots_from_user_text(messages)
    if user_slots:
        session_state['user_slots'].update(user_slots)

    user_collected_slots = session_state.get('user_slots', {})
    missing_slots = _missing_critical_slots(user_collected_slots)

    latest_user_text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            latest_user_text = m.get("content", "")
            break

    provider_name = get_provider_name()
    try:
        provider = LLMProviderFactory.get_provider(provider_name)
    except Exception as inner_exc:
        return jsonify({'error': str(inner_exc)}), 500

    # If user asks an explanatory side question while slots are still missing,
    # answer it directly and keep the guided flow intact.
    if missing_slots and _is_side_question(latest_user_text):
        side_answer = _answer_side_question_with_llm(provider, latest_user_text) or _answer_side_question(latest_user_text)
        reminder = _follow_up_question(missing_slots[0])
        return jsonify({
            'reply': f"{side_answer} {reminder}",
            'structured': None,
            'next_question': None,
            'missing_slots': missing_slots,
            'validation_error': None,
            'session_id': session_id,
            'turn_count': session_state['turn_count'],
        })

    try:
        reply = provider.get_response(messages)
    except Exception as inner_exc:
        print(f"Provider error [{provider_name}]: {inner_exc}")

        # Fallback to mock provider when API failure (quota, key, invalid model, etc.)
        mock = MockProvider()
        reply = mock.get_response(messages)

    # Parse and validate structured JSON when possible.
    structured_reply = _extract_json_object(reply)
    validation_error = None

    if structured_reply is not None:
        pydantic_model, pydantic_error = validate_textile_payload(structured_reply)
        if pydantic_model is None:
            validation_error = pydantic_error
            structured_reply = None
        else:
            structured_reply = pydantic_model.model_dump()

    if structured_reply is not None:
        is_valid, validation_error = _validate_structured_payload(structured_reply)
        if not is_valid:
            print(f"Structured payload validation failed: {validation_error}")
            structured_reply = None
        else:
            structured_reply = _apply_user_slots_to_structured(structured_reply, session_state.get('user_slots', {}))
            session_state['inferred_slots'].update(_extract_slots_from_structured(structured_reply))

    # Follow-up flow must be driven by what the user has explicitly provided,
    # not by inferred/default values generated by the model response.
    user_collected_slots = session_state.get('user_slots', {})
    missing_slots = _missing_critical_slots(user_collected_slots)
    next_question = _follow_up_question(missing_slots[0]) if missing_slots else None

    # Do not send structured payload until mandatory slots are collected.
    structured_for_client = None if missing_slots else structured_reply

    return jsonify({
        'reply': reply,
        'structured': structured_for_client,
        'next_question': next_question,
        'missing_slots': missing_slots,
        'validation_error': validation_error,
        'session_id': session_id,
        'turn_count': session_state['turn_count'],
    })


if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '127.0.0.1')
    port = int(os.getenv('FLASK_PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG', '1') == '1'
    app.run(host=host, port=port, debug=debug)
