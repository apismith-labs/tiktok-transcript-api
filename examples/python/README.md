# Python example

Requires Python 3.11+. The scripts use `apify-client==3.3.0`; `python-dotenv`
loads `.env` from the repository root. The shell environment takes precedence
over `.env`. Only `APIFY_TOKEN` is configurable; the Actor is fixed in code.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r examples/python/requirements.txt
cp .env.example .env
```

Set `APIFY_TOKEN` in `.env` or the process environment. The default video URL
is `https://www.tiktok.com/@carter.braydon/video/7647694374876319007`.

```bash
python3 examples/python/single_url.py
python3 examples/python/single_url.py --video-url 'https://www.tiktok.com/@user/video/1234567890'
python3 examples/python/async_run.py start
python3 examples/python/async_run.py wait --run-id RUN_ID --max-wait 900
python3 examples/python/csv_batch.py sample-data/tiktok-video-urls.csv --concurrency 2 --max-wait 900
python3 examples/python/csv_batch.py --reconcile
```

Single and batch outputs are written under `sample-output/generated/`. Run
creation is one client-side POST attempt, not an exactly-once guarantee. If its
result is unknown, check Apify Console before starting another Run; after a
wait timeout, continue with the same Run ID.
