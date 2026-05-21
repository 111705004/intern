# NUS Finance Internship Tracker

A small local web app for tracking finance internships, VC firms, key people, and startup/VC events.

## Run locally

```bash
cd ~/Desktop/intern-app
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open `index.html` in your browser.

## Notes

- The Key People page is now fully non-AI. It does not call OpenAI, Claude, or any paid AI API.
- The Events page still calls your FastAPI backend `/events`, which uses public search scraping logic from `main.py`.
- Keep API keys out of this repository.
