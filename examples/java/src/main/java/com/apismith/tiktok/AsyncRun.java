package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Duration;

/** Demonstrates creating a Run separately from waiting for an existing Run. */
public final class AsyncRun {
    private AsyncRun() {}

    public static void main(String[] args) {
        int exit = run(args, null);
        if (exit != 0) System.exit(exit);
    }

    static int run(String[] args, ApifyClient injected) {
        try {
            if (args.length == 0) throw new IllegalArgumentException("Usage: AsyncRun start [--video-url URL] | wait --run-id ID [--max-wait SECONDS]");
            ApifyClient client = injected == null ? new ApifyClient(SingleUrl.token()) : injected;
            if ("start".equals(args[0])) {
                String url = ApifyClient.DEFAULT_VIDEO_URL;
                if (args.length == 3 && "--video-url".equals(args[1])) url = args[2];
                else if (args.length != 1) throw new IllegalArgumentException("Usage: AsyncRun start [--video-url URL]");
                ApifyClient.validateVideoUrl(url);
                System.out.println("Actor: " + ApifyClient.ACTOR_SLUG);
                System.out.flush();
                JsonNode run = client.startRun(url);
                System.out.println("Run ID: " + run.path("id").asText());
                System.out.println("Run started. Later, use: AsyncRun wait --run-id " + run.path("id").asText());
                return 0;
            }
            if (!"wait".equals(args[0])) throw new IllegalArgumentException("Expected 'start' or 'wait'.");
            WaitOptions options = parseWaitArgs(args);
            JsonNode run = client.waitForRun(options.runId(), Duration.ofSeconds(options.maxWaitSeconds()), Duration.ofSeconds(2));
            if (!"SUCCEEDED".equals(run.path("status").asText())) throw new IllegalStateException("Run finished with status " + run.path("status").asText());
            String datasetId = run.path("defaultDatasetId").asText("");
            if (datasetId.isBlank()) throw new IllegalStateException("Run succeeded without a Dataset ID.");
            JsonNode items = client.getDatasetItems(datasetId);
            String failure = TranscriptResult.failure(run, items);
            if (failure != null) throw new IllegalStateException(failure);
            System.out.println("Transcript text: " + items.get(0).path("text").asText());
            return 0;
        } catch (ApifyClient.ApiException e) {
            System.err.println(ApifyClient.safe(e.getMessage()));
            if (e.outcomeUnknown()) System.err.println("Run creation outcome is unknown. Check Apify Console before retrying. One client send attempt is not server-side exactly-once.");
            else if (e.getMessage().contains("Wait time reached")) System.err.println("The Run may still be running; use the same Run ID with wait again.");
            return 1;
        } catch (Exception e) {
            System.err.println(ApifyClient.safe(e.getMessage()));
            return 1;
        }
    }

    /** Parses {@code wait} arguments: args[0] is the subcommand. */
    static WaitOptions parseWaitArgs(String[] args) {
        String runId = null;
        long maxWait = ApifyClient.DEFAULT_MAX_WAIT.toSeconds();
        for (int i = 1; i < args.length; i++) {
            if ("--run-id".equals(args[i]) && i + 1 < args.length) runId = args[++i];
            else if (("--max-wait".equals(args[i]) || "--max-wait-seconds".equals(args[i])) && i + 1 < args.length) {
                maxWait = ApifyClient.parseMaxWaitSeconds(args[++i]);
            } else throw new IllegalArgumentException("Usage: AsyncRun wait --run-id ID [--max-wait SECONDS]");
        }
        if (runId == null) throw new IllegalArgumentException("wait requires a Run ID.");
        return new WaitOptions(runId, maxWait);
    }

    record WaitOptions(String runId, long maxWaitSeconds) {}
}
