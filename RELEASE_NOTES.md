# Release notes

## v1.0.0 draft

Initial example repository for the Apify Actor
[`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper).

The repository provides cURL, Python, Node.js, Java, Go, and Rust examples for
single-video requests. Each Run receives one `videoUrl` string. The language
directories also include separate Run start/wait and client-side CSV batch
flows, plus offline tests that use fake transports rather than the Apify API.

All sample runtime output is written under the Git-ignored
`sample-output/generated/` directory. No live Run output is committed as a
fixture.
