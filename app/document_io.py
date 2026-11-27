import io
import os
import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from fpdf import FPDF
from pypdf import PdfReader


def extract_text_from_upload(filename: str, content: bytes) -> str:
    ext = Path(filename or "").suffix.lower()

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                pages.append(txt.strip())
        return "\n\n".join(pages).strip()

    if ext == ".docx":
        doc = Document(io.BytesIO(content))
        parts: list[str] = []
        for p in doc.paragraphs:
            if p.text.strip():
                parts.append(p.text.strip())
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(dict.fromkeys(cells)))
        return "\n".join(parts).strip()

    if ext in (".txt", ".md", ".markdown", ".rtf"):
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return content.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore").strip()

    raise ValueError(f"Formato no soportado ({ext}). Usa PDF, DOCX, TXT o MD.")


def _find_unicode_fonts() -> tuple[str | None, str | None]:
    """Locate a clean Unicode TTF font pair (regular, bold) across Linux/Docker and Windows."""
    candidates = [
        # Linux / Docker (fonts-dejavu-core)
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        # Windows system fonts
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf"),
        ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ]
    for reg, bold in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            return reg, bold
    return None, None


def _strip_md_inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return text.strip()


def _safe_latin1(text: str) -> str:
    replacements = {
        "\u2022": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def generate_ats_pdf(
    markdown_text: str,
    title: str = "Curriculum Vitae",
    template: str = "harvard",
    strict_one_page: bool = False,
) -> bytes:
    """
    Generate a clean, single-column, selectable-text ATS-friendly PDF from Markdown CV.
    Templates:
      - 'harvard': Classic Ivy/Corporate standard (high contrast, crisp divider lines, centered or clean headers).
      - 'modern': Contemporary clean styling (subtle primary slate/navy accents, clean typography).
      - 'compact': High-density single-page optimization (condensed margins & line heights).
    If strict_one_page=True, dynamically compresses spacing and font sizes to prevent 2nd page spillover.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")

    tpl = (template or "harvard").strip().lower()
    if tpl not in ("harvard", "modern", "compact"):
        tpl = "harvard"

    # Margins and baseline sizes based on template and strict_one_page
    if tpl == "compact" or strict_one_page:
        margin_x = 12.0
        margin_y = 10.0
        h1_size = 15.0
        h2_size = 10.2
        h3_size = 9.2
        body_size = 8.6
        body_lh = 4.2
        section_space = 2.0
    elif tpl == "modern":
        margin_x = 16.0
        margin_y = 14.0
        h1_size = 18.0
        h2_size = 11.5
        h3_size = 10.2
        body_size = 9.6
        body_lh = 5.0
        section_space = 3.2
    else:  # harvard
        margin_x = 16.0
        margin_y = 15.0
        h1_size = 17.0
        h2_size = 11.0
        h3_size = 10.0
        body_size = 9.4
        body_lh = 4.8
        section_space = 2.8

    pdf.set_auto_page_break(auto=not strict_one_page, margin=margin_y)
    pdf.set_margins(margin_x, margin_y, margin_x)
    pdf.set_title(title)

    reg_font, bold_font = _find_unicode_fonts()
    use_unicode = bool(reg_font and bold_font)
    font_family = "CVFont" if use_unicode else "Helvetica"

    if use_unicode:
        pdf.add_font("CVFont", "", reg_font)
        pdf.add_font("CVFont", "B", bold_font)

    pdf.add_page()

    def clean(s: str) -> str:
        s = _strip_md_inline(s)
        return s if use_unicode else _safe_latin1(s)

    def ensure_x():
        pdf.set_x(pdf.l_margin)

    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    # Color palettes
    if tpl == "harvard":
        h1_color = (17, 24, 39)
        h2_color = (31, 41, 55)
        rule_color = (156, 163, 175)
        body_color = (17, 24, 39)
    elif tpl == "modern":
        h1_color = (15, 44, 89)
        h2_color = (29, 78, 216)
        rule_color = (191, 219, 254)
        body_color = (30, 41, 59)
    else:  # compact
        h1_color = (15, 23, 42)
        h2_color = (51, 65, 85)
        rule_color = (203, 213, 225)
        body_color = (30, 41, 59)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            pdf.ln(1.8 if (strict_one_page or tpl == "compact") else 2.5)
            continue

        if line.startswith("# "):
            ensure_x()
            pdf.set_font(font_family, "B", h1_size)
            pdf.set_text_color(*h1_color)
            pdf.multi_cell(effective_width, h1_size * 0.45, clean(line[2:]))
            pdf.ln(0.8)
            continue

        if line.startswith("## "):
            pdf.ln(section_space * 0.7)
            ensure_x()
            pdf.set_font(font_family, "B", h2_size)
            pdf.set_text_color(*h2_color)
            pdf.multi_cell(effective_width, h2_size * 0.5, clean(line[3:]).upper())
            y = pdf.get_y()
            pdf.set_draw_color(*rule_color)
            pdf.set_line_width(0.35)
            pdf.line(pdf.l_margin, y + 0.4, pdf.w - pdf.r_margin, y + 0.4)
            pdf.ln(section_space * 0.6)
            continue

        if line.startswith("### "):
            pdf.ln(1.0)
            ensure_x()
            pdf.set_font(font_family, "B", h3_size)
            pdf.set_text_color(*h2_color)
            pdf.multi_cell(effective_width, h3_size * 0.5, clean(line[4:]))
            continue

        if line.startswith(("- ", "* ", "• ")):
            bullet_text = clean(line[2:])
            bullet_char = "•" if use_unicode else "-"
            pdf.set_font(font_family, "", body_size)
            pdf.set_text_color(*body_color)
            ensure_x()
            pdf.cell(4.0, body_lh, bullet_char)
            pdf.multi_cell(effective_width - 4.0, body_lh, bullet_text)
            pdf.ln(0.3)
            continue

        if re.match(r"^[-_*]{3,}$", line):
            y = pdf.get_y() + 1.0
            pdf.set_draw_color(*rule_color)
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(2.0)
            continue

        # Regular paragraph or contact/subtitle line
        ensure_x()
        is_bold_line = line.startswith("**") and line.endswith("**") and line.count("**") == 2
        pdf.set_font(font_family, "B" if is_bold_line else "", body_size)
        pdf.set_text_color(*body_color)
        pdf.multi_cell(effective_width, body_lh, clean(line))
        pdf.ln(0.4)

    out = pdf.output()
    return bytes(out)


def generate_ats_docx(
    markdown_text: str,
    title: str = "Curriculum Vitae",
    template: str = "harvard",
) -> bytes:
    """
    Generate a clean, single-column ATS-friendly Word document (.docx) from Markdown CV.
    """
    doc = Document()
    doc.core_properties.title = title

    tpl = (template or "harvard").strip().lower()
    if tpl not in ("harvard", "modern", "compact"):
        tpl = "harvard"

    for section in doc.sections:
        if tpl == "compact":
            section.top_margin = Inches(0.45)
            section.bottom_margin = Inches(0.45)
            section.left_margin = Inches(0.5)
            section.right_margin = Inches(0.5)
        else:
            section.top_margin = Inches(0.6)
            section.bottom_margin = Inches(0.6)
            section.left_margin = Inches(0.65)
            section.right_margin = Inches(0.65)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(9.5 if tpl == "compact" else 10.2)
    normal_style.font.color.rgb = RGBColor(17, 24, 39)

    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")

    def add_formatted_runs(paragraph, text: str, base_size: float = 10.2, base_color=RGBColor(38, 44, 54)):
        tokens = re.split(r"(\*\*.*?\*\*)", text)
        for token in tokens:
            if not token:
                continue
            if token.startswith("**") and token.endswith("**") and len(token) > 4:
                run = paragraph.add_run(token[2:-2])
                run.bold = True
            else:
                run = paragraph.add_run(re.sub(r"`(.+?)`", r"\1", token))
            run.font.name = "Calibri"
            run.font.size = Pt(base_size)
            run.font.color.rgb = base_color

    h2_color = RGBColor(29, 78, 216) if tpl == "modern" else RGBColor(31, 41, 55)

    for raw_line in lines:
        line = raw_line.strip()
        if not line or re.match(r"^[-_*]{3,}$", line):
            continue

        if line.startswith("# "):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(_strip_md_inline(line[2:]))
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(16 if tpl == "compact" else 18)
            run.font.color.rgb = RGBColor(17, 24, 39)
            continue

        if line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(7 if tpl == "compact" else 9)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(_strip_md_inline(line[3:]).upper())
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(10.5 if tpl == "compact" else 11.2)
            run.font.color.rgb = h2_color
            continue

        if line.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(1)
            run = p.add_run(_strip_md_inline(line[4:]))
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(10.0)
            run.font.color.rgb = RGBColor(25, 32, 44)
            continue

        if line.startswith(("- ", "* ", "• ")):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_before = Pt(0.5)
            p.paragraph_format.space_after = Pt(1.5)
            add_formatted_runs(p, line[2:], base_size=(9.2 if tpl == "compact" else 10.0))
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0.5)
        p.paragraph_format.space_after = Pt(2)
        add_formatted_runs(p, line, base_size=(9.2 if tpl == "compact" else 10.0))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_cover_letter_pdf(markdown_text: str, title: str = "Carta de Presentacion") -> bytes:
    """
    Generate a formal, beautifully proportioned single-page PDF for a cover letter.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 20, 20)
    pdf.set_title(title)

    reg_font, bold_font = _find_unicode_fonts()
    use_unicode = bool(reg_font and bold_font)
    font_family = "CVFont" if use_unicode else "Helvetica"

    if use_unicode:
        pdf.add_font("CVFont", "", reg_font)
        pdf.add_font("CVFont", "B", bold_font)

    pdf.add_page()

    def clean(s: str) -> str:
        s = _strip_md_inline(s)
        return s if use_unicode else _safe_latin1(s)

    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    effective_width = pdf.w - pdf.l_margin - pdf.r_margin

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            pdf.ln(3.5)
            continue

        pdf.set_x(pdf.l_margin)
        if line.startswith("# "):
            pdf.set_font(font_family, "B", 16)
            pdf.set_text_color(17, 24, 39)
            pdf.multi_cell(effective_width, 8.0, clean(line[2:]))
            pdf.ln(1.5)
            continue

        is_bold = (line.startswith("**") and line.endswith("**")) or line.startswith("Estimado") or line.startswith("Atentamente")
        pdf.set_font(font_family, "B" if is_bold else "", 10.5)
        pdf.set_text_color(31, 41, 55)
        pdf.multi_cell(effective_width, 5.8, clean(line))
        pdf.ln(1.0)

    out = pdf.output()
    return bytes(out)


def generate_cover_letter_docx(markdown_text: str, title: str = "Carta de Presentacion") -> bytes:
    """
    Generate a formal Word document (.docx) for a cover letter.
    """
    doc = Document()
    doc.core_properties.title = title

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)

        if line.startswith("# "):
            run = p.add_run(_strip_md_inline(line[2:]))
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(17)
            run.font.color.rgb = RGBColor(17, 24, 39)
        else:
            is_bold = (line.startswith("**") and line.endswith("**"))
            run = p.add_run(_strip_md_inline(line))
            run.bold = is_bold
            run.font.name = "Calibri"
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(31, 41, 55)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

