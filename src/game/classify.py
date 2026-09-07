"""Per-transaction classification (category + money-type) via Haiku.

Card-agnostic means a churned card can carry anything, so every transaction
needs a money-type: only Variable enters the game; Fixed (rent/utilities/
insurance/subscriptions) and Sinking (travel/gifts/medical) are excluded. Rules
hit first (deterministic, no API); novel merchants go to Haiku; low confidence
goes to the Discord ask-queue rather than being guessed.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
import re

import aiohttp

from src.game.core import MONEY_TYPES
from src.game.simplefin import Txn

CATEGORIES = ["Dining", "Groceries", "Transport", "Projects",
              "Travel", "Shopping", "Entertainment", "Bills", "Other"]
CONF_THRESHOLD = 0.80
MODEL = "claude-haiku-4-5-20251001"


@dataclass
class Classification:
    txn: Txn
    category: str
    money_type: str        # Variable | Fixed | Sinking
    confidence: float

    @property
    def needs_review(self) -> bool:
        return self.confidence < CONF_THRESHOLD


def normalize(desc: str) -> str:
    s = re.sub(r"\b\d[\d\-\*# ]{2,}\b", " ", desc.upper())
    s = re.sub(r"[^A-Z& ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_SYS = (
    "You classify a person's credit-card transactions for a discretionary-spending game.\n"
    "For each transaction return TWO labels, strict JSON only, no prose, no fences:\n"
    f"category — one of: {', '.join(CATEGORIES)}.\n"
    "money_type — one of:\n"
    "  Variable — daily discretionary choices (dining, shopping, entertainment, groceries, rideshare). These COUNT in the game.\n"
    "  Fixed    — recurring obligations you don't decide daily: rent, utilities, phone/internet, insurance, streaming/subscriptions, gym, loan/card autopay.\n"
    "  Sinking  — lumpy planned draws: flights, hotels, travel, gifts, medical, big one-off purchases.\n"
    "confidence — 0..1 that BOTH labels are right. Be honest; unfamiliar or ambiguous merchants get low confidence.\n"
    'Return: {"results":[{"id":"<id>","category":"...","money_type":"...","confidence":0.0}]}'
)


def parse_response(text: str, by_id: dict[str, Txn]) -> list[Classification]:
    """Pure: model text -> Classifications (fences stripped, defaults on miss)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        results = {r["id"]: r for r in json.loads(text).get("results", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        results = {}                               # bad/truncated -> whole batch to review
    out = []
    for tid, txn in by_id.items():
        r = results.get(tid)
        if not r or r.get("money_type") not in MONEY_TYPES:
            out.append(Classification(txn, "Other", "Variable", 0.0))  # -> review
        else:
            cat = r["category"] if r.get("category") in CATEGORIES else "Other"
            out.append(Classification(txn, cat, r["money_type"],
                                      float(r.get("confidence", 0.0))))
    return out


async def classify(txns: list[Txn], rules: dict[str, dict]) -> list[Classification]:
    """rules: normalized_merchant -> {'category','money_type'}. Returns all txns."""
    out, novel = [], []
    for t in txns:
        rule = rules.get(normalize(t.description))
        if rule:
            out.append(Classification(t, rule["category"], rule["money_type"], 1.0))
        else:
            novel.append(t)

    for i in range(0, len(novel), 20):             # batch of 20 keeps JSON under max_tokens
        batch = {t.simplefin_id: t for t in novel[i:i + 20]}
        out += parse_response(await _call(batch), batch)
    return out


async def _call(by_id: dict[str, Txn]) -> str:
    payload = json.dumps([{"id": t.simplefin_id, "merchant": t.description,
                           "amount": f"{t.spend_cents/100:.2f}"} for t in by_id.values()])
    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                     "anthropic-version": "2023-06-01"},
            json={"model": MODEL, "max_tokens": 4096,
                  "system": [{"type": "text", "text": _SYS,
                              "cache_control": {"type": "ephemeral"}}],
                  "messages": [{"role": "user", "content": payload}]},
            timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            return (await resp.json())["content"][0]["text"]
