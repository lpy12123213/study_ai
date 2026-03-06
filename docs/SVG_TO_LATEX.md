# SVG to LaTeX

This project can convert generated SVG-style math or diagram output into LaTeX-friendly content during export flows.

## When to use it

- You generated study material or a paper export and the formula/diagram did not render cleanly in LaTeX.
- You want to keep the final export editable in `.tex`.

## Current workflow

1. Generate or export content from the app.
2. If the output contains SVG-like formula fragments, run the Markdown to LaTeX conversion flow from the study-materials page.
3. Review the generated `.tex` file before compiling to PDF.

## Notes

- The media proxy blocks remote SVG payloads by default for security reasons.
- Complex diagrams may still need manual cleanup in the exported `.tex`.
- If conversion fails partway through, the backend returns a partial result when possible so you can continue editing manually.

## Related files

- `backend/agent/tools/latex_export.py`
- `backend/api/media.py`
- `backend/api/study_materials.py`
