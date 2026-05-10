# Troubleshooting

Use this guide when a TikTok Transcript API example does not return the expected
result.

## Missing `APIFY_TOKEN`

The examples require `APIFY_TOKEN`.

Fix:

```bash
cp .env.example .env
```

Then edit `.env` and set a real token:

```bash
APIFY_TOKEN=your_apify_token_here
```

## Invalid Apify token

Symptoms may include HTTP `401`, HTTP `403`, or an authentication error from
the Apify API.

Fix:

- Confirm the token is copied from your Apify account.
- Confirm the token has not expired or been revoked.
- Make sure your shell environment is not overriding `.env` with an old value.

## Actor run failed

The examples report a non-success Actor status when Apify returns `FAILED`,
`TIMED-OUT`, or `ABORTED`.

Fix:

- Open the run in Apify Console if you have the run ID.
- Check the Actor log for the exact failure reason.
- Retry once if the error looks temporary.
- Try another public TikTok video URL.

## Empty dataset results

An empty dataset means the Actor run finished but no dataset items were returned.

Fix:

- Check the raw run and dataset in Apify Console.
- Confirm the input URL is correct.
- Try the cURL example with the default sample URL.
- Review whether the Actor returned logs explaining why no item was saved.

## TikTok video unavailable

A video may be deleted, restricted, unavailable in some regions, or otherwise
not accessible to the Actor.

Fix:

- Test a known public video URL.
- Confirm the URL opens in a browser.
- Record the failed URL in your batch output for later review.

## Transcript not available for a specific video

Transcript availability can vary by video. Some videos may return metadata but
little or no transcript text.

Fix:

- Preserve the raw Actor result.
- Check `errMsg` when present.
- Treat empty `text` as an input-specific outcome your application should
  handle.

## Timeout while waiting for the Actor run

Direct HTTP examples poll the Actor run until it finishes. Long runs can exceed
the example timeout.

Fix:

- Retry the request.
- Reduce batch concurrency in your own batch workflow.
- Inspect the run in Apify Console.
- For production, store run IDs and resume polling later.

## Environment variables not loaded

If `.env` values are not taking effect, the example may be running from an
unexpected directory or your shell may already define a different value.

Fix:

- Run examples from the repository root unless the example README says
  otherwise.
- Print your shell value with `echo "$APIFY_ACTOR_ID"` if needed.
- Recreate `.env` from `.env.example`.

## Generated output files not appearing

Examples write full responses under `sample-output/generated/`.

Fix:

- Confirm the example finished without errors.
- Check the exact output path printed by the example.
- Confirm the process has permission to create files in the repository.
- Remember that `sample-output/generated/` is ignored by Git.

## Inspect raw Apify results

For deeper debugging:

1. Note the Actor run ID printed or returned by your integration.
2. Open Apify Console.
3. Inspect the run status and logs.
4. Open the default dataset for that run.
5. Compare the raw dataset item to the fields your code expects.

During early integration, save the complete dataset response before adding
strict parsing logic.
