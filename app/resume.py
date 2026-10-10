"""Resume file -> plain text (.pdf, .docx, .txt).

Kept free of any web framework so it can be unit-tested on its own.
"""
import io


def _docx_text(data: bytes) -> str:
    """Text of a .docx in reading order: paragraphs AND tables exactly where
    they appear. (Reading all paragraphs first and tables afterwards pushes a
    'Technical Skills' table to the very bottom of the resume.) A table row
    becomes one line, e.g. 'Languages: Java, Python, SQL'."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    lines: list[str] = []

    def walk(container_element, parent):
        for child in container_element.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                lines.append(Paragraph(child, parent).text)
            elif tag == "tbl":
                table = Table(child, parent)
                for row in table.rows:
                    seen, cells = set(), []
                    for cell in row.cells:
                        if id(cell._tc) in seen:  # merged cells repeat
                            continue
                        seen.add(id(cell._tc))
                        t = " ".join(p.text.strip() for p in cell.paragraphs
                                     if p.text.strip())
                        if t:
                            cells.append(t)
                    if cells:
                        lines.append(" ".join(cells))

    walk(doc.element.body, doc)
    return "\n".join(lines)


def parse(filename: str, data: bytes) -> str:
    """Return the text of a resume. Raises ValueError for an unsupported
    extension; other exceptions mean the file is damaged / protected."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == "docx":
        return _docx_text(data)
    if ext == "txt":
        return data.decode("utf-8", "ignore")
    raise ValueError("unsupported file type (use .pdf, .docx, or .txt)")
