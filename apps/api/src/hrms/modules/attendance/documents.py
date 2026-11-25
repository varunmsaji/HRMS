"""Excel (.xlsx) and PDF files for the attendance exports and the employee monthly statement.

One `Table` (a title, a header row, rows, notes) is rendered three ways, so every format of one
report holds the same figures. Nothing a person typed can act as a formula or as markup: text goes
into a spreadsheet as a string (never as a formula), and into a PDF as plain table text and
escaped paragraphs. The default PDF font covers Latin text only; a name in another script is not
drawn faithfully there (use the CSV or Excel file for that).
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, TableStyle
from reportlab.platypus import Table as PdfTable

from hrms.core.errors.base import ValidationError

ExportFormat = Literal["csv", "xlsx", "pdf"]
Cell = str | int | float | None

CSV_MEDIA = "text/csv; charset=utf-8"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA = "application/pdf"
EXTENSIONS: dict[str, str] = {"csv": "csv", "xlsx": "xlsx", "pdf": "pdf"}
MEDIA: dict[str, str] = {"csv": CSV_MEDIA, "xlsx": XLSX_MEDIA, "pdf": PDF_MEDIA}

#: A PDF holds a page per ~35 rows; beyond this it is not a document anyone reads.
MAX_PDF_ROWS = 5_000

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[Cell]]
    #: One line under the title (a period, a person), and lines after the table (a legend).
    subtitle: str | None = None
    notes: list[str] = field(default_factory=list)
    #: A cell whose text is a key here is filled with that colour (a muster's status codes).
    highlight: dict[str, str] = field(default_factory=dict)
    #: Columns before this one are never highlighted (the name and code columns).
    highlight_from: int = 0
    #: Wide tables (a muster) are laid out sideways.
    landscape: bool = True


@dataclass(frozen=True)
class ExportFile:
    filename: str
    content: bytes
    media_type: str


def csv_text(value: Cell) -> str:
    """A cell as CSV text. Text that starts like a spreadsheet formula gets a leading apostrophe;
    numbers are written as they are, so a negative figure stays a figure."""
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return f"'{value}"
    return str(value)


def to_csv(table: Table) -> bytes:
    """RFC 4180 rows with CRLF, a leading BOM so Excel reads UTF-8, and the notes after a blank
    line."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([csv_text(h) for h in table.headers])
    for row in table.rows:
        writer.writerow([csv_text(c) for c in row])
    if table.notes:
        writer.writerow([])
        for note in table.notes:
            writer.writerow([csv_text(note)])
    return ("﻿" + out.getvalue()).encode("utf-8")


def _sheet_name(title: str) -> str:
    cleaned = "".join("-" if c in "[]:*?/\\" else c for c in title).strip("'") or "Report"
    return cleaned[:31]


def to_xlsx(table: Table) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None  # a new workbook always has its first sheet
    ws.title = _sheet_name(table.title)
    row_no = 1
    ws.cell(row=row_no, column=1, value=table.title).font = Font(bold=True, size=14)
    row_no += 1
    if table.subtitle:
        ws.cell(row=row_no, column=1, value=table.subtitle).font = Font(italic=True)
        row_no += 1
    row_no += 1
    header_row = row_no
    fill = PatternFill("solid", start_color="E8EEF7")
    for col, header in enumerate(table.headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.data_type = "s"
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = [min(len(h), 40) for h in table.headers]
    for row in table.rows:
        row_no += 1
        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=row_no, column=col, value=value)
            if isinstance(value, str):
                # Text is text: openpyxl would turn a string starting with "=" into a formula.
                cell.data_type = "s"
                widths[col - 1] = max(widths[col - 1], min(len(value), 40))
                colour = table.highlight.get(value)
                if colour and col - 1 >= table.highlight_from:
                    cell.fill = PatternFill("solid", start_color=colour)
                    cell.alignment = Alignment(horizontal="center")
            elif isinstance(value, int | float):
                widths[col - 1] = max(widths[col - 1], len(str(value)))
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = max(6, width + 2)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=min(3, len(table.headers) + 1))
    for note in table.notes:
        row_no += 2 if note is table.notes[0] else 1
        note_cell = ws.cell(row=row_no, column=1, value=note)
        note_cell.data_type = "s"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(table: Table) -> bytes:
    if len(table.rows) > MAX_PDF_ROWS:
        raise ValidationError(
            f"A PDF can hold at most {MAX_PDF_ROWS} rows. Narrow the dates or filters, "
            "or use the CSV or Excel file."
        )
    page = landscape(A4) if table.landscape else portrait(A4)
    margin = 12 * mm
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=table.title,
    )
    styles = getSampleStyleSheet()
    story: list[object] = [Paragraph(escape(table.title), styles["Title"])]
    if table.subtitle:
        story.append(Paragraph(escape(table.subtitle), styles["Normal"]))
    story.append(Spacer(1, 4 * mm))

    font, size = "Helvetica", 7.5
    data: list[list[str]] = [[str(h) for h in table.headers]]
    data += [["" if c is None else str(c) for c in row] for row in table.rows]
    available = page[0] - 2 * margin
    natural = [
        max(stringWidth(row[i], font, size) for row in data) + 8 for i in range(len(table.headers))
    ]
    scale = min(1.0, available / sum(natural)) if sum(natural) else 1.0
    col_widths = [w * scale for w in natural]
    pdf_table = PdfTable(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), font, size),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", size),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8FA")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9CED6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for r, row in enumerate(table.rows, start=1):
        for c, value in enumerate(row):
            colour = table.highlight.get(value) if isinstance(value, str) else None
            if colour and c >= table.highlight_from:
                style.append(("BACKGROUND", (c, r), (c, r), colors.HexColor(f"#{colour}")))
                style.append(("ALIGN", (c, r), (c, r), "CENTER"))
    pdf_table.setStyle(TableStyle(style))
    story.append(pdf_table)
    if table.notes:
        story.append(Spacer(1, 4 * mm))
        story += [Paragraph(escape(note), styles["Normal"]) for note in table.notes]
    doc.build(story)
    return out.getvalue()


def render(table: Table, fmt: ExportFormat, base_name: str) -> ExportFile:
    """The table as `fmt`, named `<base_name>.<ext>`."""
    content = {"csv": to_csv, "xlsx": to_xlsx, "pdf": to_pdf}[fmt](table)
    return ExportFile(f"{base_name}.{EXTENSIONS[fmt]}", content, MEDIA[fmt])
