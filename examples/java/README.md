# Java example

Requires JDK 17 and Maven. Maven dependencies are declared in
`examples/java/pom.xml`. The program reads `APIFY_TOKEN` from the process
environment first, then the repository-root `.env`; the Actor ID is fixed.

From the repository root, set `APIFY_TOKEN` or copy `.env.example` to `.env`.

Single video (default URL or explicit `--video-url`):

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl compile exec:java
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.SingleUrl -Dexec.args="--video-url https://www.tiktok.com/@user/video/1234567890" compile exec:java
```

Async and CSV commands:

```bash
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.AsyncRun -Dexec.args="start" compile exec:java
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.AsyncRun -Dexec.args="wait --run-id RUN_ID --max-wait 900" compile exec:java
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.CsvBatch -Dexec.args="--csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/java-csv-batch-results.jsonl --concurrency 2 --max-wait 900" compile exec:java
mvn -f examples/java/pom.xml -Dexec.mainClass=com.apismith.tiktok.CsvBatch -Dexec.args="--csv sample-data/tiktok-video-urls.csv --journal sample-output/generated/java-csv-batch-results.jsonl --reconcile" compile exec:java
```

The default video URL is
`https://www.tiktok.com/@carter.braydon/video/7647694374876319007`. Run
creation sends one client-side POST attempt, not an exactly-once guarantee. If
the result is unknown, check Apify Console before retrying; after a wait timeout
continue with the same Run ID.

Offline tests: `mvn -o -f examples/java/pom.xml test` (requires cached Maven
dependencies).
