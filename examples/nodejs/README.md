# Node.js example

Requires Node.js 20.12+. The example uses Node.js built-ins and has no
third-party runtime dependencies. It loads `.env` from the repository root;
existing process environment values take precedence. Only `APIFY_TOKEN` is
configurable; the Actor is fixed in code.

From the repository root, set `APIFY_TOKEN` in the shell or copy
`.env.example` to `.env`, then run:

```bash
node examples/nodejs/single-url.mjs
node examples/nodejs/single-url.mjs --video-url 'https://www.tiktok.com/@user/video/1234567890'
node examples/nodejs/single-url.mjs --max-wait 1200
node examples/nodejs/async-run.mjs start
node examples/nodejs/async-run.mjs wait --run-id RUN_ID --max-wait 900
node examples/nodejs/csv-batch.mjs sample-data/tiktok-video-urls.csv --concurrency 2 --max-wait 900
node examples/nodejs/csv-batch.mjs --reconcile
```

The default video URL is
`https://www.tiktok.com/@carter.braydon/video/7647694374876319007`. Generated
results are written under `sample-output/generated/`. Run creation makes one
client-side POST attempt, not an exactly-once guarantee. Check Apify Console if
the result is unknown; after a wait timeout, use the same Run ID.
Single-video and async `wait` commands default to a 900-second wait limit;
`--max-wait SECONDS` accepts values from 1 to 86400.

Offline tests: `npm --prefix examples/nodejs test`.
