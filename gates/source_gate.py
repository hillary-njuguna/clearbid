"""
Gate 3: Source / Seller Reputation Gate (μ-Node)
=================================================
Deterministic seller trustworthiness check. Scores sellers based on
observable signals — account age proxies, listing history patterns,
red-flag language, and platform-specific reputation markers.

This gate runs AFTER identity (Gate 2) confirms a genuine sale listing.
It does NOT call external APIs — it's a heuristic scorer based on the
data present in the listing itself.

Scoring bands:
    0.0 – 0.30  →  VETO   (HIGH_RISK)
    0.31 – 0.59 →  VETO   (CAUTION)
    0.60 – 1.0  →  PASS

Status: 🔨 BUILDING
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class SourceVetoCode(Enum):
    PASS = "PASS"
    HIGH_RISK = "HIGH_RISK"
    CAUTION = "CAUTION"
    MISSING_SELLER_ID = "MISSING_SELLER_ID"


@dataclass
class SourceResult:
    """Immutable result from the source gate."""
    verdict: SourceVetoCode
    trust_score: float = 0.0
    signals_positive: List[str] = field(default_factory=list)
    signals_negative: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == SourceVetoCode.PASS


# ── Red-flag patterns ──
_RED_FLAGS = [
    (re.compile(r'\b(?:wire\s*transfer|western\s*union|moneygram)\b', re.IGNORECASE),
     "Payment via irreversible wire transfer", -0.25),
    (re.compile(r'\b(?:no\s*refund|all\s*sales?\s*final|as[\s-]?is)\b', re.IGNORECASE),
     "No refund / as-is disclaimer", -0.10),
    (re.compile(r'\b(?:act\s*fast|limited\s*time|won\'?t\s*last|going\s*quick)\b', re.IGNORECASE),
     "Urgency pressure language", -0.15),
    (re.compile(r'\b(?:too\s*good|unbelievable|incredible\s*deal|steal)\b', re.IGNORECASE),
     "Hype language (too good to be true)", -0.15),
    (re.compile(r'\b(?:send\s*money\s*first|pay\s*upfront|deposit\s*required)\b', re.IGNORECASE),
     "Upfront payment demand", -0.20),
    (re.compile(r'\b(?:no\s*questions?\s*asked|don\'?t\s*ask)\b', re.IGNORECASE),
     "Suspicious secrecy language", -0.20),
    (re.compile(r'\b(?:stolen|hot|fell\s*off\s*(?:a\s*)?truck)\b', re.IGNORECASE),
     "Possible stolen goods language", -0.30),
]

# ── Trust-positive patterns ──
_TRUST_SIGNALS = [
    (re.compile(r'\b(?:compression\s*test|leak[\s-]?down|dyno|tested)\b', re.IGNORECASE),
     "Technical verification mentioned", +0.10),
    (re.compile(r'\b(?:video|photos?|pics?|images?|documented)\b', re.IGNORECASE),
     "Visual evidence available", +0.08),
    (re.compile(r'\b(?:receipt|invoice|paperwork|documentation|title|cert)\b', re.IGNORECASE),
     "Documentation / paperwork available", +0.12),
    (re.compile(r'\b(?:PayPal|escrow|buyer\s*protection)\b', re.IGNORECASE),
     "Buyer-protected payment method", +0.10),
    (re.compile(r'\b(?:warranty|guarantee|return)\b', re.IGNORECASE),
     "Warranty or return policy", +0.10),
    (re.compile(r'\b(?:years?\s*(?:in\s*business|experience|selling)|established|since\s*\d{4})\b', re.IGNORECASE),
     "Established seller signals", +0.12),
    (re.compile(r'\b(?:feedback|reviews?|rated|reputation|trusted)\b', re.IGNORECASE),
     "Reputation references", +0.08),
]

# ── Platform reputation baselines ──
_PLATFORM_BASELINES = {
    "telegram": 0.45,      # Unregulated, anonymous — start cautious
    "whatsapp": 0.45,
    "facebook": 0.55,      # Some accountability via profiles
    "ebay": 0.65,          # Buyer protection built in
    "yahoo_auctions": 0.60,
    "gumtree": 0.50,
    "craigslist": 0.40,
    "upwork": 0.60,
    "linkedin": 0.65,
    "default": 0.50,
}

# ── Seller ID quality scoring ──
def _score_seller_id(seller_id: str) -> tuple:
    """Score seller ID quality. Returns (score_delta, signal_text)."""
    if not seller_id or not seller_id.strip():
        return (-0.15, "No seller ID provided")

    s = seller_id.strip()

    # Positive: recognisable handle format
    if re.match(r'^@[\w]{3,}', s):
        return (+0.05, f"Identifiable handle: {s}")

    # Neutral: generic or short
    if len(s) < 4:
        return (-0.05, f"Very short seller ID: {s}")

    return (0.0, f"Seller ID present: {s}")


def source_gate(
    description: str,
    seller_id: str = "",
    platform: str = "telegram",
    location: str = "",
    min_trust: float = 0.60
) -> SourceResult:
    """
    Gate 3: Source / seller reputation check.

    Scores the seller based on observable signals in the listing text,
    seller ID quality, and platform baseline trust.

    Args:
        description: Full listing text
        seller_id: Seller's handle / ID
        platform: Source platform name
        location: Seller's stated location
        min_trust: Minimum trust score to pass (default 0.60)

    Returns:
        SourceResult with verdict, trust_score, and signal breakdown
    """
    if not seller_id or not seller_id.strip():
        return SourceResult(
            verdict=SourceVetoCode.MISSING_SELLER_ID,
            trust_score=0.0,
            signals_negative=["No seller identification provided"],
            reason="Cannot evaluate source without a seller ID. "
                   "Anonymous listings are automatically flagged."
        )

    positives = []
    negatives = []

    # Start with platform baseline
    platform_key = platform.lower().replace(" ", "_")
    base_score = _PLATFORM_BASELINES.get(platform_key, _PLATFORM_BASELINES["default"])
    positives.append(f"Platform baseline ({platform}): {base_score:.2f}")

    score = base_score

    # Score seller ID
    id_delta, id_signal = _score_seller_id(seller_id)
    score += id_delta
    (positives if id_delta >= 0 else negatives).append(id_signal)

    # Scan for red flags
    for pattern, label, delta in _RED_FLAGS:
        if pattern.search(description):
            score += delta
            negatives.append(f"{label} ({delta:+.2f})")

    # Scan for trust signals
    for pattern, label, delta in _TRUST_SIGNALS:
        if pattern.search(description):
            score += delta
            positives.append(f"{label} ({delta:+.2f})")

    # Location bonus — stating a specific location adds transparency
    if location and len(location) > 3:
        score += 0.05
        positives.append(f"Location disclosed: {location} (+0.05)")

    # Clamp score 0-1
    score = max(0.0, min(1.0, score))

    # Determine verdict
    if score >= min_trust:
        verdict = SourceVetoCode.PASS
        reason = (f"Seller trust score {score:.2f} meets threshold {min_trust:.2f}. "
                  f"{len(positives)} positive signals, {len(negatives)} risk flags.")
    elif score >= 0.30:
        verdict = SourceVetoCode.CAUTION
        reason = (f"Seller trust score {score:.2f} below threshold {min_trust:.2f}. "
                  f"Elevated risk — proceed only with buyer protection.")
    else:
        verdict = SourceVetoCode.HIGH_RISK
        reason = (f"Seller trust score {score:.2f} critically low. "
                  f"Multiple risk indicators detected. Do not proceed.")

    return SourceResult(
        verdict=verdict,
        trust_score=round(score, 2),
        signals_positive=positives,
        signals_negative=negatives,
        reason=reason
    )


if __name__ == "__main__":
    # ── Smoke tests ──
    tests = [
        {
            "name": "Trusted seller with documentation",
            "description": "Selling 2JZ-GTE, compression tested, dyno sheet available. "
                          "Photos and video of running engine. PayPal accepted. "
                          "10 years in business. Feedback available on request.",
            "seller_id": "@jdm_tokyo_exports",
            "platform": "Telegram",
            "location": "Yokohama, Japan",
            "expect_pass": True,
        },
        {
            "name": "Suspicious seller with red flags",
            "description": "Incredible deal! Act fast, won't last. Wire transfer only. "
                          "No refunds, all sales final. Send money first. "
                          "Don't ask questions. Too good to be true.",
            "seller_id": "@x",
            "platform": "Craigslist",
            "location": "",
            "expect_pass": False,
        },
        {
            "name": "Neutral seller on Facebook",
            "description": "For sale: SR20DET complete. Runs and drives. Located NSW. "
                          "Can send more pics if interested. Cash or bank transfer.",
            "seller_id": "@sr20_dave",
            "platform": "facebook",
            "location": "Sydney, NSW",
            "expect_pass": True,
        },
        {
            "name": "Anonymous seller, no ID",
            "description": "RB26 for sale, $5000 firm.",
            "seller_id": "",
            "platform": "Telegram",
            "location": "",
            "expect_pass": False,
        },
        {
            "name": "Borderline seller on Telegram",
            "description": "1JZ-GTE non-VVTi, as-is no returns. Located Osaka. "
                          "Photos available. Message for details.",
            "seller_id": "@osaka_parts",
            "platform": "Telegram",
            "location": "Osaka, Japan",
            "expect_pass": False,  # Telegram baseline 0.45 + some positives - "as-is" penalty
        },
    ]

    print("Source Gate - Smoke Tests")
    print("=" * 60)
    for t in tests:
        result = source_gate(
            description=t["description"],
            seller_id=t["seller_id"],
            platform=t["platform"],
            location=t["location"]
        )
        status = "OK" if result.passed == t["expect_pass"] else "FAIL"
        print(f'{status} [{result.verdict.value:>18}] Score: {result.trust_score:.2f} | {t["name"]}')
        if result.passed != t["expect_pass"]:
            print(f'   EXPECTED: {"PASS" if t["expect_pass"] else "VETO"}, GOT: {"PASS" if result.passed else "VETO"}')
            print(f'   Positives: {result.signals_positive}')
            print(f'   Negatives: {result.signals_negative}')
            print(f'   Reason: {result.reason}')
    print("=" * 60)
