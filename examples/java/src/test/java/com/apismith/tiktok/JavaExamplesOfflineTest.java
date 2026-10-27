package com.apismith.tiktok;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class JavaExamplesOfflineTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String URL = "https://www.tiktok.com/@example/video/1234567890";
    @TempDir Path temp;

    @Test void fixedActorPostUsesAuthHeaderAndOneVideoOnly() throws Exception {
        List<String> calls = new ArrayList<>();
        ApifyClient client = new ApifyClient("unit-test-secret", (method, uri, auth, body) -> {
            calls.add(method + " " + uri.getHost() + uri.getRawPath() + " " + auth + " " + body);
            return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"R1\"}}");
        });
        assertEquals("R1", client.startRun(URL).path("id").asText());
        assertEquals(1, calls.size());
        assertEquals("POST api.apify.com/v2/actors/apple_yang~tiktok-transcripts-scraper/runs Bearer unit-test-secret {\"videoUrl\":\"" + URL + "\"}", calls.get(0));
        assertFalse(calls.get(0).contains("instagram"));
    }

    @Test void malformedCreationResponsesAreUnknownAndNeverRetried() {
        for (String body : List.of("null", "[]", "\"ok\"", "123", "{}", "{\"data\":null}", "{\"data\":[]}", "{\"data\":{\"id\":7}}")) {
            AtomicInteger posts = new AtomicInteger();
            ApifyClient client = new ApifyClient("dont-log-me", (method, uri, auth, payload) -> {
                posts.incrementAndGet(); return new ApifyClient.ApiResponse(200, body);
            });
            ApifyClient.ApiException error = assertThrows(ApifyClient.ApiException.class, () -> client.startRun(URL));
            assertTrue(error.outcomeUnknown(), body);
            assertEquals(1, posts.get(), body);
            assertFalse(error.getMessage().contains("dont-log-me"));
        }
    }

    @Test void invalidUrlFailsBeforeTransportAndRedactionPreservesTikTokHost() {
        AtomicInteger calls = new AtomicInteger();
        ApifyClient client = new ApifyClient("secret", (method, uri, auth, body) -> {
            calls.incrementAndGet(); return new ApifyClient.ApiResponse(201, "{}");
        });
        assertThrows(IllegalArgumentException.class, () -> client.startRun("https://example.com/not-tiktok"));
        assertEquals(0, calls.get());
        assertEquals("See https://www.tiktok.com/@x/video/1", ApifyClient.safe("See https://www.tiktok.com/@x/video/1"));
    }

    @Test void singleUrlOutputPreflightFailsBeforePostAndLeavesExistingFilesUntouched() throws Exception {
        Path existingOutputDirectory = temp.resolve("existing-output");
        Files.createDirectories(existingOutputDirectory);
        Path existingOutput = existingOutputDirectory.resolve("java-single-url-response.json");
        Files.writeString(existingOutput, "keep this result\n");
        SingleUrl.preflightOutputDirectory(existingOutputDirectory);
        assertEquals("keep this result\n", Files.readString(existingOutput));
        try (var entries = Files.list(existingOutputDirectory)) {
            assertEquals(List.of(existingOutput), entries.toList());
        }

        Path blocker = temp.resolve("not-a-directory");
        Files.writeString(blocker, "preserve me");
        AtomicInteger requests = new AtomicInteger();
        ApifyClient client = new ApifyClient("offline-test-token", (method, uri, auth, body) -> {
            requests.incrementAndGet();
            throw new AssertionError("output preflight must fail before HTTP");
        });
        PrintStream originalErr = System.err;
        ByteArrayOutputStream errors = new ByteArrayOutputStream();
        System.setErr(new PrintStream(errors, true, StandardCharsets.UTF_8));
        int exit;
        try {
            exit = SingleUrl.run(new String[0], client, blocker.resolve("generated"));
        } finally {
            System.setErr(originalErr);
        }
        assertEquals(1, exit);
        assertEquals(0, requests.get());
        assertTrue(errors.toString(StandardCharsets.UTF_8).contains("Output directory preflight failed"));
        assertFalse(errors.toString(StandardCharsets.UTF_8).contains("offline-test-token"));
        assertEquals("preserve me", Files.readString(blocker));
    }

    @Test void postNetworkFailureIsUnknownAndSingleAttempt() {
        AtomicInteger posts = new AtomicInteger();
        ApifyClient client = new ApifyClient("private-token", (method, uri, auth, body) -> {
            posts.incrementAndGet(); throw new IOException("socket reset private-token");
        });
        ApifyClient.ApiException error = assertThrows(ApifyClient.ApiException.class, () -> client.startRun(URL));
        assertTrue(error.outcomeUnknown());
        assertEquals(1, posts.get());
        assertFalse(error.getMessage().contains("private-token"));
    }

    @Test void rejectedCreateResponseIsUnknownAndWaitTimeoutCanReuseTheSameId() throws Exception {
        AtomicInteger posts = new AtomicInteger(), runReads = new AtomicInteger(), resumedPosts = new AtomicInteger();
        ApifyClient rejected = new ApifyClient("t", (method, uri, auth, body) -> {
            posts.incrementAndGet(); return new ApifyClient.ApiResponse(503, "service unavailable");
        });
        assertTrue(assertThrows(ApifyClient.ApiException.class, () -> rejected.startRun(URL)).outcomeUnknown());
        assertEquals(1, posts.get());

        AtomicBoolean completionAllowed = new AtomicBoolean(false);
        ApifyClient resumable = new ApifyClient("t", (method, uri, auth, body) -> {
            if ("POST".equals(method)) resumedPosts.incrementAndGet();
            int read = runReads.incrementAndGet();
            if (!completionAllowed.get()) return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R1\",\"status\":\"RUNNING\"}}");
            return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R1\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D\"}}");
        });
        ApifyClient.ApiException timeout = assertThrows(ApifyClient.ApiException.class,
                () -> resumable.waitForRun("R1", Duration.ofSeconds(1), Duration.ofSeconds(2)));
        assertTrue(timeout.getMessage().contains("same Run ID"));
        completionAllowed.set(true);
        assertEquals("R1", resumable.waitForRun("R1", Duration.ofSeconds(1), Duration.ofMillis(1)).path("id").asText());
        assertTrue(runReads.get() >= 2);
        assertEquals(0, resumedPosts.get());
        assertEquals(1, posts.get());
    }

    @Test void runEnvelopeIsUnwrappedAndTerminalWaitStopsThenDatasetIsArray() throws Exception {
        List<String> paths = new ArrayList<>();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            paths.add(uri.getRawPath());
            if (uri.getRawPath().equals("/v2/actor-runs/R1")) return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R1\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D1\"}}");
            if (uri.getRawPath().equals("/v2/datasets/D1/items")) return new ApifyClient.ApiResponse(200, "[{\"text\":\"hello\",\"segments\":[] ,\"errMsg\":\"\"}]");
            throw new AssertionError(uri);
        });
        JsonNode run = client.waitForRun("R1", Duration.ofSeconds(2), Duration.ofMillis(1));
        assertEquals("R1", run.path("id").asText());
        assertEquals("D1", run.path("defaultDatasetId").asText());
        JsonNode items = client.getDatasetItems(run.path("defaultDatasetId").asText());
        assertTrue(items.isArray());
        assertNull(TranscriptResult.failure(run, items));
        assertEquals(2, paths.size());
    }

    @Test void malformedRunEnvelopeAndMismatchedRunIdFailImmediately() {
        for (String payload : List.of("{}", "{\"data\":[]}", "{\"data\":{\"id\":\"OTHER\",\"status\":\"RUNNING\"}}")) {
            ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> new ApifyClient.ApiResponse(200, payload));
            ApifyClient.ApiException error = assertThrows(ApifyClient.ApiException.class,
                    () -> client.waitForRun("R1", Duration.ofSeconds(1), Duration.ofSeconds(1)));
            assertTrue(error.getMessage().contains("Invalid Run API response"));
        }
    }

    @Test void transcriptRequiresTextAndNoErrMsg() throws Exception {
        JsonNode run = JSON.readTree("{\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D\"}");
        assertTrue(TranscriptResult.failure(run, JSON.readTree("[]")).contains("empty"));
        assertTrue(TranscriptResult.failure(run, JSON.readTree("[{\"segments\":[]}]")).contains("empty"));
        assertTrue(TranscriptResult.failure(run, JSON.readTree("[{\"text\":\"hello\",\"errMsg\":\"bad\"}]")).contains("errMsg"));
        assertTrue(TranscriptResult.failure(JSON.readTree("{\"status\":\"FAILED\"}"), JSON.readTree("[]")).contains("failed"));
    }

    @Test void cliUrlAndWaitNeverStartsASecondRun() throws Exception {
        assertEquals(ApifyClient.DEFAULT_VIDEO_URL, SingleUrl.parseUrl(new String[0]));
        assertEquals(URL, SingleUrl.parseUrl(new String[]{URL}));
        assertEquals(URL, SingleUrl.parseUrl(new String[]{"--video-url", URL}));
        AtomicInteger posts = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if (method.equals("POST")) { posts.incrementAndGet(); return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"R1\"}}"); }
            if (uri.getRawPath().contains("datasets/D1")) return new ApifyClient.ApiResponse(200, "[{\"text\":\"ready\"}]");
            return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R1\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D1\"}}");
        });
        assertEquals(0, AsyncRun.run(new String[]{"start", "--video-url", URL}, client));
        assertEquals(0, AsyncRun.run(new String[]{"wait", "--run-id", "R1", "--max-wait", "1"}, client));
        assertEquals(1, posts.get());
    }

    @Test void csvPersistsIntentBeforePostAndUnknownCannotBeResubmitted() throws Exception {
        Path csv = temp.resolve("input.csv"), journal = temp.resolve("out.jsonl");
        Files.writeString(csv, "id,videoUrl\nrow-1," + URL + "\n");
        AtomicInteger posts = new AtomicInteger();
        ApifyClient client = new ApifyClient("secret", (method, uri, auth, body) -> {
            if (method.equals("POST")) {
                posts.incrementAndGet();
                assertTrue(Files.readString(journal).contains("start_attempted"));
                throw new IOException("connection lost");
            }
            throw new AssertionError("unexpected request");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(1, posts.get());
        assertTrue(Files.readString(journal).contains("run_creation_unknown"));
        assertFalse(Files.readString(journal).contains("secret"));
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(1, posts.get());
    }

    @Test void csvPendingUrlChangeReconcilesAndTerminalUrlChangeCreatesFreshRun() throws Exception {
        Path csv = temp.resolve("input.csv"), journal = temp.resolve("out.jsonl");
        String changed = "https://www.tiktok.com/@other/video/9876543210";
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"run_pending\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"OLD\"}\n");
        Files.writeString(csv, "id,videoUrl\nr1," + changed + "\n");
        AtomicInteger sends = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> { sends.incrementAndGet(); throw new AssertionError("must not request old run or create new one"); });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, sends.get());
        String record = Files.readString(journal);
        assertTrue(record.contains("needs_reconciliation"));
        assertTrue(record.contains("currentUrl"));
        assertTrue(record.contains("OLD"));
        assertEquals(0, CsvBatch.reconcile(csv, journal));

        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"transcript_success\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"OLD\"}\n");
        AtomicInteger posts = new AtomicInteger(), datasets = new AtomicInteger();
        ApifyClient fresh = new ApifyClient("t", (method, uri, auth, body) -> {
            if (method.equals("POST")) { posts.incrementAndGet(); assertTrue(body.contains(changed)); return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"NEW\"}}"); }
            if (uri.getRawPath().contains("actor-runs/NEW")) return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"NEW\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"DNEW\"}}");
            if (uri.getRawPath().contains("datasets/DNEW")) { datasets.incrementAndGet(); return new ApifyClient.ApiResponse(200, "[{\"text\":\"new text\"}]"); }
            throw new AssertionError(uri);
        });
        Files.writeString(csv, "id,videoUrl\nr1," + changed + "\n");
        assertEquals(0, CsvBatch.process(csv, journal, 1, fresh));
        assertEquals(1, posts.get());
        assertEquals(1, datasets.get());
        JsonNode latest = lastRecord(journal);
        assertEquals(changed, latest.path("videoUrl").asText());
        assertEquals("NEW", latest.path("run_id").asText());
        assertEquals("transcript_success", latest.path("status").asText());
    }

    @Test void sameUrlTerminalTranscriptEmptyWithoutRunIdIsStableAndStillFailsBatch() throws Exception {
        for (String runIdCase : List.of("missing", "empty", "whitespace")) {
            Path csv = temp.resolve("terminal-empty-" + runIdCase + ".csv");
            Path journal = temp.resolve("terminal-empty-" + runIdCase + ".jsonl");
            Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
            ObjectNode terminal = JSON.createObjectNode()
                    .put("key", "id:r1")
                    .put("status", "transcript_empty")
                    .put("videoUrl", URL)
                    .put("error", "transcript was empty");
            if (runIdCase.equals("empty")) terminal.put("run_id", "");
            if (runIdCase.equals("whitespace")) terminal.put("run_id", " \t ");
            Files.writeString(journal, JSON.writeValueAsString(terminal) + "\n");
            String before = Files.readString(journal);
            AtomicInteger requests = new AtomicInteger();
            ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
                requests.incrementAndGet();
                throw new AssertionError("same-URL terminal rows must not issue HTTP requests");
            });

            assertEquals(1, CsvBatch.process(csv, journal, 1, client), runIdCase);
            assertEquals(0, requests.get());
            assertEquals(before, Files.readString(journal), "terminal journal must not grow");
            JsonNode preserved = lastRecord(journal);
            assertEquals("transcript_empty", preserved.path("status").asText());
            assertEquals("transcript was empty", preserved.path("error").asText());
        }
    }

    @Test void completedWithTranscriptWithoutRunIdIsSharedSuccessfulTerminalState() throws Exception {
        Path csv = temp.resolve("shared-terminal.csv"), journal = temp.resolve("shared-terminal.jsonl");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"completed_with_transcript\",\"videoUrl\":\"" + URL
                + "\",\"error\":\"legacy success\"}\n");
        String before = Files.readString(journal);
        AtomicInteger requests = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            requests.incrementAndGet();
            throw new AssertionError("shared successful terminal rows must not issue HTTP requests");
        });

        assertEquals(0, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, requests.get());
        assertEquals(before, Files.readString(journal));
        assertEquals("completed_with_transcript", lastRecord(journal).path("status").asText());
    }

    @Test void repeatedUrlEditsKeepFirstReconciliationContextAndDoNotWriteOnStableRerun() throws Exception {
        Path csv = temp.resolve("repeated-edits.csv"), journal = temp.resolve("repeated-edits.jsonl");
        String firstEdit = "https://www.tiktok.com/@first/video/1111111111";
        String secondEdit = "https://www.tiktok.com/@second/video/2222222222";
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"run_pending\",\"videoUrl\":\"" + URL
                + "\",\"run_id\":\"KEEP_RUN\",\"error\":\"original transient diagnostic\"}\n");
        AtomicInteger requests = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            requests.incrementAndGet();
            throw new AssertionError("changed unresolved URLs must not read or create a Run");
        });

        Files.writeString(csv, "id,videoUrl\nr1," + firstEdit + "\n");
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        Files.writeString(csv, "id,videoUrl\nr1," + secondEdit + "\n");
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, requests.get());

        JsonNode held = lastRecord(journal);
        assertEquals("needs_reconciliation", held.path("status").asText());
        assertEquals("run_pending", held.path("previous_status").asText());
        assertEquals(URL, held.path("original_url").asText());
        assertEquals(secondEdit, held.path("current_url").asText());
        assertEquals("KEEP_RUN", held.path("run_id").asText());
        assertTrue(held.path("error").asText().contains("original transient diagnostic"));
        assertTrue(held.path("error").asText().contains(firstEdit));
        assertTrue(held.path("error").asText().contains(secondEdit));

        String beforeStableRerun = Files.readString(journal);
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(beforeStableRerun, Files.readString(journal));
        Captured reconciliation = runCapturingStdout(() -> CsvBatch.reconcile(csv, journal));
        assertEquals(0, reconciliation.code());
        for (String detail : List.of("previous_status=run_pending", "original_url=" + URL,
                "current_url=" + secondEdit, "run_id=KEEP_RUN", "original transient diagnostic", firstEdit)) {
            assertTrue(reconciliation.output().contains(detail), reconciliation.output());
        }
        assertEquals(beforeStableRerun, Files.readString(journal), "reconcile must remain read-only");
        assertEquals(0, requests.get());
    }

    @Test void reconcileWithIdAndEmptyUrlShowsExistingUnresolvedRecordWithoutMutation() throws Exception {
        Path csv = temp.resolve("empty-url-with-id.csv"), journal = temp.resolve("empty-url-with-id.jsonl");
        Files.writeString(csv, "id,videoUrl\nr1,\n");
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"run_pending\",\"videoUrl\":\"" + URL
                + "\",\"run_id\":\"KNOWN_RUN\",\"error\":\"waiting diagnostic\"}\n");
        String before = Files.readString(journal);
        Captured result = runCapturingStdout(() -> CsvBatch.reconcile(csv, journal));
        assertEquals(0, result.code());
        for (String detail : List.of("key=id:r1", "status=run_pending", "original_url=" + URL,
                "current_url=", "run_id=KNOWN_RUN", "waiting diagnostic", "empty videoUrl")) {
            assertTrue(result.output().contains(detail), result.output());
        }
        assertEquals(before, Files.readString(journal));

        AtomicInteger requests = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            requests.incrementAndGet();
            throw new AssertionError("empty URL must not create or read a Run");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, requests.get());
        JsonNode held = lastRecord(journal);
        assertEquals("needs_reconciliation", held.path("status").asText());
        assertEquals("run_pending", held.path("previous_status").asText());
        assertEquals(URL, held.path("original_url").asText());
        assertEquals("", held.path("current_url").asText());
        assertEquals("KNOWN_RUN", held.path("run_id").asText());
    }

    @Test void reconcileWithoutIdReportsEmptyUrlAsUnmatchableInvalidRow() throws Exception {
        Path csv = temp.resolve("empty-url-without-id.csv"), journal = temp.resolve("empty-url-without-id.jsonl");
        Files.writeString(csv, "videoUrl,notes\n,empty\n");
        String hashedKey = "url:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(URL.getBytes(StandardCharsets.UTF_8))) + ":1";
        Files.writeString(journal, "{\"key\":\"" + hashedKey + "\",\"status\":\"run_pending\",\"videoUrl\":\"" + URL
                + "\",\"run_id\":\"OTHER_ROW_RUN\",\"error\":\"other row\"}\n");
        String before = Files.readString(journal);

        Captured result = runCapturingStdout(() -> CsvBatch.reconcile(csv, journal));
        assertEquals(0, result.code());
        assertTrue(result.output().contains("invalid-url-row:2"), result.output());
        assertTrue(result.output().contains("input_error"), result.output());
        assertTrue(result.output().contains("no stable key is available"), result.output());
        assertFalse(result.output().contains("OTHER_ROW_RUN"), result.output());
        assertFalse(result.output().contains("other row"), result.output());
        assertEquals(before, Files.readString(journal));

        AtomicInteger requests = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            requests.incrementAndGet();
            throw new AssertionError("unkeyed empty URL must not create or read a Run");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, requests.get());
        JsonNode invalid = lastRecord(journal);
        assertEquals("invalid-url-row:2", invalid.path("key").asText());
        assertEquals("input_error", invalid.path("status").asText());
        assertEquals("", invalid.path("videoUrl").asText());
        assertTrue(Files.readString(journal).contains("OTHER_ROW_RUN"), "other row's history must remain untouched");
    }

    @Test void csvSameUrlPendingResumesSameRunAndCsvParserHandlesQuotedFields() throws Exception {
        Path csv = temp.resolve("same.csv"), journal = temp.resolve("same.jsonl");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"run_pending\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"EXISTING\"}\n");
        AtomicInteger posts = new AtomicInteger(), gets = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if (method.equals("POST")) posts.incrementAndGet();
            gets.incrementAndGet();
            if (uri.getRawPath().contains("actor-runs/EXISTING")) return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"EXISTING\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D\"}}");
            return new ApifyClient.ApiResponse(200, "[{\"text\":\"ok\"}]");
        });
        assertEquals(0, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, posts.get());
        assertEquals(2, gets.get());
        assertEquals("a,b", CsvBatch.parseCsv("col\r\n\"a,b\"\r\n").get(1).get(0));
        assertEquals("a\"b", CsvBatch.parseCsv("col\n\"a\"\"b\"\n").get(1).get(0));
    }

    @Test void csvWithoutIdsKeepsRepeatedUrlsAsDistinctRowsAndBoundsConcurrentPosts() throws Exception {
        Path csv = temp.resolve("duplicates.csv"), journal = temp.resolve("duplicates.jsonl");
        Files.writeString(csv, "videoUrl\r\n" + URL + "\r\n" + URL + "\r\n" + URL + "\r\n" + URL + "\r\n");
        AtomicInteger nextRun = new AtomicInteger(), active = new AtomicInteger(), maximum = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if (method.equals("POST")) {
                int now = active.incrementAndGet(); maximum.accumulateAndGet(now, Math::max);
                try { Thread.sleep(30); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
                active.decrementAndGet();
                return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"R" + nextRun.incrementAndGet() + "\"}}");
            }
            if (uri.getRawPath().contains("actor-runs/")) {
                String runId = uri.getPath().substring(uri.getPath().lastIndexOf('/') + 1);
                return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"" + runId + "\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D" + runId + "\"}}");
            }
            return new ApifyClient.ApiResponse(200, "[{\"text\":\"transcript\"}]");
        });
        assertEquals(0, CsvBatch.process(csv, journal, 2, client));
        assertEquals(4, nextRun.get());
        assertTrue(maximum.get() <= 2);
        String output = Files.readString(journal);
        assertTrue(output.contains(":1"));
        assertTrue(output.contains(":2"));
        assertTrue(output.contains(":3"));
        assertTrue(output.contains(":4"));
    }

    // --- P1-1: batch summary and exit code cover the current CSV only -------------------------

    @Test void batchSummaryAndExitCodeIgnoreRowsRemovedFromTheCsv() throws Exception {
        Path csv = temp.resolve("summary.csv"), journal = temp.resolve("summary.jsonl");
        String deletedUrl = "https://www.tiktok.com/@deleted/video/1111111111";
        Files.writeString(journal, "{\"key\":\"id:deleted\",\"status\":\"actor_failed\",\"videoUrl\":\""
                + deletedUrl + "\",\"run_id\":\"GONE\"}\n");
        Files.writeString(csv, "id,videoUrl\nkeep," + URL + "\n");
        AtomicInteger posts = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if ("POST".equals(method)) { posts.incrementAndGet(); return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"KEEP\"}}"); }
            if (uri.getRawPath().equals("/v2/actor-runs/KEEP")) return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"KEEP\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"DK\"}}");
            if (uri.getRawPath().equals("/v2/datasets/DK/items")) return new ApifyClient.ApiResponse(200, "[{\"text\":\"kept\"}]");
            throw new AssertionError(uri);
        });
        Captured captured = runCapturingStdout(() -> CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, captured.code());
        assertEquals(1, posts.get());
        assertTrue(captured.output().contains("transcript_success=1"), captured.output());
        assertFalse(captured.output().contains("actor_failed"), captured.output());
        // The journal stays append-only: the removed row is still on disk, just not counted.
        assertTrue(Files.readString(journal).contains("id:deleted"));
        assertTrue(Files.readString(journal).contains("actor_failed"));
    }

    @Test void batchStillFailsWhenACurrentCsvRowFails() throws Exception {
        Path csv = temp.resolve("failing.csv"), journal = temp.resolve("failing.jsonl");
        Files.writeString(csv, "id,videoUrl\nbad," + URL + "\n");
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> new ApifyClient.ApiResponse(503, "service unavailable"));
        Captured captured = runCapturingStdout(() -> CsvBatch.process(csv, journal, 1, client));
        assertEquals(1, captured.code());
        assertTrue(captured.output().contains("run_creation_unknown=1"), captured.output());
    }

    // --- P1-2: transient errors on a known Run are recoverable with GET only ------------------

    @Test void datasetErrorResumesTheSameRunWithGetOnly() throws Exception {
        Path csv = temp.resolve("dataset-error.csv"), journal = temp.resolve("dataset-error.jsonl");
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"dataset_error\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"R9\"}\n");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
        AtomicInteger posts = new AtomicInteger(), runReads = new AtomicInteger(), datasetReads = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if ("POST".equals(method)) { posts.incrementAndGet(); throw new IOException("recovery must not POST"); }
            if (uri.getRawPath().equals("/v2/actor-runs/R9")) {
                runReads.incrementAndGet();
                return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R9\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D9\"}}");
            }
            if (uri.getRawPath().equals("/v2/datasets/D9/items")) {
                datasetReads.incrementAndGet();
                return new ApifyClient.ApiResponse(200, "[{\"text\":\"recovered\",\"errMsg\":\"\"}]");
            }
            throw new AssertionError(uri);
        });
        assertEquals(0, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, posts.get());
        assertEquals(1, runReads.get());
        assertEquals(1, datasetReads.get());
        JsonNode latest = lastRecord(journal);
        assertEquals("transcript_success", latest.path("status").asText());
        assertEquals("R9", latest.path("run_id").asText());
    }

    @Test void processingErrorResumesTheSameRunWithGetOnly() throws Exception {
        Path csv = temp.resolve("processing-error.csv"), journal = temp.resolve("processing-error.jsonl");
        Files.writeString(journal, "{\"key\":\"id:r2\",\"status\":\"processing_error\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"R8\"}\n");
        Files.writeString(csv, "id,videoUrl\nr2," + URL + "\n");
        AtomicInteger posts = new AtomicInteger(), runReads = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            if ("POST".equals(method)) { posts.incrementAndGet(); throw new IOException("recovery must not POST"); }
            if (uri.getRawPath().equals("/v2/actor-runs/R8")) {
                runReads.incrementAndGet();
                return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"R8\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"D8\"}}");
            }
            return new ApifyClient.ApiResponse(200, "[{\"text\":\"recovered\",\"errMsg\":\"\"}]");
        });
        assertEquals(0, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, posts.get());
        assertEquals(1, runReads.get());
        JsonNode latest = lastRecord(journal);
        assertEquals("transcript_success", latest.path("status").asText());
        assertEquals("R8", latest.path("run_id").asText());
    }

    @Test void resumableRowsWithoutRunIdFailClosedAcrossMissingEmptyAndWhitespaceValues() throws Exception {
        for (String state : List.of("run_pending", "dataset_error", "processing_error")) {
            for (String runIdCase : List.of("missing", "empty", "whitespace")) {
                Path csv = temp.resolve(state + "-" + runIdCase + ".csv");
                Path journal = temp.resolve(state + "-" + runIdCase + ".jsonl");
                Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
                ObjectNode seeded = JSON.createObjectNode()
                        .put("key", "id:r1")
                        .put("status", state)
                        .put("videoUrl", URL)
                        .put("error", "prior diagnostic");
                if (runIdCase.equals("empty")) seeded.put("run_id", "");
                if (runIdCase.equals("whitespace")) seeded.put("run_id", "  \t ");
                Files.writeString(journal, JSON.writeValueAsString(seeded) + "\n");
                AtomicInteger requests = new AtomicInteger();
                ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
                    requests.incrementAndGet();
                    throw new AssertionError("a resumable row without run_id must not send HTTP requests");
                });

                assertEquals(1, CsvBatch.process(csv, journal, 1, client), state + "/" + runIdCase);
                JsonNode unresolved = lastRecord(journal);
                assertEquals("needs_reconciliation", unresolved.path("status").asText());
                assertEquals(state, unresolved.path("previous_status").asText());
                assertEquals(URL, unresolved.path("videoUrl").asText());
                assertEquals(URL, unresolved.path("currentUrl").asText());
                assertTrue(unresolved.path("error").asText().contains("prior diagnostic"));
                assertTrue(unresolved.path("error").asText().contains("existing Run ID"));
                assertEquals(0, requests.get());

                assertEquals(1, CsvBatch.process(csv, journal, 1, client), "repeat " + state + "/" + runIdCase);
                assertEquals(0, requests.get(), "repeat must not POST or GET");
                Captured reconciliation = runCapturingStdout(() -> CsvBatch.reconcile(csv, journal));
                assertEquals(0, reconciliation.code());
                for (String detail : List.of("needs_reconciliation", URL, "prior diagnostic", "previous_status=" + state)) {
                    assertTrue(reconciliation.output().contains(detail), reconciliation.output());
                }
            }
        }
    }

    @Test void changedUrlOnARecoverableRunHoldsForReconciliation() throws Exception {
        Path csv = temp.resolve("changed.csv"), journal = temp.resolve("changed.jsonl");
        String changed = "https://www.tiktok.com/@other/video/9876543210";
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"dataset_error\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"R9\"}\n");
        Files.writeString(csv, "id,videoUrl\nr1," + changed + "\n");
        AtomicInteger sends = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            sends.incrementAndGet();
            throw new AssertionError("a recoverable Run with a changed URL must not be read or replaced");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, sends.get());
        JsonNode latest = lastRecord(journal);
        assertEquals("needs_reconciliation", latest.path("status").asText());
        assertEquals("R9", latest.path("run_id").asText());
        assertEquals(URL, latest.path("videoUrl").asText());
        assertEquals(changed, latest.path("currentUrl").asText());
    }

    @Test void reconcileListsKnownRunPendingStatesAndStaysReadOnly() throws Exception {
        Path csv = temp.resolve("reconcile.csv"), journal = temp.resolve("reconcile.jsonl");
        Files.writeString(journal,
                "{\"key\":\"id:r1\",\"status\":\"dataset_error\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"R9\"}\n"
                        + "{\"key\":\"id:r2\",\"status\":\"processing_error\",\"videoUrl\":\"" + URL + "\",\"run_id\":\"R8\"}\n");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\nr2," + URL + "\n");
        String before = Files.readString(journal);
        Captured captured = runCapturingStdout(() -> CsvBatch.reconcile(csv, journal));
        assertEquals(0, captured.code());
        assertTrue(captured.output().contains("dataset_error"), captured.output());
        assertTrue(captured.output().contains("R9"), captured.output());
        assertTrue(captured.output().contains("processing_error"), captured.output());
        assertTrue(captured.output().contains("R8"), captured.output());
        assertEquals(before, Files.readString(journal));
    }

    @Test void needsReconciliationIsNeverClearedAutomatically() throws Exception {
        Path csv = temp.resolve("held.csv"), journal = temp.resolve("held.jsonl");
        String changed = "https://www.tiktok.com/@other/video/9876543210";
        Files.writeString(journal, "{\"key\":\"id:r1\",\"status\":\"needs_reconciliation\",\"videoUrl\":\"" + URL
                + "\",\"currentUrl\":\"" + changed + "\",\"run_id\":\"OLD\"}\n");
        Files.writeString(csv, "id,videoUrl\nr1," + changed + "\n");
        AtomicInteger sends = new AtomicInteger();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            sends.incrementAndGet(); throw new AssertionError("must not read or create anything");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, client));
        assertEquals(0, sends.get());
        assertEquals("needs_reconciliation", lastRecord(journal).path("status").asText());
    }

    // --- P2: configurable wait limit ---------------------------------------------------------

    @Test void waitLimitsDefaultTo900SecondsAndCanBeOverridden() {
        assertEquals(Duration.ofSeconds(900), ApifyClient.DEFAULT_MAX_WAIT);
        assertEquals(1, ApifyClient.parseMaxWaitSeconds("1"));
        assertEquals(86_400, ApifyClient.parseMaxWaitSeconds("86400"));
        assertEquals(900, CsvBatch.parseCli(new String[]{"--csv", "input.csv"}).maxWait().toSeconds());
        assertEquals(5, CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", "5"}).maxWait().toSeconds());
        assertEquals(86_400, CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", "86400"}).maxWait().toSeconds());
        assertEquals(900, SingleUrl.parseOptions(new String[]{URL}).maxWaitSeconds());
        assertEquals(900, SingleUrl.parseOptions(new String[0]).maxWaitSeconds());
        assertEquals(30, SingleUrl.parseOptions(new String[]{"--max-wait", "30"}).maxWaitSeconds());
        assertEquals(URL, SingleUrl.parseOptions(new String[]{"--video-url", URL, "--max-wait", "30"}).url());
        assertEquals(900, AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1"}).maxWaitSeconds());
        assertEquals(7, AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1", "--max-wait", "7"}).maxWaitSeconds());
        assertEquals(86_400, AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1", "--max-wait", "86400"}).maxWaitSeconds());
        assertThrows(IllegalArgumentException.class, () -> CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", "0"}));
        assertThrows(IllegalArgumentException.class, () -> SingleUrl.parseOptions(new String[]{"--max-wait", "0"}));
        assertThrows(IllegalArgumentException.class, () -> CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", "86401"}));
        assertThrows(IllegalArgumentException.class, () -> CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", Long.toString(Long.MAX_VALUE)}));
        assertThrows(IllegalArgumentException.class, () -> SingleUrl.parseOptions(new String[]{"--max-wait", "86401"}));
        assertThrows(IllegalArgumentException.class, () -> SingleUrl.parseOptions(new String[]{"--max-wait", Long.toString(Long.MAX_VALUE)}));
        assertThrows(IllegalArgumentException.class, () -> AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1", "--max-wait", "86401"}));
        assertThrows(IllegalArgumentException.class, () -> AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1", "--max-wait", Long.toString(Long.MAX_VALUE)}));
        assertThrows(IllegalArgumentException.class, () -> SingleUrl.parseOptions(new String[]{"--max-wait", "1.5"}));
        assertThrows(IllegalArgumentException.class, () -> CsvBatch.parseCli(new String[]{"--csv", "input.csv", "--max-wait", "abc"}));
        assertThrows(IllegalArgumentException.class, () -> AsyncRun.parseWaitArgs(new String[]{"wait", "--run-id", "R1", "--max-wait", "nope"}));
    }

    @Test void extremeWaitLimitsAreRejectedBeforeAnyRunCreation() throws Exception {
        AtomicInteger posts = new AtomicInteger();
        ApifyClient client = new ApifyClient("fake", (method, uri, auth, body) -> {
            if ("POST".equals(method)) posts.incrementAndGet();
            throw new AssertionError("wait validation must precede network transport");
        });
        assertEquals(1, SingleUrl.run(new String[]{"--max-wait", Long.toString(Long.MAX_VALUE)}, client));
        assertEquals(1, AsyncRun.run(new String[]{"wait", "--run-id", "R1", "--max-wait", "86401"}, client));
        assertEquals(1, AsyncRun.run(new String[]{"start", "--video-url", URL, "--max-wait", "86401"}, client));

        Path unusedCsv = temp.resolve("unused.csv");
        assertThrows(IllegalArgumentException.class, () -> CsvBatch.process(unusedCsv, temp.resolve("unused.jsonl"), 1, client,
                Duration.ofSeconds(Long.MAX_VALUE)));
        assertThrows(IllegalArgumentException.class, () -> client.waitForRun("R1", Duration.ofSeconds(Long.MAX_VALUE), Duration.ofSeconds(1)));
        assertEquals(0, posts.get());
    }

    @Test void waitTimeoutKeepsTheRunIdAndResumeOnlyReads() throws Exception {
        Path csv = temp.resolve("timeout.csv"), journal = temp.resolve("timeout.jsonl");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
        AtomicInteger posts = new AtomicInteger();
        ApifyClient stillRunning = new ApifyClient("apify_api_FAKEVALUE0123456789", (method, uri, auth, body) -> {
            if ("POST".equals(method)) { posts.incrementAndGet(); return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"RT\"}}"); }
            return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"RT\",\"status\":\"RUNNING\"}}");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, stillRunning, Duration.ofSeconds(1)));
        assertEquals(1, posts.get());
        JsonNode pending = lastRecord(journal);
        assertEquals("run_pending", pending.path("status").asText());
        assertEquals("RT", pending.path("run_id").asText());
        assertTrue(pending.path("error").asText().contains("same Run ID"), pending.path("error").asText());

        AtomicInteger resumePosts = new AtomicInteger(), resumeReads = new AtomicInteger();
        ApifyClient finished = new ApifyClient("apify_api_FAKEVALUE0123456789", (method, uri, auth, body) -> {
            if ("POST".equals(method)) { resumePosts.incrementAndGet(); return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"RX\"}}"); }
            resumeReads.incrementAndGet();
            if (uri.getRawPath().equals("/v2/datasets/DT/items")) return new ApifyClient.ApiResponse(200, "[{\"text\":\"late\",\"errMsg\":\"\"}]");
            return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"RT\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"DT\"}}");
        });
        assertEquals(0, CsvBatch.process(csv, journal, 1, finished, Duration.ofSeconds(5)));
        assertEquals(0, resumePosts.get());
        assertEquals(2, resumeReads.get());
        assertEquals("transcript_success", lastRecord(journal).path("status").asText());
    }

    @Test void knownRunWaitErrorStaysRecoverableAndResumeUsesOnlyGet() throws Exception {
        Path csv = temp.resolve("known-run.csv"), journal = temp.resolve("known-run.jsonl");
        Files.writeString(csv, "id,videoUrl\nr1," + URL + "\n");
        AtomicInteger firstPosts = new AtomicInteger();
        ApifyClient interrupted = new ApifyClient("fake", (method, uri, auth, body) -> {
            if ("POST".equals(method)) {
                firstPosts.incrementAndGet();
                return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"KNOWN1\"}}");
            }
            throw new IOException("temporary Run lookup interruption");
        });
        assertEquals(1, CsvBatch.process(csv, journal, 1, interrupted, Duration.ofSeconds(1)));
        assertEquals(1, firstPosts.get());
        JsonNode failedWait = lastRecord(journal);
        assertEquals("processing_error", failedWait.path("status").asText());
        assertEquals("KNOWN1", failedWait.path("run_id").asText());

        AtomicInteger resumePosts = new AtomicInteger();
        List<String> reads = new ArrayList<>();
        ApifyClient resumed = new ApifyClient("fake", (method, uri, auth, body) -> {
            if ("POST".equals(method)) {
                resumePosts.incrementAndGet();
                return new ApifyClient.ApiResponse(201, "{\"data\":{\"id\":\"UNEXPECTED\"}}");
            }
            reads.add(uri.getRawPath());
            if (uri.getRawPath().equals("/v2/actor-runs/KNOWN1")) {
                return new ApifyClient.ApiResponse(200, "{\"data\":{\"id\":\"KNOWN1\",\"status\":\"SUCCEEDED\",\"defaultDatasetId\":\"KNOWN_DS\"}}");
            }
            if (uri.getRawPath().equals("/v2/datasets/KNOWN_DS/items")) {
                return new ApifyClient.ApiResponse(200, "[{\"text\":\"recovered\",\"errMsg\":\"\"}]");
            }
            throw new AssertionError("unexpected GET " + uri);
        });
        assertEquals(0, CsvBatch.process(csv, journal, 1, resumed, Duration.ofSeconds(5)));
        assertEquals(0, resumePosts.get());
        assertEquals(List.of("/v2/actor-runs/KNOWN1", "/v2/datasets/KNOWN_DS/items"), reads);
        assertEquals("transcript_success", lastRecord(journal).path("status").asText());
        assertEquals("KNOWN1", lastRecord(journal).path("run_id").asText());
    }

    // --- P2: any non-empty non-terminal status keeps polling ----------------------------------

    @Test void nonTerminalRunStatusesKeepPollingUntilATerminalOne() throws Exception {
        List<String> statuses = List.of("ABORTING", "TIMING-OUT", "SOMETHING-NEW", "SUCCEEDED");
        AtomicInteger reads = new AtomicInteger();
        List<String> paths = new ArrayList<>();
        ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
            paths.add(uri.getRawPath());
            if (uri.getRawPath().startsWith("/v2/actor-runs/")) {
                String status = statuses.get(Math.min(reads.getAndIncrement(), statuses.size() - 1));
                return new ApifyClient.ApiResponse(200,
                        "{\"data\":{\"id\":\"R1\",\"status\":\"" + status + "\",\"defaultDatasetId\":\"D1\"}}");
            }
            return new ApifyClient.ApiResponse(200, "[{\"text\":\"done\",\"errMsg\":\"\"}]");
        });
        JsonNode run = client.waitForRun("R1", Duration.ofSeconds(5), Duration.ofMillis(1));
        assertEquals("SUCCEEDED", run.path("status").asText());
        assertEquals(4, reads.get());
        assertNull(TranscriptResult.failure(run, client.getDatasetItems("D1")));
        assertEquals("/v2/datasets/D1/items", paths.get(paths.size() - 1));
        assertTrue(ApifyClient.isTerminal("TIMED-OUT"));
        assertFalse(ApifyClient.isTerminal("TIMING-OUT"));
        assertFalse(ApifyClient.isTerminal("ABORTING"));
    }

    @Test void blankOrNonTextualRunStatusIsRejectedImmediately() {
        for (String payload : List.of(
                "{\"data\":{\"id\":\"R1\",\"status\":\"\"}}",
                "{\"data\":{\"id\":\"R1\",\"status\":\"   \"}}",
                "{\"data\":{\"id\":\"R1\",\"status\":42}}",
                "{\"data\":{\"id\":\"R1\"}}")) {
            AtomicInteger reads = new AtomicInteger();
            ApifyClient client = new ApifyClient("t", (method, uri, auth, body) -> {
                reads.incrementAndGet();
                return new ApifyClient.ApiResponse(200, payload);
            });
            ApifyClient.ApiException error = assertThrows(ApifyClient.ApiException.class,
                    () -> client.waitForRun("R1", Duration.ofSeconds(1), Duration.ofMillis(1)));
            assertTrue(error.getMessage().contains("Invalid Run API response"), payload);
            assertEquals(1, reads.get(), payload);
        }
    }

    @FunctionalInterface
    private interface BatchAction { int run() throws Exception; }

    private record Captured(int code, String output) {}

    private Captured runCapturingStdout(BatchAction action) throws Exception {
        PrintStream original = System.out;
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        System.setOut(new PrintStream(buffer, true, StandardCharsets.UTF_8));
        try {
            return new Captured(action.run(), buffer.toString(StandardCharsets.UTF_8));
        } finally {
            System.setOut(original);
        }
    }

    private static JsonNode lastRecord(Path journal) throws IOException {
        List<String> lines = Files.readAllLines(journal);
        for (int i = lines.size() - 1; i >= 0; i--) {
            if (!lines.get(i).isBlank()) return JSON.readTree(lines.get(i));
        }
        throw new AssertionError("journal is empty");
    }
}
