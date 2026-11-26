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


def generate_ats_pdf(markdown_text: str, title: str = "Curriculum Vitae") -> bytes:
    """
    Generate a clean, single-column, selectable-text ATS-friendly PDF from Markdown CV.
    Zero hidden tables or images so every ATS parser extracts 100% of the text accurately.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(16, 15, 16)
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

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            pdf.ln(2.5)
            continue

        if line.startswith("# "):
            ensure_x()
            pdf.set_font(font_family, "B", 18)
            pdf.set_text_color(18, 35, 64)
            pdf.multi_cell(effective_width, 8.5, clean(line[2:]))
            pdf.ln(1)
            continue

        if line.startswith("## "):
            pdf.ln(2.5)
            ensure_x()
            pdf.set_font(font_family, "B", 11.5)
            pdf.set_text_color(30, 64, 128)
            pdf.multi_cell(effective_width, 6.2, clean(line[3:]).upper())
            y = pdf.get_y()
            pdf.set_draw_color(195, 208, 228)
            pdf.set_line_width(0.35)
            pdf.line(pdf.l_margin, y + 0.5, pdf.w - pdf.r_margin, y + 0.5)
            pdf.ln(2.5)
            continue

        if line.startswith("### "):
            pdf.ln(1.2)
            ensure_x()
            pdf.set_font(font_family, "B", 10.5)
            pdf.set_text_color(28, 35, 48)
            pdf.multi_cell(effective_width, 5.6, clean(line[4:]))
            continue

        if line.startswith(("- ", "* ", "• ")):
            bullet_text = clean(line[2:])
            bullet_char = "•" if use_unicode else "-"
            pdf.set_font(font_family, "", 9.8)
            pdf.set_text_color(38, 44, 54)
            ensure_x()
            pdf.cell(4.5, 5.1, bullet_char)
            pdf.multi_cell(effective_width - 4.5, 5.1, bullet_text)
            pdf.ln(0.5)
            continue

        if re.match(r"^[-_*]{3,}$", line):
            y = pdf.get_y() + 1.5
            pdf.set_draw_color(210, 218, 230)
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3.5)
            continue

        # Regular paragraph or contact/subtitle line
        ensure_x()
        is_bold_line = line.startswith("**") and line.endswith("**") and line.count("**") == 2
        pdf.set_font(font_family, "B" if is_bold_line else "", 9.8)
        pdf.set_text_color(42, 48, 58)
        pdf.multi_cell(effective_width, 5.2, clean(line))
        pdf.ln(0.5)

    out = pdf.output()
    return bytes(out)


def generate_ats_docx(markdown_text: str, title: str = "Curriculum Vitae") -> bytes:
    """
    Generate a clean, single-column ATS-friendly Word document (.docx) from Markdown CV.
    """
    doc = Document()
    doc.core_properties.title = title

    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.7)
        section.right_margin = Inches(0.7)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(10.5)
    normal_style.font.color.rgb = RGBColor(38, 44, 54)

    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")

    def add_formatted_runs(paragraph, text: str, base_size: float = 10.5, base_color=RGBColor(38, 44, 54)):
        # Parse **bold** inline segments cleanly
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

    for raw_line in lines:
        line = raw_line.strip()
        if not line or re.match(r"^[-_*]{3,}$", line):
            continue

        if line.startswith("# "):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(3)
            run = p.add_run(_strip_md_inline(line[2:]))
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(19)
            run.font.color.rgb = RGBColor(18, 35, 64)
            continue

        if line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(3)
            run = p.add_run(_strip_md_inline(line[3:]).upper())
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(11.5)
            run.font.color.rgb = RGBColor(30, 64, 128)
            continue

        if line.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(_strip_md_inline(line[4:]))
            run.bold = True
            run.font.name = "Calibri"
            run.font.size = Pt(10.8)
            run.font.color.rgb = RGBColor(25, 32, 44)
            continue

        if line.startswith(("- ", "* ", "• ")):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2)
            add_formatted_runs(p, line[2:], base_size=10.2)
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(3)
        add_formatted_runs(p, line, base_size=10.2)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
