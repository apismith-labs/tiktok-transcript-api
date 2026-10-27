package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.cdimascio.dotenv.Dotenv;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.time.Duration;

public final class SingleUrl {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private SingleUrl() {}

    public static void main(String[] args) {
        int exit = run(args, null);
        if (exit != 0) System.exit(exit);
    }

    static int run(String[] args, ApifyClient injected) {
        return run(args, injected, null);
    }

    static int run(String[] args, ApifyClient injected, Path requestedOutputDirectory) {
        try {
            Options options = parseOptions(args);
            String url = options.url();
            ApifyClient.validateVideoUrl(url);
            Path outputDirectory = requestedOutputDirectory != null
                    ? requestedOutputDirectory
                    : repoRoot().resolve("sample-output/generated");
            preflightOutputDirectory(outputDirectory);
            ApifyClient client = injected == null ? new ApifyClient(token()) : injected;
            System.out.println("Actor: " + ApifyClient.ACTOR_SLUG);
            System.out.println("Starting Run and waiting for completion (wait limit: " + options.maxWaitSeconds() + "s)...");
            JsonNode created = client.startRun(url);
            String runId = created.path("id").asText();
            System.out.println("Run ID: " + runId);
            System.out.flush();
            JsonNode run = client.waitForRun(runId, Duration.ofSeconds(options.maxWaitSeconds()), Duration.ofSeconds(3));
            String datasetId = run.path("defaultDatasetId").asText("");
            JsonNode items = datasetId.isBlank() ? null : client.getDatasetItems(datasetId);
            String failure = TranscriptResult.failure(run, items);
            if (items != null) save(items, outputDirectory);
            if (failure != null) {
                System.err.println(failure);
                return 1;
            }
            System.out.println("Transcript items: " + items.size());
            System.out.println("Transcript text: " + items.get(0).path("text").asText());
            return 0;
        } catch (ApifyClient.ApiException e) {
            System.err.println(ApifyClient.safe(e.getMessage()));
            if (e.outcomeUnknown()) System.err.println("Run creation outcome is unknown. Check Apify Console before retrying; do not create another Run. A single client send attempt does not guarantee server-side exactly-once execution.");
            else if (e.getMessage().contains("Wait time reached")) System.err.println("Use the same Run ID to wait again; do not start another Run.");
            return 1;
        } catch (Exception e) {
            System.err.println(ApifyClient.safe(e.getMessage()));
            return 1;
        }
    }

    static String parseUrl(String[] args) {
        return parseOptions(args).url();
    }

    static Options parseOptions(String[] args) {
        String url = null;
        long maxWait = ApifyClient.DEFAULT_MAX_WAIT.toSeconds();
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--video-url" -> {
                    if (i + 1 >= args.length || url != null) throw usageError();
                    url = args[++i];
                }
                case "--max-wait" -> {
                    if (i + 1 >= args.length) throw usageError();
                    maxWait = parseMaxWait(args[++i]);
                }
                default -> {
                    if (args[i].startsWith("--") || url != null) throw usageError();
                    url = args[i];
                }
            }
        }
        return new Options(url == null ? ApifyClient.DEFAULT_VIDEO_URL : url, maxWait);
    }

    private static long parseMaxWait(String value) {
        return ApifyClient.parseMaxWaitSeconds(value);
    }

    private static IllegalArgumentException usageError() {
        return new IllegalArgumentException("Usage: SingleUrl [--video-url URL] [--max-wait SECONDS] (or one positional URL)");
    }

    record Options(String url, long maxWaitSeconds) {}

    static String token() {
        Path root = repoRoot();
        Dotenv dotenv = Dotenv.configure().directory(root.toString()).ignoreIfMissing().load();
        String value = System.getenv("APIFY_TOKEN");
        if (value == null || value.isBlank()) value = dotenv.get("APIFY_TOKEN");
        if (value == null || value.isBlank()) throw new IllegalArgumentException("APIFY_TOKEN is required in the environment or .env.");
        return value;
    }

    static Path repoRoot() {
        Path current = Path.of("").toAbsolutePath().normalize();
        while (current != null) {
            if (Files.exists(current.resolve(".env.example")) && Files.exists(current.resolve("sample-data/tiktok-video-urls.csv"))) return current;
            current = current.getParent();
        }
        throw new IllegalStateException("Could not locate repository root.");
    }

    static void preflightOutputDirectory(Path directory) throws IOException {
        try {
            Files.createDirectories(directory);
            Path probe = Files.createTempFile(directory, ".tiktok-transcript-output-probe-", ".tmp");
            try {
                Files.delete(probe);
            } catch (IOException e) {
                try { Files.deleteIfExists(probe); } catch (IOException ignored) { }
                throw e;
            }
        } catch (IOException e) {
            throw new IOException("Output directory preflight failed for " + directory + ": " + e.getMessage(), e);
        }
    }

    private static void save(JsonNode items, Path outputDirectory) throws Exception {
        Path output = outputDirectory.resolve("java-single-url-response.json");
        Files.createDirectories(output.getParent());
        Files.writeString(output, MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(items) + "\n", StandardCharsets.UTF_8);
        System.out.println("Output path: " + output);
    }
}
