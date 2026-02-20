"""
Gate 1: Economic Viability Gate
========================================
Deterministic margin check. Rejects listings where projected margin
falls below the threshold — no LLM needed.

Status: ✅ LIVE (5/5 tests passing)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VetoCode(Enum):
    PASS = "PASS"
    MARGIN_TOO_LOW = "MARGIN_TOO_LOW"
    MISSING_DATA = "MISSING_DATA"
    NEGATIVE_MARGIN = "NEGATIVE_MARGIN"


@dataclass
class EconomicResult:
    """Immutable result from the economic gate."""
    verdict: VetoCode
    ask_price: Optional[float] = None
    estimated_resale: Optional[float] = None
    estimated_logistics: Optional[float] = None
    projected_margin: Optional[float] = None
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == VetoCode.PASS


def economic_gate(
    ask_price: float,
    estimated_resale: float,
    estimated_logistics: float = 0.0,
    min_margin: float = 0.20
) -> EconomicResult:
    """
    Gate 1: Economic viability check.
    
    Calculates: (estimated_resale - ask_price - logistics) / ask_price
    Blocks if margin < min_margin (default 20%).
    
    Args:
        ask_price: Seller's asking price
        estimated_resale: Estimated resale value
        estimated_logistics: Shipping, duties, prep costs
        min_margin: Minimum acceptable margin (default 0.20 = 20%)
    
    Returns:
        EconomicResult with verdict and supporting data
    """
    # Validate inputs
    if ask_price is None or estimated_resale is None:
        return EconomicResult(
            verdict=VetoCode.MISSING_DATA,
            reason="Missing ask_price or estimated_resale"
        )
    
    if ask_price <= 0:
        return EconomicResult(
            verdict=VetoCode.MISSING_DATA,
            ask_price=ask_price,
            reason="Ask price must be positive"
        )
    
    # Calculate margin
    net_profit = estimated_resale - ask_price - estimated_logistics
    margin = net_profit / ask_price
    
    # Determine verdict  
    if margin < 0:
        verdict = VetoCode.NEGATIVE_MARGIN
        reason = f"Negative margin: {margin:.1%}. Loss of ${abs(net_profit):,.2f}"
    elif margin < min_margin:
        verdict = VetoCode.MARGIN_TOO_LOW
        reason = f"Margin {margin:.1%} below threshold {min_margin:.0%}"
    else:
        verdict = VetoCode.PASS
        reason = f"Margin {margin:.1%} meets threshold {min_margin:.0%}. Projected profit: ${net_profit:,.2f}"
    
    return EconomicResult(
        verdict=verdict,
        ask_price=ask_price,
        estimated_resale=estimated_resale,
        estimated_logistics=estimated_logistics,
        projected_margin=margin,
        reason=reason
    )


if __name__ == "__main__":
    # Quick smoke test
    result = economic_gate(
        ask_price=4500,
        estimated_resale=7500,
        estimated_logistics=500
    )
    print(f"Verdict: {result.verdict.value}")
    print(f"Margin:  {result.projected_margin:.1%}")
    print(f"Reason:  {result.reason}")
    print(f"Passed:  {result.passed}")
