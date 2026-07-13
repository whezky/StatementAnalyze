# Card Statement Analyzer

This version uses a Python parsing architecture instead of the older browser-only PDF parser.

The default deployment is lightweight for Streamlit Community Cloud and uses the built-in `pypdf` fallback parser. A full StatementSensei-style dependency set is kept in `requirements-full.txt` for Python hosts that can install Poppler/OCR/native PDF dependencies reliably.

## Run Locally

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Use a Python-capable host such as Streamlit Community Cloud, Render, Railway, Fly.io, or a VPS. Cloudflare Pages alone cannot run this parser because it needs Python.

For Streamlit Community Cloud, deploy this folder and set `app.py` as the entrypoint.

If Streamlit Cloud shows "Error running app", open **Manage app > Logs** first. Most deployment failures are dependency install errors. The default `requirements.txt` intentionally avoids heavy native PDF/OCR packages so the app can start reliably.

## Full Parser Option

For a host that supports native packages, use `requirements-full.txt` and uncomment the packages listed in `packages.txt`. This enables the StatementSensei-style `monopoly-core` path where available.

## Privacy

Uploaded files are processed in memory and are not written to disk by the app.
