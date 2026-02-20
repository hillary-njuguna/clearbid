"""
Gate 5: Composite Gate — Full Pipeline Orchestrator
============================================================
Runs ALL gates in sequence, short-circuiting on first veto.
Produces a unified CompositeResult that feeds directly into
the reasoning layer (deal_report.py) for DealPacket generation.

Gate execution order:
    1. Identity Gate   — is this a genuine sale listing?
    2. Economic Gate   — does the margin meet viability?
    3. Source Gate      — is the seller trustworthy?
    4. Shipping Gate   — is the logistics viable?

Each gate is a cheap, deterministic veto filter.
Total pipeline cost: zero tokens. Pure Python.

Status: 🔨 BUILDING
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any

from gates.identity_gate import identity_gate, IdentityResult
from gates.economic_gate import economic_gate, EconomicResult
from gates.source_gate import source_gate, SourceResult
from gates.shipping_gate import shipping_gate, ShippingResult


class PipelineVerdict(Enum):
    GO = "GO"
    NO_GO = "NO_GO"
    REVIEW = "REVIEW"  # Future: for edge cases that need human judgement


@dataclass
class GateRecord:
    """Record of a single gate execution."""
    gate_name: str
    gate_number: int
    passed: bool
    verdict_code: str
    reason: str
    execution_order: int
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeResult:
    """
    Unified pipeline result from all gates.
    This is the primary input to the DealPacket renderer.
    """
    verdict: PipelineVerdict = PipelineVerdict.NO_GO
    vetoed_at_gate: Optional[str] = None
    confidence: float = 0.0
    gates_run: int = 0
    gates_passed: int = 0
    total_gates: int = 4
    gate_records: List[GateRecord] = field(default_factory=list)
    reasoning: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)

    # Individual gate results for downstream use
    identity_result: Optional[IdentityResult] = None
    economic_result: Optional[EconomicResult] = None
    source_result: Optional[SourceResult] = None
    shipping_result: Optional[ShippingResult] = None

    @property
    def all_passed(self) -> bool:
        return self.verdict == PipelineVerdict.GO

    @property
    def pass_rate(self) -> str:
        return f"{self.gates_passed}/{self.gates_run}"


def _record_gate(name: str, number: int, result, order: int, details: dict = None) -> GateRecord:
    """Create a GateRecord from any gate result object."""
    return GateRecord(
        gate_name=name,
        gate_number=number,
        passed=result.passed,
        verdict_code=result.verdict.value,
        reason=result.reason,
        execution_order=order,
        details=details or {}
    )


def composite_gate(
    description: str,
    ask_price: float,
    estimated_resale: float,
    estimated_logistics: float = 0.0,
    seller_id: str = "",
    platform: str = "Telegram",
    origin_location: str = "",
    dest_location: str = "GB",
    min_margin: float = 0.20,
    min_trust: float = 0.60,
    max_logistics_pct: float = 0.35,
) -> CompositeResult:
    """
    Run the full 4-gate pipeline on a listing.

    Gates execute in order and short-circuit on first veto.
    All gate results are preserved in the CompositeResult for
    the DealPacket renderer to use.

    Args:
        description: Full listing text
        ask_price: Seller's asking price (USD)
        estimated_resale: Estimated resale value
        estimated_logistics: Pre-estimated logistics cost (for Gate 2)
        seller_id: Seller handle/ID
        platform: Source platform
        origin_location: Origin location of the item
        dest_location: Buyer's destination (default: GB)
        min_margin: Minimum margin for economic gate
        min_trust: Minimum trust score for source gate
        max_logistics_pct: Max logistics % for shipping gate

    Returns:
        CompositeResult with full pipeline state
    """
    result = CompositeResult()
    order = 0

    # ── GATE 1: Identity ──
    order += 1
    id_result = identity_gate(description)
    result.identity_result = id_result
    result.gates_run += 1
    result.gate_records.append(
        _record_gate("Identity", 1, id_result, order)
    )

    if not id_result.passed:
        result.verdict = PipelineVerdict.NO_GO
        result.vetoed_at_gate = "Identity (Gate 1)"
        result.confidence = 0.95
        result.reasoning.append(f"Identity gate vetoed: {id_result.reason}")
        result.risk_flags.append(f"Non-sale listing detected ({id_result.verdict.value})")
        return result

    result.gates_passed += 1
    result.reasoning.append("Identity gate passed: listing is a genuine sale")

    # ── GATE 2: Economic ──
    order += 1
    econ_result = economic_gate(
        ask_price=ask_price,
        estimated_resale=estimated_resale,
        estimated_logistics=estimated_logistics,
        min_margin=min_margin
    )
    result.economic_result = econ_result
    result.gates_run += 1
    result.gate_records.append(
        _record_gate("Economic", 2, econ_result, order, {
            "margin": econ_result.projected_margin,
            "ask": ask_price,
            "resale": estimated_resale,
        })
    )

    if not econ_result.passed:
        result.verdict = PipelineVerdict.NO_GO
        result.vetoed_at_gate = "Economic (Gate 2)"
        result.confidence = 0.90
        result.reasoning.append(f"Economic gate vetoed: {econ_result.reason}")
        if econ_result.projected_margin and econ_result.projected_margin < 0:
            result.risk_flags.append("Negative margin — guaranteed loss")
        else:
            result.risk_flags.append("Margin below viability threshold")
        return result

    result.gates_passed += 1
    result.reasoning.append(
        f"Economic gate passed: {econ_result.projected_margin:.1%} margin "
        f"(threshold: {min_margin:.0%})"
    )

    # ── GATE 3: Source ──
    order += 1
    src_result = source_gate(
        description=description,
        seller_id=seller_id,
        platform=platform,
        location=origin_location,
        min_trust=min_trust
    )
    result.source_result = src_result
    result.gates_run += 1
    result.gate_records.append(
        _record_gate("Source", 3, src_result, order, {
            "trust_score": src_result.trust_score,
            "positives": len(src_result.signals_positive),
            "negatives": len(src_result.signals_negative),
        })
    )

    if not src_result.passed:
        result.verdict = PipelineVerdict.NO_GO
        result.vetoed_at_gate = "Source (Gate 3)"
        result.confidence = 0.85
        result.reasoning.append(f"Source gate vetoed: {src_result.reason}")
        result.risk_flags.append(
            f"Seller trust score {src_result.trust_score:.2f} "
            f"below threshold {min_trust:.2f}"
        )
        if src_result.signals_negative:
            for neg in src_result.signals_negative[:3]:
                result.risk_flags.append(f"Seller risk: {neg}")
        return result

    result.gates_passed += 1
    result.reasoning.append(
        f"Source gate passed: trust score {src_result.trust_score:.2f} "
        f"({len(src_result.signals_positive)} positive signals)"
    )

    # ── GATE 4: Shipping ──
    order += 1
    ship_result = shipping_gate(
        ask_price=ask_price,
        origin_location=origin_location,
        dest_location=dest_location,
        description=description,
        max_logistics_pct=max_logistics_pct
    )
    result.shipping_result = ship_result
    result.gates_run += 1
    result.gate_records.append(
        _record_gate("Shipping", 4, ship_result, order, {
            "shipping": ship_result.estimated_shipping,
            "duties": ship_result.estimated_duties,
            "landed": ship_result.total_landed_cost,
        })
    )

    if not ship_result.passed:
        result.verdict = PipelineVerdict.NO_GO
        result.vetoed_at_gate = "Shipping (Gate 4)"
        result.confidence = 0.80
        result.reasoning.append(f"Shipping gate vetoed: {ship_result.reason}")
        result.risk_flags.append(
            f"Logistics cost too high for route to {dest_location}"
        )
        return result

    result.gates_passed += 1
    result.reasoning.append(
        f"Shipping gate passed: landed cost ${ship_result.total_landed_cost:,.0f} "
        f"(logistics {ship_result.estimated_shipping + ship_result.estimated_duties:,.0f})"
    )

    # ── ALL GATES PASSED ──
    result.verdict = PipelineVerdict.GO
    result.confidence = 0.85
    result.reasoning.append(
        f"All {result.gates_passed}/{result.total_gates} gates passed. "
        f"Deal is viable — proceed to offer calculation."
    )

    return result


if __name__ == "__main__":
    tests = [
        {
            "name": "Full GO — trusted seller, good margins, viable route",
            "description": "Selling 2JZ-GTE, compression tested, dyno sheet available. "
                          "Photos and video. PayPal accepted. 10 years in business.",
            "ask_price": 4500,
            "estimated_resale": 7500,
            "estimated_logistics": 650,
            "seller_id": "@jdm_tokyo_exports",
            "platform": "Telegram",
            "origin": "Yokohama, Japan",
            "dest": "Singapore",  # Low duty + GST, viable route
            "expect_verdict": "GO",
        },
        {
            "name": "Veto at Gate 1 — WTB listing",
            "description": "WTB: looking for a clean 2JZ-GTE, budget $4000",
            "ask_price": 4000,
            "estimated_resale": 6000,
            "estimated_logistics": 500,
            "seller_id": "@buyer_dave",
            "platform": "Telegram",
            "origin": "Osaka, Japan",
            "dest": "GB",
            "expect_verdict": "NO_GO",
        },
        {
            "name": "Veto at Gate 2 — terrible margins",
            "description": "For sale: RB26DETT engine, running condition. Photos available.",
            "ask_price": 8000,
            "estimated_resale": 8200,
            "estimated_logistics": 1000,
            "seller_id": "@nissan_parts_jp",
            "platform": "Telegram",
            "origin": "Tokyo, Japan",
            "dest": "GB",
            "expect_verdict": "NO_GO",
        },
        {
            "name": "Veto at Gate 3 — suspicious seller",
            "description": "Incredible deal! Act fast, won't last. Wire transfer only. "
                          "No refunds. Too good to be true. Send money first.",
            "ask_price": 2000,
            "estimated_resale": 6000,
            "estimated_logistics": 500,
            "seller_id": "@x",
            "platform": "Craigslist",
            "origin": "Tokyo, Japan",
            "dest": "US",
            "expect_verdict": "NO_GO",
        },
        {
            "name": "Veto at Gate 4 — import restriction",
            "description": "OEM catalytic converter, brand new, for emissions compliance.",
            "ask_price": 1500,
            "estimated_resale": 3000,
            "estimated_logistics": 200,
            "seller_id": "@cat_parts_jp",
            "platform": "facebook",
            "origin": "Tokyo, Japan",
            "dest": "US",
            "expect_verdict": "NO_GO",
        },
    ]

    print("Composite Gate - Full Pipeline Smoke Tests")
    print("=" * 70)
    for t in tests:
        result = composite_gate(
            description=t["description"],
            ask_price=t["ask_price"],
            estimated_resale=t["estimated_resale"],
            estimated_logistics=t["estimated_logistics"],
            seller_id=t["seller_id"],
            platform=t["platform"],
            origin_location=t["origin"],
            dest_location=t["dest"]
        )
        status = "OK" if result.verdict.value == t["expect_verdict"] else "FAIL"
        veto_info = f"Vetoed at: {result.vetoed_at_gate}" if result.vetoed_at_gate else "All gates passed"
        print(f'{status} [{result.verdict.value:>5}] {result.pass_rate} gates | {veto_info} | {t["name"]}')
        if result.verdict.value != t["expect_verdict"]:
            print(f'   EXPECTED: {t["expect_verdict"]}, GOT: {result.verdict.value}')
            print(f'   Reasoning: {result.reasoning}')
            print(f'   Risk flags: {result.risk_flags}')
    print("=" * 70)
