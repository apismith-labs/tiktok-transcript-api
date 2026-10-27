package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

import java.io.IOException;
import java.net.URI;
import java.time.Duration;
import java.util.Locale;

/** Apify HTTP operations for the one supported TikTok transcript Actor. */
public final class ApifyClient {
    public static final String ACTOR_API_ID = "apple_yang~tiktok-transcripts-scraper";
    public static final String ACTOR_SLUG = "apple_yang/tiktok-transcripts-scraper";
    public static final String API_BASE = "https://api.apify.com/v2";
    public static final String DEFAULT_VIDEO_URL =
            "https://www.tiktok.com/@carter.braydon/video/7647694374876319007";
    /** Per-Run wait limit used when the CLI is not given an explicit --max-wait. */
    public static final Duration DEFAULT_MAX_WAIT = Duration.ofSeconds(900);
    public static final long MAX_MAX_WAIT_SECONDS = 86_400;
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final ObjectMapper MAPPER = new ObjectMapper();

    @FunctionalInterface
    public interface Transport {
        ApiResponse send(String method, URI uri, String authorization, String body) throws IOException;
    }

    public record ApiResponse(int statusCode, String body) {}

    public static final class ApiException extends Exception {
        private final boolean outcomeUnknown;
        public ApiException(String message, boolean outcomeUnknown) {
            super(message);
            this.outcomeUnknown = outcomeUnknown;
        }
        public ApiException(String message, boolean outcomeUnknown, Throwable cause) {
            super(message, cause);
            this.outcomeUnknown = outcomeUnknown;
        }
        public boolean outcomeUnknown() { return outcomeUnknown; }
    }

    private final String token;
    private final Transport transport;

    public ApifyClient(String token) {
        this(token, new OkHttpTransport());
    }

    public ApifyClient(String token, Transport transport) {
        if (token == null || token.isBlank()) throw new IllegalArgumentException("APIFY_TOKEN is required.");
        this.token = token;
        this.transport = transport;
    }

    public static void validateVideoUrl(String value) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Video URL is required.");
        try {
            URI uri = URI.create(value.trim());
            String host = uri.getHost();
            String path = uri.getPath();
            if (!"https".equalsIgnoreCase(uri.getScheme()) || host == null
                    || !(host.equalsIgnoreCase("tiktok.com") || host.toLowerCase(Locale.ROOT).endsWith(".tiktok.com"))
                    || path == null || !path.matches("/@[^/]+/video/[0-9]+/?")) {
                throw new IllegalArgumentException("Expected a TikTok video URL like https://www.tiktok.com/@user/video/123.");
            }
        } catch (IllegalArgumentException e) {
            if (e.getMessage() != null && e.getMessage().startsWith("Expected a TikTok")) throw e;
            throw new IllegalArgumentException("Expected a valid TikTok video URL.");
        }
    }

    public JsonNode startRun(String videoUrl) throws ApiException {
        validateVideoUrl(videoUrl);
        ObjectNode input = MAPPER.createObjectNode().put("videoUrl", videoUrl.trim());
        String path = "/actors/" + ACTOR_API_ID + "/runs";
        ApiResponse response;
        try {
            // One client send attempt only. This does not provide server-side exactly-once semantics.
            response = transport.send("POST", URI.create(API_BASE + path), "Bearer " + token, input.toString());
        } catch (Exception e) {
            throw new ApiException("Run creation outcome is unknown. Check Apify Console before retrying. " + safeDetail(e.getMessage()), true, e);
        }
        if (response == null) {
            throw new ApiException("Run creation outcome is unknown because no HTTP response was available. Check Apify Console before retrying.", true);
        }
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new ApiException("Run creation outcome is unknown (HTTP " + response.statusCode() + "). Check Apify Console before retrying.", true);
        }
        try {
            JsonNode envelope = MAPPER.readTree(response.body());
            JsonNode data = envelope != null && envelope.isObject() ? envelope.get("data") : null;
            JsonNode id = data != null && data.isObject() ? data.get("id") : null;
            if (id == null || !id.isTextual() || id.asText().isBlank()) throw new IOException("response data.id is missing or invalid");
            return data;
        } catch (Exception e) {
            throw new ApiException("Run creation outcome is unknown because Apify returned an invalid response. Check Apify Console before retrying. " + safeDetail(e.getMessage()), true, e);
        }
    }

    public JsonNode getRun(String runId) throws ApiException {
        if (runId == null || !runId.matches("[A-Za-z0-9_-]+")) throw new ApiException("Invalid Run ID.", false);
        ApiResponse response;
        try { response = get("/actor-runs/" + runId); }
        catch (ApiException e) {
            if (e.getMessage().contains("HTTP 404")) throw new ApiException("Run " + runId + " was not found (HTTP 404).", false, e);
            throw e;
        }
        try {
            JsonNode root = MAPPER.readTree(response.body());
            JsonNode data = root != null && root.isObject() ? root.get("data") : null;
            if (data == null || !data.isObject()) throw new IOException("response data must be an object");
            JsonNode id = data.get("id");
            JsonNode status = data.get("status");
            // Any non-empty textual status is accepted: Apify adds transitional states over
            // time (for example ABORTING or TIMING-OUT), and only isTerminal() may stop a wait.
            if (id == null || !id.isTextual() || !runId.equals(id.asText())
                    || status == null || !status.isTextual() || status.asText().isBlank()) {
                throw new IOException("Run ID or status is missing or inconsistent");
            }
            return data;
        } catch (Exception e) {
            throw new ApiException("Invalid Run API response: " + safeDetail(e.getMessage()), false, e);
        }
    }

    public JsonNode waitForRun(String runId, Duration maxWait, Duration pollInterval) throws ApiException, InterruptedException {
        validateMaxWait(maxWait);
        if (pollInterval == null || pollInterval.isZero() || pollInterval.isNegative()) {
            throw new ApiException("Wait duration and polling interval must be positive.", false);
        }
        long deadline = System.nanoTime() + maxWait.toNanos();
        while (true) {
            JsonNode run = getRun(runId);
            String status = run.path("status").asText();
            if (isTerminal(status)) return run;
            long remaining = deadline - System.nanoTime();
            if (remaining <= 0) throw new ApiException("Wait time reached; Run may still be running (status: " + status
                    + "). Use the same Run ID to wait again: " + runId, false);
            Thread.sleep(Math.min(pollInterval.toMillis(), Math.max(1, remaining / 1_000_000)));
        }
    }

    public static long parseMaxWaitSeconds(String value) {
        final long seconds;
        try { seconds = Long.parseLong(value); }
        catch (NumberFormatException e) {
            throw new IllegalArgumentException("--max-wait must be a whole number of seconds.");
        }
        if (seconds < 1 || seconds > MAX_MAX_WAIT_SECONDS) {
            throw new IllegalArgumentException("--max-wait must be between 1 and " + MAX_MAX_WAIT_SECONDS + " seconds.");
        }
        return seconds;
    }

    public static void validateMaxWait(Duration maxWait) {
        if (maxWait == null || maxWait.compareTo(Duration.ofSeconds(1)) < 0
                || maxWait.compareTo(Duration.ofSeconds(MAX_MAX_WAIT_SECONDS)) > 0) {
            throw new IllegalArgumentException("Wait limit must be between 1 and " + MAX_MAX_WAIT_SECONDS + " seconds.");
        }
    }

    public JsonNode getDatasetItems(String datasetId) throws ApiException {
        if (datasetId == null || !datasetId.matches("[A-Za-z0-9_-]+")) throw new ApiException("Invalid Dataset ID.", false);
        ApiResponse response = get("/datasets/" + datasetId + "/items");
        try {
            JsonNode items = MAPPER.readTree(response.body());
            if (items == null || !items.isArray()) throw new IOException("Dataset Items response must be an array");
            return items;
        } catch (Exception e) {
            throw new ApiException("Invalid Dataset API response: " + safeDetail(e.getMessage()), false, e);
        }
    }

    private ApiResponse get(String path) throws ApiException {
        try {
            ApiResponse response = transport.send("GET", URI.create(API_BASE + path), "Bearer " + token, null);
            if (response.statusCode() < 200 || response.statusCode() >= 300) throw new ApiException("Apify API request failed with HTTP " + response.statusCode() + ".", false);
            return response;
        } catch (ApiException e) { throw e; }
        catch (Exception e) { throw new ApiException("Apify API network error: " + safeDetail(e.getMessage()), false, e); }
    }

    public static boolean isTerminal(String status) {
        return "SUCCEEDED".equals(status) || "FAILED".equals(status) || "TIMED-OUT".equals(status) || "ABORTED".equals(status);
    }

    public static String safe(String message) {
        if (message == null) return "request failed";
        return message.replaceAll("(?i)(token|authorization)(\\s*[:=]\\s*|\\s+bearer\\s+)[^\\s,;]+", "$1=[REDACTED]");
    }

    private String safeDetail(String message) {
        String sanitized = safe(message);
        return token.isBlank() ? sanitized : sanitized.replace(token, "[REDACTED]");
    }

    public String redact(String message) { return safeDetail(message); }

    private static final class OkHttpTransport implements Transport {
        private final OkHttpClient http = new OkHttpClient.Builder()
                .retryOnConnectionFailure(false)
                .followRedirects(false)
                .followSslRedirects(false)
                .callTimeout(Duration.ofMinutes(10))
                .build();

        @Override public ApiResponse send(String method, URI uri, String authorization, String body) throws IOException {
            Request.Builder builder = new Request.Builder().url(uri.toURL()).header("Authorization", authorization).header("Accept", "application/json");
            if ("POST".equals(method)) builder.post(RequestBody.create(body, JSON)); else builder.get();
            try (Response response = http.newCall(builder.build()).execute()) {
                return new ApiResponse(response.code(), response.body() == null ? "" : response.body().string());
            }
        }
    }
}
