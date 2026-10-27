package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Client-side CSV fan-out: each valid row creates its own single-video Run. */
public final class CsvBatch {
    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Set<String> SUCCESS = Set.of("transcript_success", "completed_with_transcript");
    // Final row states, matching the Python reference implementation's FINAL_RECORD_STATUSES.
    // dataset_error and processing_error are absent on purpose: they keep a known Run and stay
    // recoverable, so a changed URL must be reconciled instead of silently starting a new Run.
    private static final Set<String> TERMINAL = Set.of(
            "transcript_success", "completed_with_transcript", "transcript_empty", "transcript_failed",
            "actor_failed", "dataset_empty", "dataset_id_missing", "input_error", "duplicate_id"
    );
    /** Row states that may resume against an existing Run using GET requests only. */
    private static final Set<String> RESUMABLE = Set.of("run_pending", "dataset_error", "processing_error");
    /** Row states that still need a human or a resumed run before the batch can finish. */
    private static final Set<String> PENDING = Set.of(
            "needs_reconciliation", "start_attempted", "run_creation_unknown", "dataset_error", "processing_error"
    );
    private static final Duration POLL_INTERVAL = Duration.ofSeconds(3);
    private CsvBatch() {}

    public static void main(String[] args) {
        int code;
        try { code = runCli(args); }
        catch (Exception e) { System.err.println(ApifyClient.safe(e.getMessage())); code = 1; }
        if (code != 0) System.exit(code);
    }

    static int runCli(String[] args) throws Exception {
        Options options = parseCli(args);
        if (options.reconcile()) return reconcile(options.csv(), options.journal());
        return process(options.csv(), options.journal(), options.concurrency(),
                new ApifyClient(SingleUrl.token()), options.maxWait());
    }

    static Options parseCli(String[] args) {
        Path csv = null;
        Path journal = null;
        int concurrency = 2;
        long maxWaitSeconds = ApifyClient.DEFAULT_MAX_WAIT.toSeconds();
        boolean reconcile = false;
        for (int i = 0; i < args.length; i++) {
            switch (args[i]) {
                case "--csv" -> csv = Path.of(args[++i]);
                case "--journal" -> journal = Path.of(args[++i]);
                case "--concurrency" -> concurrency = Integer.parseInt(args[++i]);
                case "--max-wait" -> maxWaitSeconds = ApifyClient.parseMaxWaitSeconds(args[++i]);
                case "--reconcile" -> reconcile = true;
                default -> throw new IllegalArgumentException(
                        "Usage: CsvBatch --csv FILE [--journal FILE] [--concurrency 1..8] [--max-wait SECONDS] [--reconcile]");
            }
        }
        if (csv == null) throw new IllegalArgumentException("--csv is required.");
        if (concurrency < 1 || concurrency > 8) throw new IllegalArgumentException("Concurrency must be between 1 and 8.");
        if (journal == null) journal = csv.resolveSibling(csv.getFileName() + ".results.jsonl");
        return new Options(csv, journal, concurrency, Duration.ofSeconds(maxWaitSeconds), reconcile);
    }

    record Options(Path csv, Path journal, int concurrency, Duration maxWait, boolean reconcile) {}

    static int process(Path csv, Path journal, int concurrency, ApifyClient client) throws Exception {
        return process(csv, journal, concurrency, client, ApifyClient.DEFAULT_MAX_WAIT);
    }

    static int process(Path csv, Path journal, int concurrency, ApifyClient client, Duration maxWait) throws Exception {
        if (concurrency < 1 || concurrency > 8) throw new IllegalArgumentException("Concurrency must be between 1 and 8.");
        ApifyClient.validateMaxWait(maxWait);
        List<Row> rows = readCsv(csv);
        if (rows.isEmpty()) { System.err.println("CSV contains no video rows."); return 1; }
        Map<String, JsonNode> latest = loadJournal(journal);
        List<Work> work = identify(rows, latest);
        Set<String> activeKeys = new LinkedHashSet<>();
        for (Work item : work) activeKeys.add(item.key());
        // Let processRow inspect prior unresolved state before classifying a changed/empty URL.
        // Otherwise an input error could overwrite the Run ID needed for manual reconciliation.
        List<Work> validWork = work;
        boolean workerFailure = false;
        ExecutorService pool = Executors.newFixedThreadPool(concurrency);
        try {
            List<Future<String>> futures = new ArrayList<>();
            for (Work item : validWork) futures.add(pool.submit(() -> processRow(item, latest, journal, client, maxWait)));
            for (Future<String> future : futures) {
                try { future.get(); }
                catch (Exception e) {
                    workerFailure = true;
                    System.err.println("CSV row processing error: " + ApifyClient.safe(e.getMessage()));
                }
            }
        } finally { pool.shutdownNow(); }
        // Only rows of the current CSV contribute to the summary and the exit code. The journal
        // stays append-only, so deleted or historical rows remain on disk without affecting results.
        Map<String, JsonNode> batchRows = selectBatchRows(loadJournal(journal), activeKeys);
        System.out.println("Per-Run wait limit: " + describe(maxWait));
        printSummary(batchRows);
        boolean incomplete = workerFailure
                || batchRows.size() != activeKeys.size()
                || batchRows.values().stream().anyMatch(r -> !SUCCESS.contains(text(r, "status")));
        return incomplete ? 1 : 0;
    }

    /** Latest record per key, restricted to the keys present in the current CSV. */
    static Map<String, JsonNode> selectBatchRows(Map<String, JsonNode> latest, Set<String> activeKeys) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        for (String key : activeKeys) {
            JsonNode record = latest.get(key);
            if (record != null) result.put(key, record);
        }
        return result;
    }

    private static String describe(Duration wait) {
        return wait.toSeconds() >= 1 ? wait.toSeconds() + " seconds" : wait.toMillis() + " ms";
    }

    private static String processRow(Work work, Map<String, JsonNode> latest, Path journal, ApifyClient client, Duration maxWait) {
        String key = work.key();
        JsonNode old = latest.get(key);
        String currentUrl = work.url();
        String oldUrl = old == null ? null : text(old, "videoUrl");
        String oldStatus = old == null ? "" : text(old, "status");
        String runId = old == null ? "" : text(old, "run_id").trim();
        if (old != null && "needs_reconciliation".equals(oldStatus)) {
            String recordedCurrent = firstText(old, "current_url", "currentUrl");
            if (!currentUrl.equals(recordedCurrent)) {
                ObjectNode held = old.deepCopy();
                String originalUrl = firstText(old, "original_url", "videoUrl");
                String previousStatus = firstText(old, "previous_status", "status");
                held.put("status", "needs_reconciliation");
                held.put("videoUrl", originalUrl);
                held.put("original_url", originalUrl);
                held.put("currentUrl", currentUrl);
                held.put("current_url", currentUrl);
                held.put("run_id", runId);
                held.put("previous_status", previousStatus);
                held.put("error", appendDiagnostic(text(old, "error"),
                        "CSV videoUrl changed again from " + recordedCurrent + " to " + currentUrl + "; manual reconciliation is still required."));
                appendRecord(journal, held);
            }
            return "needs_reconciliation";
        }
        if (old != null && !currentUrl.equals(oldUrl)) {
            if (TERMINAL.contains(oldStatus)) { old = null; runId = ""; }
            else {
                String originalUrl = firstText(old, "original_url", "videoUrl");
                ObjectNode held = record(key, "needs_reconciliation", originalUrl, currentUrl, runId,
                        appendDiagnostic(text(old, "error"), "Input URL changed while prior Run was unresolved (from " + oldUrl + " to " + currentUrl + ")."));
                held.put("original_url", originalUrl);
                held.put("current_url", currentUrl);
                held.put("previous_status", oldStatus);
                appendRecord(journal, held);
                return "needs_reconciliation";
            }
        }
        if (old != null && TERMINAL.contains(oldStatus)) return oldStatus;
        if (old != null && ("start_attempted".equals(oldStatus) || "run_creation_unknown".equals(oldStatus))) return "run_creation_unknown";
        if (work.inputError() != null) {
            if (old != null) return oldStatus;
            appendRecord(journal, record(key, "input_error", currentUrl, currentUrl, "", work.inputError()));
            return "input_error";
        }
        // run_pending, dataset_error and processing_error resume the same Run with GET requests
        // only: a failed poll or Dataset read is transient and must not be frozen forever.
        if (old != null && RESUMABLE.contains(oldStatus) && runId.isBlank()) {
            ObjectNode held = record(key, "needs_reconciliation", oldUrl, currentUrl, "",
                    appendDiagnostic(text(old, "error"), "Journal state requires an existing Run ID, but none is recorded. Check Apify Console and reconcile manually before continuing."));
            held.put("original_url", firstText(old, "original_url", "videoUrl"));
            held.put("current_url", currentUrl);
            held.put("previous_status", oldStatus);
            appendRecord(journal, held);
            return "needs_reconciliation";
        }
        if (old != null && !runId.isBlank() && !RESUMABLE.contains(oldStatus)) return oldStatus;
        if (runId.isBlank()) {
            try { ApifyClient.validateVideoUrl(currentUrl); }
            catch (IllegalArgumentException e) {
                appendRecord(journal, record(key, "input_error", currentUrl, currentUrl, "", e.getMessage()));
                return "input_error";
            }
        }
        try {
            if (runId.isBlank()) {
                appendRecord(journal, record(key, "start_attempted", currentUrl, currentUrl, "", "Intent persisted before POST."));
                JsonNode created = client.startRun(currentUrl);
                runId = created.path("id").asText();
                appendRecord(journal, record(key, "run_pending", currentUrl, currentUrl, runId, "Run created; awaiting completion."));
            }
            JsonNode run = client.waitForRun(runId, maxWait, POLL_INTERVAL);
            String status = run.path("status").asText("");
            if (!"SUCCEEDED".equals(status)) {
                appendRecord(journal, record(key, "actor_failed", currentUrl, currentUrl, runId, "Actor Run status: " + status));
                return "actor_failed";
            }
            String dataset = run.path("defaultDatasetId").asText("");
            if (dataset.isBlank()) {
                appendRecord(journal, record(key, "dataset_id_missing", currentUrl, currentUrl, runId, "Run succeeded without a default Dataset ID."));
                return "dataset_id_missing";
            }
            JsonNode items;
            try { items = client.getDatasetItems(dataset); }
            catch (ApifyClient.ApiException e) {
                appendRecord(journal, record(key, "dataset_error", currentUrl, currentUrl, runId, e.getMessage()));
                return "dataset_error";
            }
            String failure = TranscriptResult.failure(run, items);
            if (items.isEmpty()) {
                appendRecord(journal, record(key, "dataset_empty", currentUrl, currentUrl, runId, "Dataset has no Items."));
                return "dataset_empty";
            }
            String finalStatus = failure == null ? "transcript_success" : failure.startsWith("Transcript failed") ? "transcript_failed" : "transcript_empty";
            appendRecord(journal, record(key, finalStatus, currentUrl, currentUrl, runId, failure == null ? "Transcript available." : failure));
            return finalStatus;
        } catch (ApifyClient.ApiException e) {
            boolean knownRun = !runId.isBlank();
            String state = knownRun
                    ? e.getMessage().contains("Wait time reached") ? "run_pending" : "processing_error"
                    : e.outcomeUnknown() ? "run_creation_unknown" : "processing_error";
            String message = knownRun
                    ? "Run ID is known; this row can resume by querying the same Run. " + e.getMessage()
                    : e.outcomeUnknown() ? "Run may have been created; check Apify Console before retrying. " + e.getMessage() : e.getMessage();
            appendRecord(journal, record(key, state, currentUrl, currentUrl, runId, client.redact(message)));
            return state;
        } catch (Exception e) {
            boolean knownRun = !runId.isBlank();
            String state = knownRun ? "processing_error" : "run_creation_unknown";
            String context = knownRun
                    ? "Run ID is known; resume by querying the same Run. "
                    : "Run creation outcome is unknown; Run may have been created. Check Apify Console before retrying. ";
            appendRecord(journal, record(key, state, currentUrl, currentUrl, runId,
                    "Unexpected Run creation/processing result. " + context + client.redact(e.getMessage())));
            return state;
        }
    }

    private static String appendDiagnostic(String previous, String current) {
        if (current == null || current.isBlank()) return previous == null ? "" : previous;
        return previous == null || previous.isBlank() ? current : previous + "; " + current;
    }

    private static String firstText(JsonNode node, String primary, String fallback) {
        String value = text(node, primary);
        return value.isBlank() ? text(node, fallback) : value;
    }

    /** Read-only view of rows that are still unresolved for the current CSV. Never writes or requests. */
    static int reconcile(Path csv, Path journal) throws Exception {
        List<Work> current = identify(readCsv(csv), loadJournal(journal));
        Map<String, JsonNode> latest = loadJournal(journal);
        boolean found = false;
        for (Work work : current) {
            JsonNode rec = latest.get(work.key());
            if (rec == null && work.inputError() == null) continue;
            String status = rec == null ? "input_error" : text(rec, "status");
            String oldUrl = rec == null ? "" : firstText(rec, "original_url", "videoUrl");
            String runId = rec == null ? "" : text(rec, "run_id");
            boolean unresolved = work.inputError() != null || PENDING.contains(status)
                    || ("run_pending".equals(status) && !work.url().equals(oldUrl))
                    || (!work.url().equals(oldUrl) && !TERMINAL.contains(status));
            if (unresolved) {
                found = true;
                System.out.printf("key=%s status=%s previous_status=%s original_url=%s current_url=%s run_id=%s error=%s%n",
                        work.key(), status, rec == null ? "" : text(rec, "previous_status"), oldUrl, work.url(), runId,
                        appendDiagnostic(rec == null ? "" : text(rec, "error"), work.inputError() == null ? "" : work.inputError()));
            }
        }
        if (!found) System.out.println("No records need reconciliation.");
        return 0;
    }

    private static List<Work> identify(List<Row> rows, Map<String, JsonNode> prior) throws Exception {
        boolean hasId = rows.stream().anyMatch(row -> row.id() != null);
        Set<String> ids = new HashSet<>();
        Map<String, Integer> duplicateUrls = new HashMap<>();
        List<Work> result = new ArrayList<>();
        for (int i = 0; i < rows.size(); i++) {
            Row row = rows.get(i);
            boolean emptyUrl = row.url() == null || row.url().isBlank();
            String key;
            if (hasId) {
                if (row.id() == null || row.id().isBlank()) throw new IllegalArgumentException("CSV row " + (i + 2) + " has an empty id.");
                if (!ids.add(row.id())) throw new IllegalArgumentException("Duplicate CSV id: " + row.id());
                key = "id:" + row.id();
            } else if (emptyUrl) {
                // An empty URL has no stable URL-derived identity; report it by row only and never match history.
                result.add(new Work("invalid-url-row:" + (i + 2), row.url() == null ? "" : row.url(),
                        "CSV row " + (i + 2) + " has an empty videoUrl; no stable key is available without an id column."));
                continue;
            } else {
                // Without an id column, URL edits create a new key; duplicate rows are distinct by occurrence order.
                int occurrence = duplicateUrls.merge(row.url(), 1, Integer::sum);
                key = "url:" + sha256(row.url()) + ":" + occurrence;
            }
            result.add(new Work(key, row.url() == null ? "" : row.url(), emptyUrl
                    ? "CSV row " + (i + 2) + " has an empty videoUrl." : null));
        }
        return result;
    }

    private static ObjectNode record(String key, String status, String url, String currentUrl, String runId, String error) {
        ObjectNode node = MAPPER.createObjectNode().put("key", key).put("status", status).put("videoUrl", url);
        if (currentUrl != null) node.put("currentUrl", currentUrl);
        node.put("run_id", runId == null ? "" : runId).put("error", ApifyClient.safe(error));
        return node;
    }

    private static synchronized void appendRecord(Path path, JsonNode node) {
        try {
            Files.createDirectories(path.toAbsolutePath().getParent());
            byte[] data = (MAPPER.writeValueAsString(node) + "\n").getBytes(StandardCharsets.UTF_8);
            try (FileChannel channel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
                channel.write(java.nio.ByteBuffer.wrap(data));
                channel.force(true);
            }
        } catch (IOException e) { throw new IllegalStateException("Could not persist CSV journal record.", e); }
    }

    private static Map<String, JsonNode> loadJournal(Path path) throws IOException {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        if (!Files.exists(path)) return result;
        for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {
            if (line.isBlank()) continue;
            JsonNode node = MAPPER.readTree(line);
            if (node != null && node.isObject() && !text(node, "key").isBlank()) result.put(text(node, "key"), node);
        }
        return result;
    }

    static void printSummary(Map<String, JsonNode> rows) {
        Map<String, Long> counts = new java.util.TreeMap<>();
        for (JsonNode row : rows.values()) counts.merge(text(row, "status"), 1L, Long::sum);
        System.out.println("Batch summary: " + counts);
    }

    static List<Row> readCsv(Path path) throws IOException {
        String text = Files.readString(path, StandardCharsets.UTF_8);
        if (text.startsWith("\uFEFF")) text = text.substring(1);
        List<List<String>> records = parseCsv(text);
        if (records.isEmpty()) return List.of();
        List<String> header = records.remove(0);
        if (new HashSet<>(header).size() != header.size()) throw new IllegalArgumentException("CSV has duplicate column headers.");
        int urlIndex = header.indexOf("videoUrl"), idIndex = header.indexOf("id");
        if (urlIndex < 0) throw new IllegalArgumentException("CSV must contain a videoUrl column.");
        List<Row> rows = new ArrayList<>();
        for (List<String> values : records) {
            if (values.size() == 1 && values.get(0).isBlank()) continue;
            if (values.size() != header.size()) throw new IllegalArgumentException("CSV row has a different number of fields than its header.");
            rows.add(new Row(idIndex < 0 ? null : values.get(idIndex), values.get(urlIndex)));
        }
        return rows;
    }

    static List<List<String>> parseCsv(String input) {
        List<List<String>> rows = new ArrayList<>();
        List<String> row = new ArrayList<>();
        StringBuilder cell = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < input.length(); i++) {
            char c = input.charAt(i);
            if (quoted) {
                if (c == '"' && i + 1 < input.length() && input.charAt(i + 1) == '"') { cell.append('"'); i++; }
                else if (c == '"') quoted = false;
                else cell.append(c);
            } else if (c == '"' && cell.length() == 0) quoted = true;
            else if (c == ',') { row.add(cell.toString()); cell.setLength(0); }
            else if (c == '\n' || c == '\r') {
                if (c == '\r' && i + 1 < input.length() && input.charAt(i + 1) == '\n') i++;
                row.add(cell.toString()); cell.setLength(0);
                if (!(row.size() == 1 && row.get(0).isBlank())) rows.add(row);
                row = new ArrayList<>();
            } else cell.append(c);
        }
        if (quoted) throw new IllegalArgumentException("CSV contains an unterminated quoted field.");
        if (cell.length() > 0 || !row.isEmpty()) { row.add(cell.toString()); rows.add(row); }
        return rows;
    }

    private static String sha256(String value) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))); }
    private static String text(JsonNode node, String key) { return node == null ? "" : node.path(key).asText(""); }
    record Row(String id, String url) {}
    record Work(String key, String url, String inputError) {}
}
