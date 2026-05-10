# Use TikTok Transcript API with Java

This example calls the Apify Actor `apple_yang/tiktok-transcripts-scraper`
with OkHttp, Jackson, and dotenv-java.

## Requirements

- Java 17
- Maven

## Setup

From the repository root:

```bash
cp .env.example .env
mvn -f examples/java/pom.xml compile
```

Set `APIFY_TOKEN` in `.env` or your shell environment.

## Run

```bash
mvn -f examples/java/pom.xml exec:java -Dexec.mainClass=com.apismith.tiktok.SingleUrl
```

You can also pass a URL directly:

```bash
mvn -f examples/java/pom.xml exec:java -Dexec.mainClass=com.apismith.tiktok.SingleUrl -Dexec.args="https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
```

The full response is saved to:

```text
sample-output/generated/java-single-url-response.json
```
