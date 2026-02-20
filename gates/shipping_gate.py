"""
Gate 4: Shipping & Logistics Feasibility Gate
======================================================
Deterministic check on whether a deal is logistically viable:
  - Is the origin/destination route supported?
  - Do estimated shipping costs make sense for the item value?
  - Does FX conversion (if applicable) eat the margin?
  - Are there known import restriction risks?

This gate runs AFTER source (Gate 3) confirms seller credibility.
It uses lookup tables, not live API calls — intended for fast
deterministic veto before the expensive reasoning layer.

Status: 🔨 BUILDING
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class ShippingVetoCode(Enum):
    PASS = "PASS"
    ROUTE_UNSUPPORTED = "ROUTE_UNSUPPORTED"
    LOGISTICS_TOO_EXPENSIVE = "LOGISTICS_TOO_EXPENSIVE"
    FX_ERODES_MARGIN = "FX_ERODES_MARGIN"
    IMPORT_RESTRICTION = "IMPORT_RESTRICTION"
    MISSING_LOCATION = "MISSING_LOCATION"


@dataclass
class ShippingResult:
    """Immutable result from the shipping gate."""
    verdict: ShippingVetoCode
    estimated_shipping: float = 0.0
    estimated_duties: float = 0.0
    fx_impact_pct: float = 0.0
    total_landed_cost: float = 0.0
    cost_breakdown: List[str] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == ShippingVetoCode.PASS


# ── Region mapping (fuzzy match to canonical region) ──
_REGION_MAP = {
    # Japan
    "japan": "JP", "tokyo": "JP", "yokohama": "JP", "osaka": "JP",
    "nagoya": "JP", "kobe": "JP", "fukuoka": "JP", "sapporo": "JP",
    "hiroshima": "JP", "kyoto": "JP",
    # USA
    "usa": "US", "united states": "US", "us": "US", "california": "US",
    "bay area": "US", "los angeles": "US", "new york": "US", "texas": "US",
    "florida": "US", "chicago": "US", "miami": "US",
    # UK
    "uk": "GB", "united kingdom": "GB", "england": "GB", "london": "GB",
    "birmingham": "GB", "manchester": "GB", "scotland": "GB",
    # Australia
    "australia": "AU", "sydney": "AU", "melbourne": "AU", "brisbane": "AU",
    "perth": "AU", "nsw": "AU", "vic": "AU", "qld": "AU",
    # UAE
    "uae": "AE", "dubai": "AE", "abu dhabi": "AE", "sharjah": "AE",
    # Canada
    "canada": "CA", "toronto": "CA", "vancouver": "CA", "montreal": "CA",
    # Europe
    "germany": "DE", "berlin": "DE", "munich": "DE",
    "netherlands": "NL", "amsterdam": "NL", "rotterdam": "NL",
    # Kenya (home market)
    "kenya": "KE", "nairobi": "KE", "mombasa": "KE",
    # Singapore
    "singapore": "SG",
    # Thailand
    "thailand": "TH", "bangkok": "TH",
}

# ── Shipping cost estimates (origin_region → dest_region → cost_usd) ──
# These are RORO/container estimates for engine-sized items (~200kg)
_SHIPPING_COSTS = {
    ("JP", "US"): 800,
    ("JP", "GB"): 950,
    ("JP", "AU"): 650,
    ("JP", "AE"): 700,
    ("JP", "CA"): 850,
    ("JP", "DE"): 900,
    ("JP", "NL"): 900,
    ("JP", "KE"): 1100,
    ("JP", "SG"): 500,
    ("JP", "TH"): 450,
    ("US", "GB"): 700,
    ("US", "AU"): 900,
    ("US", "CA"): 400,
    ("US", "AE"): 1000,
    ("US", "JP"): 800,
    ("US", "KE"): 1200,
    ("GB", "US"): 700,
    ("GB", "AU"): 950,
    ("GB", "AE"): 600,
    ("GB", "KE"): 800,
    ("AU", "US"): 900,
    ("AU", "GB"): 950,
    ("AU", "JP"): 650,
    ("AE", "KE"): 500,
    ("AE", "GB"): 600,
    ("DE", "GB"): 350,
    ("DE", "US"): 750,
    ("NL", "GB"): 300,
}

# ── Import duty estimates (destination → % of declared value) ──
_DUTY_RATES = {
    "US": 0.025,   # 2.5% for auto parts
    "GB": 0.06,    # 6% + potential VAT (20%)
    "AU": 0.05,    # 5% customs + GST
    "AE": 0.05,    # 5% customs
    "CA": 0.06,    # 6.1% MFN
    "DE": 0.06,    # EU 6% + 19% VAT
    "NL": 0.06,    # EU 6% + 21% VAT
    "KE": 0.25,    # 25% import duty
    "SG": 0.0,     # Zero for most goods
    "TH": 0.10,    # 10% + VAT
    "JP": 0.0,     # Context-dependent
}

# ── VAT/GST rates (stacked on top of duty) ──
_VAT_RATES = {
    "US": 0.0,
    "GB": 0.20,
    "AU": 0.10,
    "AE": 0.05,
    "CA": 0.05,
    "DE": 0.19,
    "NL": 0.21,
    "KE": 0.16,
    "SG": 0.09,
    "TH": 0.07,
    "JP": 0.10,
}

# ── Known import restriction red flags ──
_IMPORT_RESTRICTIONS = [
    (re.compile(r'\b(?:catalytic\s*converter|cat\s*con|exhaust\s*emissions)\b', re.IGNORECASE),
     "Emissions-regulated component — may require compliance certification"),
    (re.compile(r'\b(?:airbag|srs|restraint)\b', re.IGNORECASE),
     "Safety-regulated component — import restrictions in most jurisdictions"),
    (re.compile(r'\b(?:refrigerant|r134a|r12|freon|a/?c\s*compressor)\b', re.IGNORECASE),
     "Controlled substance (refrigerant) — requires EPA/environmental clearance"),
]


def _resolve_region(location: str) -> Optional[str]:
    """Resolve a freeform location string to a canonical region code."""
    if not location:
        return None
    loc_lower = location.lower().strip()
    for key, code in _REGION_MAP.items():
        if key in loc_lower:
            return code
    return None


def shipping_gate(
    ask_price: float,
    origin_location: str,
    dest_location: str = "GB",
    description: str = "",
    max_logistics_pct: float = 0.35,
) -> ShippingResult:
    """
    Gate 4: Shipping & logistics feasibility check.

    Estimates total landed cost (shipping + duties + VAT/GST) and
    checks whether logistics costs exceed the viability threshold.

    Args:
        ask_price: Item price in USD
        origin_location: Origin location (freeform text)
        dest_location: Destination location/region (freeform or code)
        description: Listing description (for restriction scanning)
        max_logistics_pct: Max logistics as % of ask_price (default 35%)

    Returns:
        ShippingResult with verdict and full cost breakdown
    """
    # Resolve regions
    origin = _resolve_region(origin_location)
    dest = _resolve_region(dest_location) or dest_location.upper()[:2]

    if not origin:
        return ShippingResult(
            verdict=ShippingVetoCode.MISSING_LOCATION,
            reason=f"Cannot resolve origin location: '{origin_location}'. "
                   "Shipping estimate requires a recognisable origin."
        )

    if not dest:
        return ShippingResult(
            verdict=ShippingVetoCode.MISSING_LOCATION,
            reason=f"Cannot resolve destination location: '{dest_location}'. "
                   "Shipping estimate requires a recognisable destination."
        )

    # Check for import restrictions first
    for pattern, risk_desc in _IMPORT_RESTRICTIONS:
        if description and pattern.search(description):
            return ShippingResult(
                verdict=ShippingVetoCode.IMPORT_RESTRICTION,
                reason=f"Import restriction risk: {risk_desc}. "
                       f"Route {origin} to {dest} may be blocked or require permits.",
                cost_breakdown=[f"RESTRICTION: {risk_desc}"]
            )

    # Look up shipping cost
    route = (origin, dest)
    reverse_route = (dest, origin)
    if route in _SHIPPING_COSTS:
        shipping_cost = _SHIPPING_COSTS[route]
    elif reverse_route in _SHIPPING_COSTS:
        shipping_cost = _SHIPPING_COSTS[reverse_route]  # Approximate
    elif origin == dest:
        shipping_cost = 150  # Domestic
    else:
        # Unknown route — estimate based on average
        shipping_cost = 1000  # Conservative default

    breakdown = [f"Shipping ({origin} to {dest}): ${shipping_cost:,.0f}"]

    # Calculate duties
    duty_rate = _DUTY_RATES.get(dest, 0.05)  # Default 5%
    duties = ask_price * duty_rate
    breakdown.append(f"Import duty ({dest}, {duty_rate:.0%}): ${duties:,.0f}")

    # Calculate VAT/GST
    vat_rate = _VAT_RATES.get(dest, 0.0)
    vat_base = ask_price + duties  # VAT is usually on CIF + duty
    vat = vat_base * vat_rate
    if vat > 0:
        breakdown.append(f"VAT/GST ({dest}, {vat_rate:.0%}): ${vat:,.0f}")

    # Total landed cost (logistics portion only)
    total_logistics = shipping_cost + duties + vat
    total_landed = ask_price + total_logistics
    breakdown.append(f"Total logistics: ${total_logistics:,.0f}")
    breakdown.append(f"Total landed cost: ${total_landed:,.0f}")

    logistics_pct = total_logistics / ask_price if ask_price > 0 else 999

    # Determine verdict
    if logistics_pct > max_logistics_pct:
        verdict = ShippingVetoCode.LOGISTICS_TOO_EXPENSIVE
        reason = (f"Logistics cost ${total_logistics:,.0f} is {logistics_pct:.0%} of ask price "
                  f"(threshold: {max_logistics_pct:.0%}). Route {origin} to {dest} "
                  f"is not economically viable at this price point.")
    else:
        verdict = ShippingVetoCode.PASS
        reason = (f"Logistics cost ${total_logistics:,.0f} is {logistics_pct:.0%} of ask price "
                  f"(within {max_logistics_pct:.0%} threshold). Route {origin} to {dest} "
                  f"is feasible. Total landed cost: ${total_landed:,.2f}.")

    return ShippingResult(
        verdict=verdict,
        estimated_shipping=shipping_cost,
        estimated_duties=duties + vat,
        total_landed_cost=total_landed,
        cost_breakdown=breakdown,
        reason=reason
    )


if __name__ == "__main__":
    tests = [
        {
            "name": "Japan to UK — standard engine",
            "ask_price": 4500,
            "origin": "Yokohama, Japan",
            "dest": "United Kingdom",
            "desc": "2JZ-GTE complete engine with turbo and ECU",
            "expect_pass": False,  # UK VAT (20%) pushes logistics to 48% of ask
        },
        {
            "name": "Japan to Kenya — high duty market",
            "ask_price": 3000,
            "origin": "Osaka, Japan",
            "dest": "Nairobi, Kenya",
            "desc": "4AGE 20V silvertop engine",
            "expect_pass": False,  # 25% duty + 16% VAT + shipping = high cost ratio
        },
        {
            "name": "US domestic — low freight",
            "ask_price": 5000,
            "origin": "California",
            "dest": "Texas",
            "desc": "LS3 6.2L engine, tested and running",
            "expect_pass": True,
        },
        {
            "name": "Import restriction — catalytic converter",
            "ask_price": 2000,
            "origin": "Japan",
            "dest": "USA",
            "desc": "OEM catalytic converter for compliance",
            "expect_pass": False,
        },
        {
            "name": "Missing origin",
            "ask_price": 4000,
            "origin": "somewhere",
            "dest": "UK",
            "desc": "RB25DET engine swap",
            "expect_pass": False,
        },
    ]

    print("Shipping Gate - Smoke Tests")
    print("=" * 60)
    for t in tests:
        result = shipping_gate(
            ask_price=t["ask_price"],
            origin_location=t["origin"],
            dest_location=t["dest"],
            description=t["desc"]
        )
        status = "OK" if result.passed == t["expect_pass"] else "FAIL"
        landed = f"Landed: ${result.total_landed_cost:,.0f}" if result.total_landed_cost else "N/A"
        print(f'{status} [{result.verdict.value:>25}] {landed} | {t["name"]}')
        if result.passed != t["expect_pass"]:
            print(f'   EXPECTED: {"PASS" if t["expect_pass"] else "VETO"}')
            print(f'   Reason: {result.reason}')
            print(f'   Breakdown: {result.cost_breakdown}')
    print("=" * 60)
