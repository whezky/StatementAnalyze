# Card Statement Analyzer

This version uses a  Python parsing architecture instead of the older browser-only PDF parser.

## Run Locally

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Deploy

Use a Python-capable host such as Streamlit Community Cloud, Render, Railway, Fly.io, or a VPS. Cloudflare Pages alone cannot run this parser because it needs Python PDF libraries and optional OCR tooling.

For Streamlit Community Cloud, deploy this folder and set `app.py` as the entrypoint. `packages.txt` lists Linux system packages needed by Poppler/OCR dependencies.

## Privacy

Uploaded files are processed in memory and are not written to disk by the app.
