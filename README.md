# ClearBid — Sovereign Decision Compiler

> One page. GO or NO-GO. Evidence included.

**Send a listing. Receive a DealPacket. Keep the document.**

ClearBid is a deterministic deal analysis pipeline for procurement, imports, used equipment, and fleet buying. It runs listings through a series of veto gates — cheap, fast, auditable — before bounded AI reasoning produces a structured DealPacket artifact.

## Architecture

```
Listing → γ-Node (Ingest) → μ-Node (Veto Gates) → α-Node (Reasoning) → τ-Node (Human Auth) → ρ-Node (Ledger)
```

### Gate Pipeline (μ-Node)

| Gate | File                      | Function                      | Status      |
| ---- | ------------------------- | ----------------------------- | ----------- |
| 1    | `gates/economic_gate.py`  | Margin viability check (>20%) | ✅ LIVE     |
| 2    | `gates/identity_gate.py`  | WTB/wanted ad filter          | 🔨 Building |
| 3    | `gates/source_gate.py`    | Seller reputation check       | 📋 Planned  |
| 4    | `gates/shipping_gate.py`  | Logistics feasibility + FX    | 📋 Planned  |
| 5    | `gates/composite_gate.py` | Full pipeline orchestration   | 📋 Planned  |

### Output

`deal_report.py` generates a 1-page PDF DealPacket:

- **Verdict**: GO / NO-GO
- **Recommended offer** with evidence
- **Gate results** with confidence scores
- **Audit trail** for every decision

## Usage

```bash
python -m clearbid.pipeline "JDM engine 2JZ-GTE, asking $4500, located Tokyo"
```

## Pricing

- **$25–75** per DealPacket (manual service)
- **$49–199/mo** ClearBid Pro (automated SaaS, Q2)

## License

Proprietary — Hillary Systems © 2026
