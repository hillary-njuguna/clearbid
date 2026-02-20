"""
ClearBid DealPacket — Premium PDF Report Generator
===================================================
Combines gate results into a single-page, investor-grade
DealPacket that a buyer can file, forward, and act on.

Design: Dark navy + gold + forest green. Goldman meets Bloomberg.
The document IS the product. Not a conversation — an artifact.

Usage:
    python deal_report.py                    # Generate both samples
    python deal_report.py --test-go          # GO sample only
    python deal_report.py --test-nogo        # NO-GO sample only
    python deal_report.py output.pdf         # Custom output path

Status: LIVE v2
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

# Import gates
from gates.economic_gate import economic_gate, EconomicResult, VetoCode
from gates.identity_gate import identity_gate, IdentityResult, IdentityVetoCode


# ══════════════════════════════════════════════════════════
# COLOR PALETTE — Premium Dark
# ══════════════════════════════════════════════════════════
class Palette:
    NAVY       = colors.HexColor("#0B1426")
    NAVY_MID   = colors.HexColor("#162240")
    NAVY_LIGHT = colors.HexColor("#1E2D52")
    GOLD       = colors.HexColor("#C9A84C")
    GOLD_DIM   = colors.HexColor("#8A7535")
    GREEN      = colors.HexColor("#1B8C5A")
    GREEN_LIGHT= colors.HexColor("#22B573")
    RED        = colors.HexColor("#C0392B")
    RED_DIM    = colors.HexColor("#922B21")
    WHITE      = colors.HexColor("#FFFFFF")
    CREAM      = colors.HexColor("#F5F0E8")
    PAPER      = colors.HexColor("#FAFAF7")
    INK        = colors.HexColor("#1C1916")
    INK2       = colors.HexColor("#4A4540")
    INK3       = colors.HexColor("#8A8278")
    RULE       = colors.HexColor("#DDD8CF")
    VERDICT_GO = colors.HexColor("#0D7A3F")
    VERDICT_NO = colors.HexColor("#B91C1C")


# ══════════════════════════════════════════════════════════
# DATA MODEL
# ══════════════════════════════════════════════════════════
@dataclass
class ListingInput:
    """Raw listing data — what the user sends us."""
    title: str
    description: str
    ask_price: float
    currency: str = "USD"
    estimated_resale: float = 0.0
    estimated_logistics: float = 0.0
    platform: str = "Telegram"
    seller_id: str = ""
    location: str = ""
    category: str = ""
    image_url: str = ""


@dataclass
class DealPacket:
    """The crystallized decision unit — the product."""
    packet_id: str = ""
    timestamp: str = ""
    verdict: str = "PENDING"  # GO, NO_GO, REVIEW
    confidence: float = 0.0
    recommended_offer: float = 0.0
    listing: Optional[ListingInput] = None
    identity_result: Optional[IdentityResult] = None
    economic_result: Optional[EconomicResult] = None
    reasoning: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.packet_id:
            self.packet_id = str(uuid.uuid4())[:8].upper()
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ══════════════════════════════════════════════════════════
# PIPELINE — Run gates, produce DealPacket
# ══════════════════════════════════════════════════════════
def run_pipeline(listing: ListingInput) -> DealPacket:
    """
    Run the full gate pipeline on a listing.
    Returns a DealPacket with all results.
    """
    packet = DealPacket(listing=listing)

    # Gate 1: Identity
    id_result = identity_gate(listing.description)
    packet.identity_result = id_result

    if not id_result.passed:
        packet.verdict = "NO_GO"
        packet.confidence = 0.95
        packet.reasoning.append(f"Identity gate vetoed: {id_result.reason}")
        packet.risk_flags.append(f"Non-sale listing detected ({id_result.verdict.value})")
        return packet

    packet.reasoning.append("Identity gate passed: listing is a genuine sale")

    # Gate 2: Economic
    econ_result = economic_gate(
        ask_price=listing.ask_price,
        estimated_resale=listing.estimated_resale,
        estimated_logistics=listing.estimated_logistics
    )
    packet.economic_result = econ_result

    if not econ_result.passed:
        packet.verdict = "NO_GO"
        packet.confidence = 0.90
        packet.reasoning.append(f"Economic gate vetoed: {econ_result.reason}")
        if econ_result.projected_margin and econ_result.projected_margin < 0:
            packet.risk_flags.append("Negative margin — guaranteed loss")
        else:
            packet.risk_flags.append("Margin below 20% viability threshold")
        return packet

    packet.reasoning.append(f"Economic gate passed: {econ_result.projected_margin:.1%} margin")

    # All gates passed — calculate offer
    packet.verdict = "GO"
    packet.confidence = 0.85
    # Recommended offer: 85-90% of ask (depending on margin headroom)
    margin = econ_result.projected_margin
    if margin > 0.50:
        offer_pct = 0.82  # Strong margin — negotiate hard
        packet.reasoning.append("Strong margin (>50%): aggressive offer recommended")
    elif margin > 0.35:
        offer_pct = 0.88
        packet.reasoning.append("Healthy margin (35-50%): moderate negotiation room")
    else:
        offer_pct = 0.93  # Thin margin — offer close to ask
        packet.reasoning.append("Thin margin (20-35%): offer near asking price")

    packet.recommended_offer = round(listing.ask_price * offer_pct, 2)
    return packet


# ══════════════════════════════════════════════════════════
# PDF RENDERER — The Beautiful Part
# ══════════════════════════════════════════════════════════
class DealPacketPDF:
    """Premium one-page DealPacket PDF generator."""

    def __init__(self, packet: DealPacket, output_path: str = "dealpacket.pdf"):
        self.packet = packet
        self.output_path = output_path
        self.width, self.height = A4
        self.margin = 18 * mm
        self.c = canvas.Canvas(output_path, pagesize=A4)
        self.c.setTitle(f"ClearBid DealPacket — {packet.packet_id}")
        self.c.setAuthor("ClearBid by Hillary Systems")
        self.y = self.height  # Current y position (top-down)

    def _usable_width(self):
        return self.width - 2 * self.margin

    def _draw_rect(self, x, y, w, h, fill_color, stroke=False, stroke_color=None):
        self.c.setFillColor(fill_color)
        if stroke and stroke_color:
            self.c.setStrokeColor(stroke_color)
            self.c.setLineWidth(0.5)
            self.c.rect(x, y, w, h, fill=1, stroke=1)
        else:
            self.c.rect(x, y, w, h, fill=1, stroke=0)

    def _draw_rounded_rect(self, x, y, w, h, r, fill_color, stroke=False, stroke_color=None):
        self.c.setFillColor(fill_color)
        if stroke and stroke_color:
            self.c.setStrokeColor(stroke_color)
            self.c.setLineWidth(0.5)
            self.c.roundRect(x, y, w, h, r, fill=1, stroke=1)
        else:
            self.c.roundRect(x, y, w, h, r, fill=1, stroke=0)

    def _text(self, x, y, text, size=9, color=Palette.INK, font="Helvetica", align="left"):
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        if align == "right":
            tw = self.c.stringWidth(text, font, size)
            self.c.drawString(x - tw, y, text)
        elif align == "center":
            tw = self.c.stringWidth(text, font, size)
            self.c.drawString(x - tw / 2, y, text)
        else:
            self.c.drawString(x, y, text)

    def _draw_paragraph(self, x, y_top, max_width, text, size=9,
                        color=Palette.INK, font="Helvetica", leading=None):
        """
        Draw word-wrapped text using a reportlab Paragraph.
        y_top is the TOP of the text block (our top-down coordinate).
        Returns the actual height consumed so callers can advance self.y.
        """
        if leading is None:
            leading = size * 1.4
        hex_color = color.hexval() if hasattr(color, 'hexval') else str(color)
        # Sanitize text for XML — escape ampersands and angle brackets
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        style = ParagraphStyle(
            "para",
            fontName=font,
            fontSize=size,
            leading=leading,
            textColor=color,
        )
        para = Paragraph(safe, style)
        w, h = para.wrap(max_width, 500 * mm)
        # drawOn expects the BOTTOM-LEFT y coordinate
        para.drawOn(self.c, x, y_top - h)
        return h

    def render(self):
        """Render the complete DealPacket to PDF."""
        self._render_header()
        self._render_verdict_banner()
        self._render_listing_details()
        self._render_economic_analysis()
        self._render_gate_status()
        self._render_recommendation()
        self._render_reasoning()
        self._render_footer()
        self.c.save()
        return self.output_path

    # ── HEADER ──
    def _render_header(self):
        p = self.packet
        header_h = 32 * mm

        # Full-width navy header
        self._draw_rect(0, self.height - header_h, self.width, header_h, Palette.NAVY)

        # Gold accent line at bottom of header
        self._draw_rect(0, self.height - header_h, self.width, 0.8 * mm, Palette.GOLD)

        # Brand name
        self._text(self.margin, self.height - 10 * mm, "CLEARBID",
                   size=11, color=Palette.GOLD, font="Helvetica-Bold")
        self._text(self.margin, self.height - 15 * mm, "DEALPACKET",
                   size=22, color=Palette.WHITE, font="Helvetica-Bold")

        # Right side: packet metadata
        rx = self.width - self.margin
        self._text(rx, self.height - 10 * mm, f"Packet ID: {p.packet_id}",
                   size=7.5, color=Palette.GOLD_DIM, font="Helvetica", align="right")
        self._text(rx, self.height - 14.5 * mm, p.timestamp,
                   size=7.5, color=Palette.GOLD_DIM, font="Helvetica", align="right")
        self._text(rx, self.height - 19 * mm,
                   f"Pipeline: 2 gates active | Confidence: {p.confidence:.0%}",
                   size=7.5, color=Palette.GOLD_DIM, font="Helvetica", align="right")

        # Decorative corner marks
        self._text(rx, self.height - 26 * mm, "hillary.systems",
                   size=6.5, color=colors.HexColor("#3A4A6B"), font="Helvetica", align="right")

        self.y = self.height - header_h - 6 * mm

    # ── VERDICT BANNER ──
    # DEFECT 4 FIX: Confidence badge flush-right, vertically centred
    def _render_verdict_banner(self):
        p = self.packet
        is_go = p.verdict == "GO"
        banner_h = 22 * mm
        uw = self._usable_width()

        # Banner background
        bg_color = Palette.VERDICT_GO if is_go else Palette.VERDICT_NO
        banner_top = self.y
        banner_bottom = self.y - banner_h
        self._draw_rounded_rect(self.margin, banner_bottom, uw, banner_h, 3, bg_color)

        # Vertical centre of banner
        vc = banner_bottom + banner_h / 2

        # Left block: Verdict text — vertically centred
        verdict_text = "GO" if is_go else "NO-GO"
        verdict_size = 32
        self._text(self.margin + 8 * mm, vc - verdict_size * 0.35, verdict_text,
                   size=verdict_size, color=Palette.WHITE, font="Helvetica-Bold")

        # Right block: Confidence badge — vertically centred, flush-right
        rx = self.margin + uw - 6 * mm
        conf_size = 22
        self._text(rx, vc + 1 * mm, f"{p.confidence:.0%}",
                   size=conf_size, color=Palette.WHITE, font="Helvetica-Bold", align="right")
        self._text(rx, vc - 5 * mm, "CONFIDENCE",
                   size=6, color=colors.HexColor("#FFFFFFAA"), font="Helvetica", align="right")

        # Middle block: Description + offer (between verdict text and confidence)
        mid_x = self.margin + 55 * mm
        mid_max_w = uw - 55 * mm - 35 * mm  # Leave room for confidence badge

        if is_go and p.listing:
            desc = "This listing passes all active gates. Proceed with offer."
        elif p.risk_flags:
            desc = p.risk_flags[0]
        else:
            desc = "Listing did not meet viability thresholds."

        self._draw_paragraph(mid_x, vc + 7 * mm, mid_max_w, desc,
                             size=8.5, color=colors.HexColor("#FFFFFFCC"), font="Helvetica")

        if is_go and p.recommended_offer > 0:
            self._text(mid_x, vc - 5 * mm,
                       f"Recommended Offer: ${p.recommended_offer:,.2f}",
                       size=11, color=Palette.WHITE, font="Helvetica-Bold")

        self.y = banner_bottom - 5 * mm

    # ── LISTING DETAILS ──
    # DEFECT 1 FIX: Word-wrapped description via Paragraph
    def _render_listing_details(self):
        p = self.packet
        if not p.listing:
            return

        uw = self._usable_width()

        # Section header
        self._text(self.margin, self.y - 3 * mm, "LISTING DETAILS",
                   size=7, color=Palette.GOLD, font="Helvetica-Bold")
        self._draw_rect(self.margin, self.y - 4.5 * mm, uw, 0.3 * mm, Palette.RULE)

        y = self.y - 10 * mm
        listing = p.listing

        # Two-column layout
        col1_x = self.margin
        col1_w = uw / 2 - 4 * mm
        col2_x = self.margin + uw / 2

        # Column 1: Title (word-wrapped)
        title_h = self._draw_paragraph(col1_x, y, col1_w, listing.title,
                                       size=11, color=Palette.INK, font="Helvetica-Bold")
        y -= title_h + 2 * mm

        # Column 1: Description (word-wrapped, no truncation)
        desc_h = self._draw_paragraph(col1_x, y, col1_w, listing.description,
                                      size=8, color=Palette.INK2, font="Helvetica")

        # Column 2: Key facts — anchored to section top
        facts_y = self.y - 10 * mm
        facts = [
            ("Platform", listing.platform),
            ("Location", listing.location or "Not specified"),
            ("Seller", listing.seller_id or "Anonymous"),
            ("Category", listing.category or "General"),
        ]
        for label, value in facts:
            self._text(col2_x, facts_y, f"{label}:",
                       size=7, color=Palette.INK3, font="Helvetica")
            self._text(col2_x + 18 * mm, facts_y, value,
                       size=8, color=Palette.INK, font="Helvetica-Bold")
            facts_y -= 4.5 * mm

        # Advance by whichever column is taller
        col1_total = (self.y - 10 * mm) - (y - desc_h)
        col2_total = (self.y - 10 * mm) - facts_y
        section_used = max(col1_total, col2_total)
        self.y = self.y - 10 * mm - section_used - 4 * mm

    # ── ECONOMIC ANALYSIS ──
    # DEFECT 2 FIX: Conditional rendering based on which gate vetoed
    def _render_economic_analysis(self):
        p = self.packet
        uw = self._usable_width()

        # Section header
        self._text(self.margin, self.y - 3 * mm, "ECONOMIC ANALYSIS",
                   size=7, color=Palette.GOLD, font="Helvetica-Bold")
        self._draw_rect(self.margin, self.y - 4.5 * mm, uw, 0.3 * mm, Palette.RULE)

        y = self.y - 12 * mm

        # DEFECT 2: If identity gate vetoed, economic gate never ran.
        # Do NOT render price fields — they would be misleading.
        if p.economic_result is None:
            # Identity gate vetoed before economic gate could run
            notice_h = 10 * mm
            self._draw_rounded_rect(self.margin, y - notice_h, uw, notice_h, 2,
                                    colors.HexColor("#FEF2F2"),
                                    stroke=True, stroke_color=Palette.RED_DIM)
            self._text(self.margin + 4 * mm, y - 6.5 * mm,
                       "Not evaluated — listing vetoed at Gate 1: Identity",
                       size=8.5, color=Palette.RED_DIM, font="Helvetica")
            self.y = y - notice_h - 4 * mm
            return

        listing = p.listing

        if listing:
            # Price boxes — three columns
            box_w = uw / 3 - 2 * mm
            box_h = 18 * mm
            prices = [
                ("ASK PRICE", f"${listing.ask_price:,.2f}", Palette.NAVY_LIGHT),
                ("EST. RESALE", f"${listing.estimated_resale:,.2f}", Palette.NAVY_MID),
                ("LOGISTICS", f"${listing.estimated_logistics:,.2f}", Palette.NAVY_LIGHT),
            ]

            for i, (label, value, bg) in enumerate(prices):
                bx = self.margin + i * (box_w + 2 * mm)
                self._draw_rounded_rect(bx, y - box_h, box_w, box_h, 2, bg)
                self._text(bx + 4 * mm, y - 6 * mm, label,
                           size=6, color=Palette.GOLD_DIM, font="Helvetica")
                self._text(bx + 4 * mm, y - 12 * mm, value,
                           size=14, color=Palette.WHITE, font="Helvetica-Bold")

            y -= box_h + 4 * mm

            # Margin bar
            if p.economic_result.projected_margin is not None:
                margin = p.economic_result.projected_margin
                margin_pct = max(0, min(1, margin))  # Clamp 0-100%

                # Bar background
                bar_w = uw
                bar_h = 8 * mm
                self._draw_rounded_rect(self.margin, y - bar_h, bar_w, bar_h, 2,
                                        colors.HexColor("#EEEAE3"))

                # Bar fill
                fill_color = Palette.GREEN if margin >= 0.20 else Palette.RED
                fill_w = max(bar_w * margin_pct, 6 * mm)
                self._draw_rounded_rect(self.margin, y - bar_h, fill_w, bar_h, 2,
                                        fill_color)

                # Margin label
                self._text(self.margin + 3 * mm, y - 5.5 * mm,
                           f"PROJECTED MARGIN: {margin:.1%}",
                           size=7, color=Palette.WHITE, font="Helvetica-Bold")

                # Threshold marker
                threshold_x = self.margin + bar_w * 0.20
                self.c.setStrokeColor(Palette.GOLD)
                self.c.setLineWidth(1)
                self.c.setDash([2, 2])
                self.c.line(threshold_x, y - bar_h, threshold_x, y)
                self.c.setDash([])
                self._text(threshold_x + 1 * mm, y + 1 * mm, "20% threshold",
                           size=5.5, color=Palette.INK3, font="Helvetica")

                # Net profit
                if listing.estimated_resale > 0:
                    net = listing.estimated_resale - listing.ask_price - listing.estimated_logistics
                    profit_label = f"Net: ${net:,.2f}" if net > 0 else f"Loss: ${abs(net):,.2f}"
                    self._text(self.margin + bar_w - 3 * mm, y - 5.5 * mm,
                               profit_label,
                               size=7, color=Palette.WHITE, font="Helvetica-Bold", align="right")

                y -= bar_h + 3 * mm

        self.y = y - 2 * mm

    # ── GATE STATUS ──
    # DEFECT 3 FIX: Consistent alignment, word-wrapped descriptions,
    # handle unreached gates, proper colours per verdict
    def _render_gate_status(self):
        p = self.packet
        uw = self._usable_width()

        self._text(self.margin, self.y - 3 * mm, "GATE STATUS",
                   size=7, color=Palette.GOLD, font="Helvetica-Bold")
        self._draw_rect(self.margin, self.y - 4.5 * mm, uw, 0.3 * mm, Palette.RULE)

        y = self.y - 10 * mm
        gate_w = uw / 2 - 2 * mm

        gates = [
            ("GATE 1: IDENTITY", p.identity_result),
            ("GATE 2: ECONOMIC", p.economic_result),
        ]

        for i, (name, result) in enumerate(gates):
            gx = self.margin + i * (gate_w + 4 * mm)

            # Determine gate state: PASS, VETO, or NOT REACHED
            if result is None:
                # Gate was never reached (pipeline stopped before it)
                indicator = "NOT EVALUATED"
                ind_color = Palette.INK3
                bg = colors.HexColor("#F5F3EF")
                border = Palette.RULE
                reason_text = "Pipeline halted at a prior gate before this gate was reached."
            elif result.passed:
                indicator = "PASS"
                ind_color = Palette.GREEN
                bg = colors.HexColor("#E8F4EE")
                border = Palette.GREEN
                reason_text = result.reason
            else:
                indicator = "VETO"
                ind_color = Palette.RED
                bg = colors.HexColor("#FEF2F2")
                border = Palette.RED
                reason_text = result.reason

            # Gate card background — taller to allow word-wrapped description
            gate_h = 10 * mm
            self._draw_rounded_rect(gx, y - gate_h, gate_w, gate_h, 2, bg,
                                    stroke=True, stroke_color=border)

            # Gate label: bold, left-aligned, coloured by verdict
            self._text(gx + 4 * mm, y - 4 * mm, indicator,
                       size=8, color=ind_color, font="Helvetica-Bold")
            self._text(gx + 4 * mm + self.c.stringWidth(indicator, "Helvetica-Bold", 8) + 3 * mm,
                       y - 4 * mm, name,
                       size=7, color=Palette.INK2, font="Helvetica")

            # Gate description: indented 12pt, word-wrapped, normal weight
            desc_top = y - gate_h - 1 * mm
            desc_w = gate_w - 8 * mm
            desc_h = self._draw_paragraph(gx + 4 * mm, desc_top, desc_w, reason_text,
                                          size=6.5, color=Palette.INK3, font="Helvetica",
                                          leading=8.5)

        # Advance y past both gate cards + descriptions
        # Use fixed spacing to keep layout predictable
        self.y = y - gate_h - 14 * mm

    # ── RECOMMENDATION ──
    def _render_recommendation(self):
        p = self.packet
        uw = self._usable_width()

        if p.verdict != "GO" or not p.listing:
            return

        rec_h = 16 * mm
        self._draw_rounded_rect(self.margin, self.y - rec_h, uw, rec_h, 3,
                                colors.HexColor("#F8F6F0"),
                                stroke=True, stroke_color=Palette.GOLD)

        # Gold left accent
        self._draw_rect(self.margin, self.y - rec_h, 3 * mm, rec_h, Palette.GOLD)

        # Offer
        self._text(self.margin + 7 * mm, self.y - 5 * mm, "RECOMMENDED OFFER",
                   size=6.5, color=Palette.GOLD, font="Helvetica-Bold")
        self._text(self.margin + 7 * mm, self.y - 12 * mm,
                   f"${p.recommended_offer:,.2f}  {p.listing.currency}",
                   size=18, color=Palette.INK, font="Helvetica-Bold")

        # Savings
        savings = p.listing.ask_price - p.recommended_offer
        savings_pct = savings / p.listing.ask_price * 100
        self._text(self.margin + uw - 5 * mm, self.y - 5 * mm,
                   f"Negotiation target: ${savings:,.0f} below ask ({savings_pct:.0f}%)",
                   size=7, color=Palette.INK3, font="Helvetica", align="right")

        # Upside
        if p.economic_result and p.economic_result.estimated_resale:
            upside = p.economic_result.estimated_resale - p.recommended_offer - (p.listing.estimated_logistics or 0)
            self._text(self.margin + uw - 5 * mm, self.y - 12 * mm,
                       f"Projected upside at offer price: ${upside:,.2f}",
                       size=8, color=Palette.GREEN, font="Helvetica-Bold", align="right")

        self.y = self.y - rec_h - 5 * mm

    # ── REASONING ──
    # DEFECT 1 + 5 FIX: Full text, word-wrapped, no truncation
    def _render_reasoning(self):
        p = self.packet
        uw = self._usable_width()

        self._text(self.margin, self.y - 3 * mm, "REASONING TRACE",
                   size=7, color=Palette.GOLD, font="Helvetica-Bold")
        self._draw_rect(self.margin, self.y - 4.5 * mm, uw, 0.3 * mm, Palette.RULE)

        y = self.y - 10 * mm
        step_text_x = self.margin + 8 * mm
        step_text_w = uw - 8 * mm  # Full remaining width for word-wrap

        for i, step in enumerate(p.reasoning[:6], 1):  # Max 6 steps
            # Step number badge
            self._draw_rounded_rect(self.margin, y - 3.5 * mm, 5 * mm, 4.5 * mm, 1,
                                    Palette.NAVY_LIGHT)
            self._text(self.margin + 2.5 * mm, y - 2 * mm, str(i),
                       size=6, color=Palette.GOLD, font="Helvetica-Bold", align="center")

            # Step text — full content, word-wrapped
            step_h = self._draw_paragraph(step_text_x, y, step_text_w, step,
                                          size=7.5, color=Palette.INK2, font="Helvetica",
                                          leading=10)
            y -= max(step_h, 4.5 * mm) + 2 * mm

        # Risk flags
        if p.risk_flags:
            y -= 2 * mm
            self._text(self.margin, y - 2 * mm, "RISK FLAGS",
                       size=6, color=Palette.RED, font="Helvetica-Bold")
            y -= 5 * mm
            for flag in p.risk_flags[:3]:
                flag_h = self._draw_paragraph(self.margin + 3 * mm, y, uw - 3 * mm,
                                              f"! {flag}",
                                              size=7, color=Palette.RED_DIM, font="Helvetica",
                                              leading=9)
                y -= max(flag_h, 4 * mm) + 1 * mm

        self.y = y

    # ── FOOTER ──
    def _render_footer(self):
        p = self.packet
        footer_h = 12 * mm
        uw = self._usable_width()

        # Footer background
        self._draw_rect(0, 0, self.width, footer_h, Palette.NAVY)

        # Gold line at top
        self._draw_rect(0, footer_h, self.width, 0.5 * mm, Palette.GOLD)

        # Left: brand
        self._text(self.margin, 5 * mm, "CLEARBID",
                   size=7, color=Palette.GOLD, font="Helvetica-Bold")
        self._text(self.margin, 2 * mm,
                   "Deal Analysis Pipeline  |  hillary.systems",
                   size=5.5, color=colors.HexColor("#5A6A8B"), font="Helvetica")

        # Center: audit hash
        self._text(self.width / 2, 5 * mm, f"Packet {p.packet_id}",
                   size=6, color=colors.HexColor("#5A6A8B"), font="Helvetica", align="center")
        self._text(self.width / 2, 2 * mm,
                   "This document is an immutable artifact. Gate verdicts are deterministic and auditable.",
                   size=4.5, color=colors.HexColor("#3A4A6B"), font="Helvetica", align="center")

        # Right: timestamp
        rx = self.width - self.margin
        self._text(rx, 5 * mm, p.timestamp,
                   size=6, color=colors.HexColor("#5A6A8B"), font="Helvetica", align="right")
        self._text(rx, 2 * mm, "Generated by ClearBid Pipeline v1.0",
                   size=4.5, color=colors.HexColor("#3A4A6B"), font="Helvetica", align="right")


# ══════════════════════════════════════════════════════════
# SAMPLE GENERATOR
# ══════════════════════════════════════════════════════════
def generate_sample_go(output_path: str = None) -> str:
    """Generate a sample GO DealPacket with realistic JDM data."""
    listing = ListingInput(
        title="Toyota 2JZ-GTE Non-VVTi Complete Engine",
        description="Selling a clean 2JZ-GTE non-VVTi pulled from a 1995 JZA80 Supra. "
                    "145,000 km, compression tested all 6 cylinders, no leaks. "
                    "Comes with turbo, exhaust manifold, ECU, and wiring harness. "
                    "Located in Yokohama. Can arrange shipping via Roro or container.",
        ask_price=4500.00,
        currency="USD",
        estimated_resale=7500.00,
        estimated_logistics=650.00,
        platform="Telegram",
        seller_id="@jdm_tokyo_exports",
        location="Yokohama, Japan",
        category="JDM Engines / Powertrain",
    )

    packet = run_pipeline(listing)

    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "output",
            f"DealPacket_{packet.packet_id}_v2.pdf"
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pdf = DealPacketPDF(packet, output_path)
    pdf.render()
    return output_path


def generate_sample_nogo(output_path: str = None) -> str:
    """Generate a sample NO-GO DealPacket."""
    listing = ListingInput(
        title="WTB: RB26DETT for R32 GTR project",
        description="Looking for a clean RB26DETT, must have matching numbers. "
                    "Budget around $6000. Located in Melbourne, can organise "
                    "freight from Japan. Anyone selling?",
        ask_price=6000.00,
        currency="USD",
        estimated_resale=8500.00,
        estimated_logistics=900.00,
        platform="Telegram",
        seller_id="@melb_gtr_builds",
        location="Melbourne, Australia",
        category="JDM Engines / Powertrain",
    )

    packet = run_pipeline(listing)

    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "output",
            f"DealPacket_{packet.packet_id}_NOGO_v2.pdf"
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    pdf = DealPacketPDF(packet, output_path)
    pdf.render()
    return output_path


if __name__ == "__main__":
    print("=" * 60)
    print("  CLEARBID DealPacket Generator v2")
    print("=" * 60)

    args = sys.argv[1:]

    if "--test-go" in args:
        go_path = generate_sample_go()
        print(f"\n  [GO]    DealPacket saved: {go_path}")
    elif "--test-nogo" in args:
        nogo_path = generate_sample_nogo()
        print(f"\n  [NO-GO] DealPacket saved: {nogo_path}")
    elif args and not args[0].startswith("--"):
        go_path = generate_sample_go(args[0])
        print(f"\n  [GO]    DealPacket saved: {go_path}")
    else:
        go_path = generate_sample_go()
        print(f"\n  [GO]    DealPacket saved: {go_path}")
        nogo_path = generate_sample_nogo()
        print(f"  [NO-GO] DealPacket saved: {nogo_path}")

    print(f"\n  Open these files to see your premium DealPackets.")
    print("=" * 60)
