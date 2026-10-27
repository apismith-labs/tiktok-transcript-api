# Release notes

## v1.1.0

Expanded the repository into runnable integration examples for the fixed Apify
Actor [`apple_yang/tiktok-transcripts-scraper`](https://apify.com/apple_yang/tiktok-transcripts-scraper)
in cURL, Python, Node.js, Java, Go, and Rust.

The examples cover single-video calls with one `videoUrl` per Run, separate
Run start and wait flows, and client-side CSV batch processing. Offline tests
exercise request and result handling with fake transports without calling the
Apify API.

Generated runtime output is written under the Git-ignored
`sample-output/generated/` directory; no live Run output is committed as a
fixture.
