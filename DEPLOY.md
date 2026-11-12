# Deploying DRISHTI-lite (Streamlit Community Cloud, free)

1. `data/signal_log_seed.json` must exist (Signal log screen → JSON button), so the live app shows the documented examples.
2. Push the project to a GitHub repository (see the steps in chat).
3. On https://share.streamlit.io → Create app → choose the repository, branch `main`, main file `app.py`.
   Advanced settings: Python 3.12; Secrets: `OPENFDA_API_KEY = "your-key"`.
4. Hosted storage is temporary: the cache, extraction records and any new log entries are reset when
   the app restarts. The signal log reloads from `data/signal_log_seed.json` each time.
