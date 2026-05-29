"""scripts package — pipeline entry points for daily-trends.

Loads `.env` once at package import so any `python -m scripts.X` invocation
sees the env vars consumers expect (e.g. `BRIGHT_DATA_KEY` in
`scripts.lib.bright_data`). Silent no-op if `.env` is absent — production
deployments can export env vars directly.
"""

from dotenv import load_dotenv

load_dotenv()
