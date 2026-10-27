# cURL example

This Bash script creates one Run for the fixed TikTok Actor, waits for that Run,
then reads its Dataset. It requires Bash, `curl`, and Python 3 (standard library
only). It does not load `.env`.

From the repository root, set `APIFY_TOKEN` in your shell:

```bash
export APIFY_TOKEN='your_apify_token_here'
bash examples/curl/single-url-sync.sh
```

The default video URL is
`https://www.tiktok.com/@carter.braydon/video/7647694374876319007`. Replace it
with `--video-url`:

```bash
bash examples/curl/single-url-sync.sh --video-url 'https://www.tiktok.com/@user/video/1234567890'
```

The script uses one client-side POST attempt; this is not a server-side
exactly-once guarantee. If the create result is unknown, check Apify Console
before trying again. For long waits, use `start`, then continue with the same
Run ID using `wait --run-id RUN_ID`. Outputs are written to
`sample-output/generated/`.

See [QuickStart](../../docs/quick-start.md) for the complete command set and
[API reference](../../docs/api-reference.md) for response fields.
