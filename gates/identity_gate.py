"""
Gate 2: Identity / Intent Gate
=======================================
Regex-based veto that filters out non-sale listings:
  - WTB (Want to Buy) posts
  - "Wanted" / "Looking for" / "ISO" requests
  - Price check requests (no actual sale)
  - Duplicate/repost markers

This gate costs zero tokens. Pure regex. Runs before economic_gate
if the listing text is available, or after if only structured data
arrives first.

Status: 🔨 BUILDING
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class IdentityVetoCode(Enum):
    PASS = "PASS"
    WTB_DETECTED = "WTB_DETECTED"
    WANTED_AD = "WANTED_AD"
    PRICE_CHECK = "PRICE_CHECK"
    EMPTY_LISTING = "EMPTY_LISTING"
    DUPLICATE_MARKER = "DUPLICATE_MARKER"


@dataclass
class IdentityResult:
    """Immutable result from the identity gate."""
    verdict: IdentityVetoCode
    matched_patterns: List[str] = field(default_factory=list)
    original_text: str = ""
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == IdentityVetoCode.PASS


# ── Pattern Definitions ──
# Each tuple: (compiled_regex, veto_code, human_label)
_VETO_PATTERNS = [
    # WTB patterns
    (re.compile(r'\bW\s*T\s*B\b', re.IGNORECASE), 
     IdentityVetoCode.WTB_DETECTED, "WTB marker"),
    (re.compile(r'\bwant\s+to\s+buy\b', re.IGNORECASE), 
     IdentityVetoCode.WTB_DETECTED, "want to buy"),
    (re.compile(r'\bbuying\b.*\bany(?:one|body)?\b', re.IGNORECASE), 
     IdentityVetoCode.WTB_DETECTED, "buying request"),
    
    # Wanted / Looking for / ISO
    (re.compile(r'\b(?:wanted|looking\s+for|in\s+search\s+of|ISO)\b', re.IGNORECASE), 
     IdentityVetoCode.WANTED_AD, "wanted/ISO ad"),
    (re.compile(r'\bseeking\b.*\b(?:parts?|engine|vehicle|unit)\b', re.IGNORECASE), 
     IdentityVetoCode.WANTED_AD, "seeking parts"),
    (re.compile(r'\bneed\b.*\b(?:urgently?|asap|quickly)\b', re.IGNORECASE), 
     IdentityVetoCode.WANTED_AD, "urgent need request"),
    (re.compile(r'\banyone\s+(?:selling|have|got)\b', re.IGNORECASE), 
     IdentityVetoCode.WANTED_AD, "anyone selling query"),
    
    # Price checks (not actual sales)
    (re.compile(r'\b(?:price\s*check|PC|what(?:\'?s|\s+is)\s+(?:this|it)\s+worth)\b', re.IGNORECASE), 
     IdentityVetoCode.PRICE_CHECK, "price check"),
    (re.compile(r'\bhow\s+much\s+(?:is|are|would|should)\b', re.IGNORECASE), 
     IdentityVetoCode.PRICE_CHECK, "valuation query"),
    
    # Duplicate / repost markers
    (re.compile(r'\b(?:repost|bump|re-?listing)\b', re.IGNORECASE), 
     IdentityVetoCode.DUPLICATE_MARKER, "repost/bump"),
]

# ── Sale-positive signals ──
# If these appear WITH a veto pattern, reduce confidence of the veto.
# Not used for overriding, but logged for reasoning layer context.
_SALE_SIGNALS = [
    re.compile(r'\b(?:for\s+sale|F/?S|selling|sell)\b', re.IGNORECASE),
    re.compile(r'\$\s*\d+', re.IGNORECASE),
    re.compile(r'\b(?:OBO|firm|negotiable|ONO|or\s+best\s+offer)\b', re.IGNORECASE),
    re.compile(r'\b(?:DM|PM|inbox|message)\s+(?:me|for)\b', re.IGNORECASE),
]


def identity_gate(text: str) -> IdentityResult:
    """
    Gate 2: Identity/intent classification.
    
    Determines whether a listing text represents an actual sale
    or a non-sale intent (WTB, wanted, price check, etc.).
    
    Args:
        text: Raw listing text from source platform
        
    Returns:
        IdentityResult with verdict and matched patterns
    """
    if not text or not text.strip():
        return IdentityResult(
            verdict=IdentityVetoCode.EMPTY_LISTING,
            original_text="",
            reason="Empty or whitespace-only listing text"
        )
    
    cleaned = text.strip()
    matched = []
    
    # Check all veto patterns
    for pattern, veto_code, label in _VETO_PATTERNS:
        if pattern.search(cleaned):
            matched.append(label)
            # Check for sale-positive signals that might conflict
            has_sale_signal = any(sp.search(cleaned) for sp in _SALE_SIGNALS)
            
            if not has_sale_signal:
                # Clear veto — no conflicting sale signals
                return IdentityResult(
                    verdict=veto_code,
                    matched_patterns=matched,
                    original_text=cleaned,
                    reason=f"Non-sale intent detected: {label}. No sale-positive signals found."
                )
            else:
                # Conflicting signals — still veto but note the ambiguity
                # The reasoning layer can re-evaluate if needed
                return IdentityResult(
                    verdict=veto_code,
                    matched_patterns=matched,
                    original_text=cleaned,
                    reason=f"Non-sale intent detected: {label}. "
                           f"NOTE: Sale-positive signals also present — reasoning layer may override."
                )
    
    # No veto patterns matched — listing passes
    return IdentityResult(
        verdict=IdentityVetoCode.PASS,
        matched_patterns=[],
        original_text=cleaned,
        reason="No non-sale intent patterns detected. Listing appears to be a genuine sale."
    )


if __name__ == "__main__":
    # ── Smoke tests ──
    tests = [
        ("Selling 2JZ-GTE engine, low miles, $4500 OBO. DM for pics.", True),
        ("WTB: 2JZ-GTE engine, preferably non-VVTi. Budget $4K.", False),
        ("Looking for a clean SR20DET, anyone selling?", False),
        ("Price check — what's a 1JZ-GTE worth these days?", False),
        ("REPOST: Still available! RB26 complete swap, $8500 firm.", False),
        ("For sale: complete K24 swap kit, $3200. Located Bay Area.", True),
        ("ISO RB25DET Neo, must be running.", False),
        ("", False),
    ]
    
    print("Identity Gate — Smoke Tests")
    print("=" * 60)
    for text, expected_pass in tests:
        result = identity_gate(text)
        status = "OK" if result.passed == expected_pass else "FAIL"
        display = text[:50] + "..." if len(text) > 50 else text or "(empty)"
        print(f"{status} [{result.verdict.value:>16}] {display}")
        if result.passed != expected_pass:
            print(f"   EXPECTED: {'PASS' if expected_pass else 'VETO'}, GOT: {'PASS' if result.passed else 'VETO'}")
            print(f"   Reason: {result.reason}")
    print("=" * 60)
