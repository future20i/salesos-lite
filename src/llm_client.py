"""LLM client for AI pipeline — intent grading and customer profile extraction.

Uses OpenAI-compatible API (DeepSeek, OpenAI, etc.).
Configured via environment variables:
  LLM_API_KEY       — API key
  LLM_BASE_URL      — Base URL (default: https://api.deepseek.com/v1)
  LLM_MODEL         — Model name (default: deepseek-chat)
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_KEY = os.getenv("LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")))
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

INTENT_PROMPT = """You are a sales assistant for a foreign trade company. Analyze the following customer message and extract:

1. **intent** — one of: hot (ready to buy, asking for price/quote), warm (showing interest, asking questions), cold (just browsing, initial contact), dormant (no reply, abandoned)
2. **target_price** — mentioned price range or budget (null if not found)
3. **inquired_sku** — product name, model, or SKU the customer is asking about (null if none)
4. **port** — destination port or country mentioned (null if none)
5. **decision_chain** — who is the decision maker? (e.g. "boss", "procurement manager", "self", null if unclear)
6. **summary** — one-sentence summary of the customer's request in Chinese

Respond ONLY with valid JSON. No markdown, no explanation.

Example response:
{"intent":"hot","target_price":"$5-8/kg","inquired_sku":"N95 meltblown fabric","port":"Hamburg, Germany","decision_chain":"procurement manager","summary":"客户询问N95熔喷布FOB上海报价，需要5吨试单"}

Customer message:
{content}"""


async def grade_intent(content: str) -> dict[str, Any]:
    """Call LLM to grade customer intent and extract profile fields.

    Returns a dict with keys: intent, target_price, inquired_sku, port,
    decision_chain, summary.  On failure returns a safe default.
    """
    if not API_KEY:
        logger.warning("No LLM_API_KEY set — using stub (intent=cold)")
        return _stub_result()

    prompt = INTENT_PROMPT.format(content=content[:3000])  # truncate long messages

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a JSON-only API. Always respond with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        content_text = data["choices"][0]["message"]["content"]
        result = _parse_llm_json(content_text)
        logger.info("Intent graded: %s", result.get("intent", "unknown"))
        return result

    except httpx.HTTPError as e:
        logger.error("LLM HTTP error: %s", e)
        return _stub_result()
    except (KeyError, json.JSONDecodeError) as e:
        logger.error("LLM response parse error: %s", e)
        return _stub_result()
    except Exception:
        logger.exception("Unexpected LLM error")
        return _stub_result()


def _parse_llm_json(text: str) -> dict[str, Any]:
    """Robust JSON extraction from LLM output (may have markdown fences)."""
    text = text.strip()
    # Remove markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return json.loads(text)


# ── Reply suggestion ──────────────────────────────────────────────────────

SUGGEST_PROMPT = """You are a sales assistant for a foreign trade company in China. Based on the conversation below, write a natural, professional reply in Chinese. Keep it concise (2-4 sentences), friendly, and focused on moving the sale forward. Include a clear next step or call to action.

Conversation:
{context}

Reply:"""


async def suggest_reply(context: str) -> str:
    """Call LLM to generate a suggested reply based on conversation context.

    Returns the suggested reply text, or a fallback message if unavailable.
    """
    if not API_KEY:
        logger.warning("No LLM_API_KEY set — reply suggestion unavailable")
        return "(AI suggestion unavailable — no API key configured)"

    prompt = SUGGEST_PROMPT.format(context=context[:3000])

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a professional foreign trade sales assistant. Reply in Chinese."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        reply = data["choices"][0]["message"]["content"]
        logger.info("Reply suggestion generated (%d chars)", len(reply))
        return reply

    except httpx.HTTPError as e:
        logger.error("LLM HTTP error during suggest_reply: %s", e)
        return "(AI suggestion unavailable — LLM service error)"
    except (KeyError, json.JSONDecodeError) as e:
        logger.error("LLM response parse error during suggest_reply: %s", e)
        return "(AI suggestion unavailable — response parse error)"
    except Exception:
        logger.exception("Unexpected LLM error during suggest_reply")
        return "(AI suggestion unavailable — unexpected error)"


def _stub_result() -> dict[str, Any]:
    return {
        "intent": "cold",
        "target_price": None,
        "inquired_sku": None,
        "port": None,
        "decision_chain": None,
        "summary": "AI analysis unavailable (no API key configured)",
    }
