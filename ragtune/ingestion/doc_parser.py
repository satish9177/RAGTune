"""Document parser to normalize SGML, RST, and Markdown into clean Markdown for chunking."""

from __future__ import annotations

import re


def parse_sgml_docbook(text: str) -> str:
    """Normalize DocBook SGML/XML (PostgreSQL) into clean structured Markdown."""
    # Convert titles
    text = re.sub(r"<title>\s*(.*?)\s*</title>", r"# \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    # Convert code listings
    text = re.sub(
        r'<programlisting[^>]*>\s*(.*?)\s*</programlisting>',
        r'```sql\n\1\n```\n',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Convert paragraphs
    text = re.sub(r"<para>\s*(.*?)\s*</para>", r"\1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    # Strip remaining SGML/XML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Clean multiple spaces and blank lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
    return text.strip()


def parse_rst(text: str) -> str:
    """Normalize reStructuredText (PyTorch) into clean structured Markdown."""
    lines = text.splitlines()
    md_lines = []
    i = 0
    in_code_block = False

    while i < len(lines):
        line = lines[i]

        # Check for code blocks
        if line.strip().startswith(".. code-block::") or line.strip().startswith(".. code::"):
            lang = line.strip().split("::")[-1].strip() or "python"
            md_lines.append(f"```{lang}")
            i += 1
            # Collect indented block
            code_lines = []
            while i < len(lines) and (lines[i].startswith("   ") or lines[i].strip() == ""):
                code_lines.append(lines[i][3:] if lines[i].startswith("   ") else "")
                i += 1
            md_lines.extend(code_lines)
            md_lines.append("```")
            continue

        # Check for RST title underlines: ===, ---, ~~~
        if i + 1 < len(lines) and len(lines[i + 1].strip()) >= 3:
            underline = lines[i + 1].strip()
            if all(c == "=" for c in underline) and len(underline) >= len(line.strip()):
                md_lines.append(f"# {line.strip()}")
                i += 2
                continue
            elif all(c == "-" for c in underline) and len(underline) >= len(line.strip()):
                md_lines.append(f"## {line.strip()}")
                i += 2
                continue
            elif all(c == "~" for c in underline) and len(underline) >= len(line.strip()):
                md_lines.append(f"### {line.strip()}")
                i += 2
                continue

        # Strip directives like .. note:: or .. warning::
        if line.strip().startswith(".. "):
            i += 1
            continue

        # Strip RST field lists/attributes like :class: hidden-section, :orphan:, etc.
        if re.match(r"^:[a-zA-Z0-9_-]+:(\s+.*)?$", line.strip()):
            i += 1
            continue

        md_lines.append(line)
        i += 1

    return "\n".join(md_lines).strip()


def normalize_to_markdown(raw_text: str, file_path: str) -> str:
    """Convert raw document text to normalized markdown based on file extension."""
    lower_path = file_path.lower()
    if lower_path.endswith((".sgml", ".xml")):
        return parse_sgml_docbook(raw_text)
    elif lower_path.endswith(".rst"):
        return parse_rst(raw_text)
    else:
        # Standard Markdown
        # Strip frontmatter if present (e.g. Hugo / Jekyll --- ... ---)
        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                raw_text = parts[2].strip()

        # Strip Hugo template comments and shortcode includes (scaffolding boilerplate)
        text = re.sub(r"<!--.*?-->", "", raw_text, flags=re.DOTALL)
        text = re.sub(r"\{\{[<%].*?[>%]\}\}", "", text)
        # Clean excessive newlines created by stripped tags
        text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
        return text.strip()
