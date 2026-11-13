from io import BytesIO
import hashlib
from pathlib import Path
from zipfile import ZipFile

MAX_FILE = 10 * 1024 * 1024
MAX_OFFICE_EXPANSION = 40 * 1024 * 1024
MAX_LOCATIONS = 20_000
MAX_CHARS = 500_000


def load_material(root, path, expected_sha256):
    root = Path(root).resolve(strict=True)
    path = (root / path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Material must be a registered file inside the data directory.")
    with path.open("rb") as source:
        content = source.read(MAX_FILE + 1)
    if len(content) > MAX_FILE:
        raise ValueError("Material exceeds the file size limit.")
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Material digest differs from its manifest.")
    suffix = path.suffix.lower()
    if suffix in {".docx", ".xlsx"}:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(item.file_size for item in entries) > MAX_OFFICE_EXPANSION:
                raise ValueError("Office material exceeds expansion limits.")
    if suffix == ".pdf":
        from pypdf import PdfReader

        pdf = PdfReader(BytesIO(content))
        if pdf.is_encrypted or len(pdf.pages) > 100:
            raise ValueError("PDF must be unencrypted and at most 100 pages.")
        for number, page in enumerate(pdf.pages, 1):
            yield f"page:{number}", page.extract_text() or ""
    elif suffix == ".docx":
        from docx import Document

        document = Document(BytesIO(content))
        for number, paragraph in enumerate(document.paragraphs, 1):
            yield f"paragraph:{number}", paragraph.text
        for number, table in enumerate(document.tables, 1):
            for row_number, row in enumerate(table.rows, 1):
                for column, cell in enumerate(row.cells, 1):
                    yield f"table:{number}:r{row_number}c{column}", cell.text
    elif suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
        try:
            for sheet in workbook.worksheets:
                if sheet.max_row is None or sheet.max_column is None or (
                    sheet.max_row * sheet.max_column > MAX_LOCATIONS
                ):
                    raise ValueError("Worksheet must have bounded dimensions.")
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            yield f"cell:{sheet.title}!{cell.coordinate}", str(cell.value)
        finally:
            workbook.close()
    elif suffix in {".txt", ".md"}:
        for number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
            yield f"line:{number}", line
    else:
        raise ValueError("Unsupported material format.")


def extract_material(root, spec):
    result = {}
    characters = 0
    for index, (location, value) in enumerate(load_material(root, spec.path, spec.sha256), 1):
        characters += len(value)
        if index > MAX_LOCATIONS or characters > MAX_CHARS:
            raise ValueError("Material exceeds extraction limits.")
        if value.strip():
            result[location] = value
    if not result:
        raise ValueError("No extractable text or cached cell values.")
    return result
