# Card Statement Analyzer

This version uses a Python parsing architecture instead of the older browser-only PDF parser.

The Streamlit deployment installs `monopoly-core` for StatementSensei-style bank detection and falls back to the built-in `pypdf` parser if the full parser cannot handle a file.

## Run Locally

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Use a Python-capable host such as Streamlit Community Cloud, Render, Railway, Fly.io, or a VPS. Cloudflare Pages alone cannot run this parser because it needs Python.

For Streamlit Community Cloud, deploy this folder and set `app.py` as the entrypoint. `requirements.txt` installs the Python parser stack, and `packages.txt` installs the native Linux packages needed by `pdftotext` and OCR support.

If Streamlit Cloud shows "Error running app", open **Manage app > Logs** first. Most deployment failures are dependency install errors from either `requirements.txt` or `packages.txt`.

## Lightweight Fallback Option

If the full parser dependencies are too heavy for a host, remove `monopoly-core`, `pdftotext`, `pymupdf`, `pydantic`, and `pydantic-settings` from `requirements.txt`, then empty `packages.txt`. The app will still run with the simpler `pypdf` fallback parser.

## Privacy

Uploaded files are processed in memory and are not written to disk by the app.
