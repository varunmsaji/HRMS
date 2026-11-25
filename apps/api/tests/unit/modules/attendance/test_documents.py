"""The shared builder behind the Excel, PDF and CSV exports: every format of one table holds the
same figures, and nothing a person typed can run as a formula or as markup."""

import io

import pytest
from openpyxl import load_workbook

from hrms.core.errors.base import ValidationError
from hrms.modules.attendance.documents import (
    MAX_PDF_ROWS,
    Table,
    csv_text,
    render,
    to_csv,
    to_pdf,
    to_xlsx,
)

TABLE = Table(
    title="Daily attendance",
    subtitle="2026-11-01 to 2026-11-30",
    headers=["Employee", "Code", "Worked (min)"],
    rows=[["Asha", "E1", 480], ["=SUM(1,2)", "E2", -5], ['Bala, "B"', None, 0]],
    notes=["Legend", "P = Present"],
)


def test_csv_has_a_bom_crlf_numbers_untouched_and_notes_after_a_blank_line() -> None:
    text = to_csv(TABLE).decode("utf-8")
    assert text.startswith("﻿Employee,Code,Worked (min)\r\n")
    lines = text.lstrip("﻿").split("\r\n")
    assert lines[1] == "Asha,E1,480"
    # Defused with a leading apostrophe and quoted for its comma; the negative number stays one.
    assert lines[2] == '"\'=SUM(1,2)",E2,-5'
    assert lines[3] == '"Bala, ""B""",,0'
    assert lines[4:7] == ["", "Legend", "P = Present"]


def test_csv_text_only_defuses_text() -> None:
    assert csv_text("-cmd") == "'-cmd" and csv_text("@x") == "'@x"
    assert csv_text(-5) == "-5" and csv_text(None) == "" and csv_text("Asha") == "Asha"


def test_xlsx_keeps_text_as_text_and_numbers_as_numbers() -> None:
    sheet = load_workbook(io.BytesIO(to_xlsx(TABLE))).active
    assert sheet is not None
    assert sheet.title == "Daily attendance"
    assert [c.value for c in sheet[4]] == [
        "Employee",
        "Code",
        "Worked (min)",
    ]  # title, subtitle, gap
    asha, hostile = sheet[5], sheet[6]
    assert asha[2].value == 480 and asha[2].data_type == "n"
    # A string that starts with "=" is stored as a string, never as a formula.
    assert hostile[0].value == "=SUM(1,2)" and hostile[0].data_type == "s"
    assert hostile[2].value == -5
    assert sheet.freeze_panes == "C5"


def test_xlsx_fills_highlighted_codes_but_not_the_name_columns() -> None:
    table = Table(
        title="Muster register",
        headers=["Employee", "Code", "2026-11-01"],
        rows=[["A", "A", "A"]],
        highlight={"A": "FFC7CE"},
        highlight_from=2,
    )
    row = load_workbook(io.BytesIO(to_xlsx(table))).active[4]  # type: ignore[index]
    assert row[0].fill.start_color.rgb != "00FFC7CE" and row[1].fill.start_color.rgb != "00FFC7CE"
    assert row[2].fill.start_color.rgb.endswith("FFC7CE")


def test_a_sheet_title_is_made_safe() -> None:
    table = Table(title="Late/early: [a]*b?" + "x" * 40, headers=["A"], rows=[])
    sheet = load_workbook(io.BytesIO(to_xlsx(table))).active
    assert sheet is not None and len(sheet.title) <= 31 and "/" not in sheet.title


def test_pdf_is_a_pdf_and_survives_hostile_text() -> None:
    table = Table(
        title="<b>Bold</b> & <script>",
        subtitle="<i>x</i>",
        headers=["Employee"],
        rows=[["<para><b>x</b></para>"], ["A & B"]],
        notes=["<br/>note"],
    )
    pdf = to_pdf(table)
    assert pdf.startswith(b"%PDF") and len(pdf) > 500


def test_a_wide_table_fits_the_page_and_a_huge_one_is_refused() -> None:
    wide = Table(
        title="Muster", headers=[f"2026-11-{d:02d}" for d in range(1, 32)], rows=[["x"] * 31]
    )
    assert to_pdf(wide).startswith(b"%PDF")
    huge = Table(title="Too big", headers=["A"], rows=[["x"]] * (MAX_PDF_ROWS + 1))
    with pytest.raises(ValidationError):
        to_pdf(huge)


def test_render_names_and_types_each_format() -> None:
    assert render(TABLE, "csv", "daily").filename == "daily.csv"
    xlsx = render(TABLE, "xlsx", "daily")
    assert xlsx.media_type.endswith("spreadsheetml.sheet") and xlsx.filename == "daily.xlsx"
    pdf = render(TABLE, "pdf", "daily")
    assert pdf.media_type == "application/pdf" and pdf.content.startswith(b"%PDF")
