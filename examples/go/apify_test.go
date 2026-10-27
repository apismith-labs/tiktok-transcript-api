package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type redirectingTestTransport struct {
	handler http.HandlerFunc
	seen    atomic.Int32
	mu      chan *http.Request
}

func (r *redirectingTestTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	r.seen.Add(1)
	if r.mu != nil {
		r.mu <- request.Clone(context.Background())
	}
	recorder := httptest.NewRecorder()
	r.handler.ServeHTTP(recorder, request)
	return recorder.Result(), nil
}

func testAPI(t *testing.T, handler http.HandlerFunc) (*API, *http.Client, *redirectingTestTransport) {
	t.Helper()
	transport := &redirectingTestTransport{handler: handler, mu: make(chan *http.Request, 32)}
	client := newHTTPClient()
	client.Transport = transport
	api := NewAPI("fake-token-123456", client)
	api.pollInterval = time.Millisecond
	return api, client, transport
}

func writeJSONResponse(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

func TestCreateRunFixedRequestAndIgnoresActorEnvironment(t *testing.T) {
	t.Setenv("APIFY_ACTOR_ID", "instagram-actor")
	var requestBody []byte
	api, _, transport := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		requestBody, _ = io.ReadAll(r.Body)
		writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"R1"}}`)
	})
	run, err := api.startRun(defaultVideoURL)
	if err != nil {
		t.Fatal(err)
	}
	if run.ID != "R1" || transport.seen.Load() != 1 {
		t.Fatalf("run=%+v requests=%d", run, transport.seen.Load())
	}
	req := <-transport.mu
	if req.Method != http.MethodPost || req.URL.Host != "api.apify.com" || req.URL.Path != "/v2/actors/apple_yang~tiktok-transcripts-scraper/runs" {
		t.Fatalf("unexpected request target: %s %s", req.Method, req.URL)
	}
	if req.URL.RawQuery != "" || strings.Contains(req.URL.String(), "fake-token") {
		t.Fatalf("token leaked into URL: %s", req.URL)
	}
	if req.Header.Get("Authorization") != "Bearer fake-token-123456" {
		t.Fatalf("unexpected Authorization header: %q", req.Header.Get("Authorization"))
	}
	var input map[string]any
	if err := json.Unmarshal(requestBody, &input); err != nil {
		t.Fatal(err)
	}
	if len(input) != 1 || input["videoUrl"] != defaultVideoURL {
		t.Fatalf("unexpected payload: %#v", input)
	}
}

func TestCreateRunUnknownResponsesAreNeverRetried(t *testing.T) {
	for _, test := range []struct {
		name   string
		status int
		body   string
	}{
		{"non-2xx", http.StatusServiceUnavailable, `service unavailable`},
		{"malformed-json", http.StatusOK, `{`},
		{"null", http.StatusOK, `null`},
		{"array", http.StatusOK, `[]`},
		{"missing-data", http.StatusOK, `{}`},
		{"invalid-data", http.StatusOK, `{"data":[]}`},
		{"missing-id", http.StatusOK, `{"data":{"status":"READY"}}`},
	} {
		t.Run(test.name, func(t *testing.T) {
			api, _, transport := testAPI(t, func(w http.ResponseWriter, _ *http.Request) { writeJSONResponse(w, test.status, test.body) })
			_, err := api.startRun(defaultVideoURL)
			if apiErrorKind(err) != "run_creation_unknown" || transport.seen.Load() != 1 {
				t.Fatalf("err=%v requests=%d", err, transport.seen.Load())
			}
			if strings.Contains(err.Error(), "fake-token-123456") {
				t.Fatalf("token leaked in error: %v", err)
			}
		})
	}
}

func TestCreateRedirectIsNotFollowed(t *testing.T) {
	var requests atomic.Int32
	api, _, transport := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		http.Redirect(w, r, "/other", http.StatusTemporaryRedirect)
	})
	_, err := api.startRun(defaultVideoURL)
	if apiErrorKind(err) != "run_creation_unknown" || transport.seen.Load() != 1 || requests.Load() != 1 {
		t.Fatalf("err=%v transport=%d server=%d", err, transport.seen.Load(), requests.Load())
	}
}

func TestCreateTransportFailureIsUnknownOnce(t *testing.T) {
	for name, sendErr := range map[string]error{
		"disconnect": errors.New("private fake transport failure"),
		"timeout":    context.DeadlineExceeded,
	} {
		t.Run(name, func(t *testing.T) {
			var calls atomic.Int32
			client := newHTTPClient()
			client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
				calls.Add(1)
				return nil, sendErr
			})
			api := NewAPI("fake-token-123456", client)
			_, err := api.startRun(defaultVideoURL)
			if apiErrorKind(err) != "run_creation_unknown" || calls.Load() != 1 || strings.Contains(err.Error(), "fake-token-123456") {
				t.Fatalf("err=%v calls=%d", err, calls.Load())
			}
		})
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func TestRunEnvelopeIDAndTerminalPolling(t *testing.T) {
	var reads atomic.Int32
	api, _, transport := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		reads.Add(1)
		if r.URL.Path != "/v2/actor-runs/R1" {
			t.Fatalf("unexpected GET path %q", r.URL.Path)
		}
		writeJSONResponse(w, http.StatusOK, `{"data":{"id":"R1","status":"SUCCEEDED","defaultDatasetId":"D1"}}`)
	})
	run, err := api.waitForRun("R1", 1)
	if err != nil || run.ID != "R1" || run.DefaultDatasetID != "D1" || reads.Load() != 1 {
		t.Fatalf("run=%+v err=%v reads=%d", run, err, reads.Load())
	}
	if req := <-transport.mu; req.URL.Host != "api.apify.com" || req.Method != http.MethodGet {
		t.Fatalf("unexpected Run request: %s %s", req.Method, req.URL)
	}
}

func TestUnknownNonterminalStatusContinuesPolling(t *testing.T) {
	var reads atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) {
		status := "ABORTING"
		if reads.Add(1) == 2 {
			status = "SUCCEEDED"
		}
		writeJSONResponse(w, http.StatusOK, fmt.Sprintf(`{"data":{"id":"R1","status":%q,"defaultDatasetId":"D1"}}`, status))
	})
	run, err := api.waitForRun("R1", 2)
	if err != nil || run.Status != "SUCCEEDED" || reads.Load() != 2 {
		t.Fatalf("run=%+v err=%v reads=%d", run, err, reads.Load())
	}
}

func TestMalformedRunResponseAndMismatchedIDFail(t *testing.T) {
	for _, body := range []string{
		`{}`, `{"data":[]}`, `{"data":{"id":"OTHER","status":"RUNNING"}}`,
		`{"data":{"id":"R1","status":" "}}`, `{"data":{"id":"R1","status":4}}`,
	} {
		t.Run(body, func(t *testing.T) {
			api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) { writeJSONResponse(w, http.StatusOK, body) })
			_, err := api.getRun(context.Background(), "R1")
			if apiErrorKind(err) != "run_lookup_error" {
				t.Fatalf("expected run lookup response error, got %v", err)
			}
		})
	}
}

func TestRunNotFoundIsLookupErrorAndDatasetMalformedIsDatasetError(t *testing.T) {
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v2/actor-runs/MISSING" {
			writeJSONResponse(w, http.StatusNotFound, `{}`)
			return
		}
		writeJSONResponse(w, http.StatusOK, `null`)
	})
	if _, err := api.getRun(context.Background(), "MISSING"); apiErrorKind(err) != "run_lookup_error" {
		t.Fatalf("wrong missing Run error: %v", err)
	}
	if _, err := api.datasetItems("D1"); apiErrorKind(err) != "dataset_error" {
		t.Fatalf("wrong malformed Dataset error: %v", err)
	}
}

func TestDatasetAndTranscriptClassification(t *testing.T) {
	tests := []struct {
		name   string
		status string
		ds     string
		items  string
		want   string
	}{
		{"success", "SUCCEEDED", "D", `[{"text":"hello","errMsg":""}]`, ""},
		{"empty-dataset", "SUCCEEDED", "D", `[]`, "Run succeeded but the Dataset is empty"},
		{"empty-text", "SUCCEEDED", "D", `[{"text":"  "}]`, "transcript text is empty"},
		{"missing-text", "SUCCEEDED", "D", `[{"segments":[]}]`, "transcript text is empty"},
		{"err-msg", "SUCCEEDED", "D", `[{"text":"hello","errMsg":"failed"}]`, "non-empty errMsg"},
		{"missing-dataset", "SUCCEEDED", "", `[]`, "without a default Dataset ID"},
		{"failed-run", "FAILED", "", `[]`, "Actor Run failed"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var items []json.RawMessage
			_ = json.Unmarshal([]byte(test.items), &items)
			got := transcriptFailure(Run{Status: test.status, DefaultDatasetID: test.ds}, items)
			if test.want == "" && got != "" || test.want != "" && !strings.Contains(got, test.want) {
				t.Fatalf("transcriptFailure=%q want contains %q", got, test.want)
			}
		})
	}
	api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) { writeJSONResponse(w, http.StatusOK, `[]`) })
	items, err := api.datasetItems("D1")
	if err != nil || len(items) != 0 {
		t.Fatalf("items=%v err=%v", items, err)
	}
}

func TestCLIStartWaitAndInvalidWaitDoNotPost(t *testing.T) {
	var posts, gets atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			posts.Add(1)
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"R1"}}`)
			return
		}
		gets.Add(1)
		if r.URL.Path == "/v2/actor-runs/R1" {
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"R1","status":"SUCCEEDED","defaultDatasetId":"D1"}}`)
			return
		}
		writeJSONResponse(w, http.StatusOK, `[{"text":"ok"}]`)
	})
	var out bytes.Buffer
	if err := runAsync([]string{"start", "--video-url", defaultVideoURL}, api, &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Run ID: R1") || posts.Load() != 1 {
		t.Fatalf("out=%q posts=%d", out.String(), posts.Load())
	}
	if err := runAsync([]string{"wait", "--run-id", "R1", "--max-wait", "1"}, api, &out); err != nil {
		t.Fatal(err)
	}
	if posts.Load() != 1 || gets.Load() != 2 {
		t.Fatalf("wait started a Run: posts=%d gets=%d", posts.Load(), gets.Load())
	}
	postsBefore := posts.Load()
	if err := runSingle([]string{"--video-url", defaultVideoURL, "--max-wait", "9223372036854775807"}, api, &out, t.TempDir()); err == nil {
		t.Fatal("expected huge wait to be rejected")
	}
	if err := runAsync([]string{"start", "--video-url", defaultVideoURL, "--unsupported"}, api, &out); err == nil {
		t.Fatal("expected invalid start args to be rejected")
	}
	if err := runAsync([]string{"wait", "--run-id", "R1", "--max-wait", "9223372036854775807"}, api, &out); err == nil {
		t.Fatal("expected extreme wait to be rejected")
	}
	if posts.Load() != postsBefore {
		t.Fatalf("invalid CLI args sent POST: before=%d after=%d", postsBefore, posts.Load())
	}
}

func TestSingleRunIDIsPrintedBeforeWaitingAndFullDatasetIsSaved(t *testing.T) {
	dir := t.TempDir()
	var output bytes.Buffer
	t.Setenv("TIKTOK_VIDEO_URL", "https://www.tiktok.com/@wrong/video/999")
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v2/actors/apple_yang~tiktok-transcripts-scraper/runs":
			var input struct {
				VideoURL string `json:"videoUrl"`
			}
			_ = json.NewDecoder(r.Body).Decode(&input)
			if input.VideoURL != defaultVideoURL {
				t.Errorf("default URL was overridden by environment: %q", input.VideoURL)
			}
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"SINGLE1"}}`)
		case "/v2/actor-runs/SINGLE1":
			if !strings.Contains(output.String(), "Run ID: SINGLE1") {
				t.Errorf("wait began before Run ID was printed: %q", output.String())
			}
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"SINGLE1","status":"SUCCEEDED","defaultDatasetId":"DS1"}}`)
		case "/v2/datasets/DS1/items":
			writeJSONResponse(w, http.StatusOK, `[{"text":"transcript","segments":[{"start":0,"end":1,"text":"transcript"}]}]`)
		default:
			t.Errorf("unexpected path %s", r.URL.Path)
		}
	})
	if err := runSingle(nil, api, &output, dir); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "sample-output", "generated", "go-single-url-response.json"))
	if err != nil || !strings.Contains(string(data), "segments") || !strings.Contains(output.String(), "Run ID: SINGLE1") || !strings.Contains(output.String(), "transcript") {
		t.Fatalf("output=%q data=%s err=%v", output.String(), data, err)
	}
	if strings.Contains(output.String(), "fake-token-123456") || strings.Contains(string(data), "fake-token-123456") {
		t.Fatal("test token leaked into stdout or output file")
	}
}

func TestSingleOutputPreflightFailureDoesNotCreateRun(t *testing.T) {
	root := t.TempDir()
	blockedRoot := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(blockedRoot, []byte("block"), 0o600); err != nil {
		t.Fatal(err)
	}
	var posts atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			posts.Add(1)
		}
		writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"SHOULD_NOT_START"}}`)
	})
	err := runSingle(nil, api, io.Discard, blockedRoot)
	if err == nil || !strings.Contains(err.Error(), "output preflight failed before Run creation") {
		t.Fatalf("expected preflight error, got %v", err)
	}
	if posts.Load() != 0 {
		t.Fatalf("output preflight failure sent %d POST requests", posts.Load())
	}
}

func TestSingleFallsBackToWorkingDirectoryWithoutRepositoryMarkers(t *testing.T) {
	workingDir := t.TempDir()
	oldWorkingDir, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(workingDir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(oldWorkingDir); err != nil {
			t.Errorf("restore working directory: %v", err)
		}
	})
	var output bytes.Buffer
	var posts atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/v2/actors/" + actorAPIID + "/runs":
			posts.Add(1)
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"COPY1"}}`)
		case "/v2/actor-runs/COPY1":
			if !strings.Contains(output.String(), "Run ID: COPY1") {
				t.Errorf("Run ID wasn't written before wait: %q", output.String())
			}
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"COPY1","status":"SUCCEEDED","defaultDatasetId":"COPY_DS"}}`)
		case "/v2/datasets/COPY_DS/items":
			writeJSONResponse(w, http.StatusOK, `[{"text":"copied example transcript","errMsg":""}]`)
		default:
			t.Errorf("unexpected request path %s", r.URL.Path)
		}
	})
	if err := runSingle(nil, api, &output, ""); err != nil {
		t.Fatal(err)
	}
	if posts.Load() != 1 {
		t.Fatalf("expected one Run creation POST, got %d", posts.Load())
	}
	resultPath := filepath.Join(workingDir, "sample-output", "generated", "go-single-url-response.json")
	data, err := os.ReadFile(resultPath)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "copied example transcript") || !strings.Contains(string(data), "copied example transcript") {
		t.Fatalf("transcript not visible; output=%q json=%s", output.String(), data)
	}
	if strings.Contains(output.String(), "fake-token-123456") || strings.Contains(string(data), "fake-token-123456") {
		t.Fatal("test token leaked into stdout or output file")
	}
}

func TestAsyncWaitTimeoutCanBeRetriedWithSameRunID(t *testing.T) {
	var posts, gets atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			posts.Add(1)
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"R-TIMEOUT"}}`)
			return
		}
		gets.Add(1)
		writeJSONResponse(w, http.StatusOK, `{"data":{"id":"R-TIMEOUT","status":"RUNNING"}}`)
	})
	api.pollInterval = 5 * time.Second
	err := runAsync([]string{"wait", "--run-id", "R-TIMEOUT", "--max-wait", "1"}, api, io.Discard)
	if apiErrorKind(err) != "wait_timeout" || !strings.Contains(err.Error(), "R-TIMEOUT") {
		t.Fatalf("expected same-ID wait timeout, got %v", err)
	}
	if posts.Load() != 0 || gets.Load() != 1 {
		t.Fatalf("wait sent POST=%d GET=%d", posts.Load(), gets.Load())
	}
}

func TestMaxWaitDefaultsBoundsAndExtremeValues(t *testing.T) {
	if defaultMaxWait != 900 || maxMaxWait != 86400 {
		t.Fatalf("unexpected defaults: default=%d max=%d", defaultMaxWait, maxMaxWait)
	}
	for _, valid := range []string{"1", "900", "86400"} {
		if _, err := parseMaxWait(valid); err != nil {
			t.Fatalf("parseMaxWait(%q): %v", valid, err)
		}
	}
	for _, invalid := range []string{"0", "-1", "86401", "9223372036854775807", "1.5", "abc"} {
		if _, err := parseMaxWait(invalid); err == nil {
			t.Fatalf("parseMaxWait(%q) unexpectedly succeeded", invalid)
		}
	}
	client := newHTTPClient()
	client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid wait limit reached HTTP transport")
		return nil, nil
	})
	api := NewAPI("fake", client)
	if _, err := api.waitForRun("R1", int64(^uint64(0)>>1)); err == nil {
		t.Fatal("expected max int64 to be rejected")
	}
	if err := processCSV(filepath.Join(t.TempDir(), "not-created.csv"), filepath.Join(t.TempDir(), "out.jsonl"), 1,
		int64(^uint64(0)>>1), api, io.Discard); err == nil || !strings.Contains(err.Error(), "between 1 and 86400") {
		t.Fatalf("direct ProcessCSV should reject extreme wait before reading or posting, got %v", err)
	}
}

func TestCSVWriteAheadUnknownNoRetryAndKnownRunResume(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	if err := os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var firstPosts atomic.Int32
	firstAPI, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			firstPosts.Add(1)
			contents, _ := os.ReadFile(journalPath)
			if !strings.Contains(string(contents), `"status":"start_attempted"`) {
				t.Errorf("POST happened before start_attempted was flushed: %s", contents)
			}
			writeJSONResponse(w, http.StatusBadGateway, `not sure`)
			return
		}
		writeJSONResponse(w, http.StatusInternalServerError, `{}`)
	})
	if err := processCSV(csvPath, journalPath, 1, 900, firstAPI, io.Discard); err == nil {
		t.Fatal("expected unknown creation to fail the batch")
	}
	if firstPosts.Load() != 1 {
		t.Fatalf("POST count=%d", firstPosts.Load())
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		t.Fatal(err)
	}
	if latest["id:r1"].Status != "run_creation_unknown" || latest["id:r1"].RunID != "" {
		t.Fatalf("unexpected unknown record: %+v", latest["id:r1"])
	}
	if err := processCSV(csvPath, journalPath, 1, 900, firstAPI, io.Discard); err == nil {
		t.Fatal("unknown creation row must remain a failed batch")
	}
	if firstPosts.Load() != 1 {
		t.Fatalf("unknown result was reposted: %d", firstPosts.Load())
	}
}

func TestCSVKnownRunRecoverableStatesReuseGETOnly(t *testing.T) {
	for _, state := range []string{"run_pending", "dataset_error", "processing_error"} {
		t.Run(state, func(t *testing.T) {
			dir := t.TempDir()
			csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
			_ = os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600)
			line, _ := json.Marshal(batchRecord{Key: "id:r1", RowNum: 2, VideoURL: defaultVideoURL, RunID: "R1", Status: state})
			_ = os.WriteFile(journalPath, append(line, '\n'), 0o600)
			var posts atomic.Int32
			api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodPost {
					posts.Add(1)
					writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"OTHER"}}`)
				} else if r.URL.Path == "/v2/actor-runs/R1" {
					writeJSONResponse(w, http.StatusOK, `{"data":{"id":"R1","status":"SUCCEEDED","defaultDatasetId":"D1"}}`)
				} else {
					writeJSONResponse(w, http.StatusOK, `[{"text":"ok"}]`)
				}
			})
			if err := processCSV(csvPath, journalPath, 2, 900, api, io.Discard); err != nil {
				t.Fatal(err)
			}
			if posts.Load() != 0 {
				t.Fatalf("%s recovery sent %d POST requests", state, posts.Load())
			}
			latest, _ := readJournal(journalPath)
			if latest["id:r1"].RunID != "R1" || latest["id:r1"].Status != "transcript_success" {
				t.Fatalf("unexpected resumed record: %+v", latest["id:r1"])
			}
		})
	}
}

func TestCompletedWithTranscriptJournalStateIsSuccessfulAndNotReposted(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	if err := os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	record, err := json.Marshal(batchRecord{
		Key: "id:r1", RowNum: 2, ID: "r1", VideoURL: defaultVideoURL,
		RunID: "OLD-RUN", Status: "completed_with_transcript",
	})
	if err != nil {
		t.Fatal(err)
	}
	journalBytes := append(record, '\n')
	if err := os.WriteFile(journalPath, journalBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	var requests atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) {
		requests.Add(1)
		writeJSONResponse(w, http.StatusInternalServerError, `{}`)
	})
	var summary bytes.Buffer
	if err := processCSV(csvPath, journalPath, 1, 900, api, &summary); err != nil {
		t.Fatalf("completed_with_transcript should count as success: %v (%s)", err, summary.String())
	}
	if requests.Load() != 0 {
		t.Fatalf("completed row made %d requests", requests.Load())
	}
	if !strings.Contains(summary.String(), "completed_with_transcript:1") {
		t.Fatalf("summary omitted completed journal status: %q", summary.String())
	}
	after, err := os.ReadFile(journalPath)
	if err != nil || !bytes.Equal(after, journalBytes) {
		t.Fatalf("completed row journal changed: %s err=%v", after, err)
	}
}

func TestCompletedWithTranscriptUrlChangeStartsFreshRun(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	oldURL := defaultVideoURL
	newURL := "https://www.tiktok.com/@edited/video/7777777777"
	if err := os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+newURL+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	line, err := json.Marshal(batchRecord{Key: "id:r1", ID: "r1", VideoURL: oldURL, RunID: "OLD", Status: "completed_with_transcript", Items: []json.RawMessage{json.RawMessage(`{"text":"old transcript"}`)}})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(journalPath, append(line, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	var posts atomic.Int32
	var datasetPaths []string
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			posts.Add(1)
			var payload map[string]string
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil || payload["videoUrl"] != newURL {
				t.Errorf("new Run payload mismatch: %#v err=%v", payload, err)
			}
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"NEW"}}`)
			return
		}
		if r.URL.Path == "/v2/actor-runs/NEW" {
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"NEW","status":"SUCCEEDED","defaultDatasetId":"NEW_DS"}}`)
			return
		}
		datasetPaths = append(datasetPaths, r.URL.Path)
		writeJSONResponse(w, http.StatusOK, `[{"text":"new transcript","errMsg":""}]`)
	})
	var summary bytes.Buffer
	if err := processCSV(csvPath, journalPath, 1, 900, api, &summary); err != nil {
		t.Fatal(err)
	}
	if posts.Load() != 1 || len(datasetPaths) != 1 || datasetPaths[0] != "/v2/datasets/NEW_DS/items" {
		t.Fatalf("posts=%d dataset paths=%v", posts.Load(), datasetPaths)
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		t.Fatal(err)
	}
	if got := latest["id:r1"]; got.VideoURL != newURL || got.RunID != "NEW" || got.Status != "transcript_success" {
		t.Fatalf("terminal URL edit did not create a fresh result: %+v", got)
	}
}

func TestRecoverableJournalStateWithoutRunIDRequiresReconciliation(t *testing.T) {
	states := []string{"run_pending", "dataset_error", "processing_error"}
	for _, state := range states {
		for _, runIDField := range []string{"missing", "empty", "whitespace"} {
			t.Run(state+"-"+runIDField, func(t *testing.T) {
				dir := t.TempDir()
				csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
				if err := os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600); err != nil {
					t.Fatal(err)
				}
				record := map[string]any{
					"key": "id:r1", "row_number": 2, "id": "r1", "videoUrl": defaultVideoURL, "status": state, "error": "prior diagnostic",
				}
				switch runIDField {
				case "empty":
					record["run_id"] = ""
				case "whitespace":
					record["run_id"] = "  \t"
				}
				line, err := json.Marshal(record)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(journalPath, append(line, '\n'), 0o600); err != nil {
					t.Fatal(err)
				}
				var requests atomic.Int32
				api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) {
					requests.Add(1)
					writeJSONResponse(w, http.StatusInternalServerError, `{}`)
				})
				if err := processCSV(csvPath, journalPath, 1, 900, api, io.Discard); err == nil {
					t.Fatal("missing Run ID must keep the batch unresolved")
				}
				latest, err := readJournal(journalPath)
				if err != nil {
					t.Fatal(err)
				}
				resolved := latest["id:r1"]
				if resolved.Status != "needs_reconciliation" || resolved.PreviousStatus != state || resolved.RunID != "" || resolved.OriginalURL != defaultVideoURL || resolved.CurrentURL != defaultVideoURL {
					t.Fatalf("unexpected fail-closed record: %+v", resolved)
				}
				if !strings.Contains(resolved.Error, "prior diagnostic") || !strings.Contains(resolved.Error, "no valid Run ID") {
					t.Fatalf("missing diagnostic: %+v", resolved)
				}
				if requests.Load() != 0 {
					t.Fatalf("missing-ID record made %d requests", requests.Load())
				}
				if err := processCSV(csvPath, journalPath, 1, 900, api, io.Discard); err == nil {
					t.Fatal("reconciliation state must remain unresolved on later runs")
				}
				if requests.Load() != 0 {
					t.Fatalf("reconciliation rerun made %d requests", requests.Load())
				}
				var listing bytes.Buffer
				if err := reconcileCSV(csvPath, journalPath, &listing); err != nil {
					t.Fatal(err)
				}
				for _, field := range []string{"needs_reconciliation", "original_url=" + defaultVideoURL, "current_url=" + defaultVideoURL, "run_id=", "prior diagnostic"} {
					if !strings.Contains(listing.String(), field) {
						t.Fatalf("reconcile output %q missing %q", listing.String(), field)
					}
				}
			})
		}
	}
}

func TestURLChangeAndMissingRunIDPreservesBothReconciliationReasons(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	oldURL := defaultVideoURL
	newURL := "https://www.tiktok.com/@edited/video/7777777777"
	if err := os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+newURL+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	line, err := json.Marshal(map[string]any{
		"key": "id:r1", "row_number": 2, "id": "r1", "videoUrl": oldURL,
		"run_id": "  ", "status": "run_pending",
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(journalPath, append(line, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	var requests atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) {
		requests.Add(1)
		writeJSONResponse(w, http.StatusInternalServerError, `{}`)
	})
	if err := processCSV(csvPath, journalPath, 1, 900, api, io.Discard); err == nil {
		t.Fatal("URL change with no Run ID must need reconciliation")
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		t.Fatal(err)
	}
	record := latest["id:r1"]
	if record.Status != "needs_reconciliation" || record.RunID != "" || record.OriginalURL != oldURL || record.CurrentURL != newURL {
		t.Fatalf("unexpected reconciliation record: %+v", record)
	}
	if !strings.Contains(record.Error, "no valid Run ID") || requests.Load() != 0 {
		t.Fatalf("missing diagnostic or unexpected request: err=%q requests=%d", record.Error, requests.Load())
	}
	var listing bytes.Buffer
	if err := reconcileCSV(csvPath, journalPath, &listing); err != nil {
		t.Fatal(err)
	}
	for _, value := range []string{oldURL, newURL, "needs_reconciliation"} {
		if !strings.Contains(listing.String(), value) {
			t.Fatalf("reconcile output %q omitted %q", listing.String(), value)
		}
	}
}

func TestCreatedRunWaitFailureKeepsIDAndResumeDoesNotPost(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	_ = os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600)
	var initialPosts atomic.Int32
	firstAPI, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			initialPosts.Add(1)
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"CREATED1"}}`)
			return
		}
		writeJSONResponse(w, http.StatusBadGateway, `{}`)
	})
	if err := processCSV(csvPath, journalPath, 1, 900, firstAPI, io.Discard); err == nil {
		t.Fatal("wait lookup error should fail the batch")
	}
	if initialPosts.Load() != 1 {
		t.Fatalf("initial POST count=%d", initialPosts.Load())
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		t.Fatal(err)
	}
	if got := latest["id:r1"]; got.Status != "processing_error" || got.RunID != "CREATED1" {
		t.Fatalf("known Run was misclassified: %+v", got)
	}

	var resumePosts atomic.Int32
	var resumePaths []string
	resumeAPI, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			resumePosts.Add(1)
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"WRONG"}}`)
			return
		}
		resumePaths = append(resumePaths, r.URL.Path)
		if r.URL.Path == "/v2/actor-runs/CREATED1" {
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"CREATED1","status":"SUCCEEDED","defaultDatasetId":"DS1"}}`)
		} else {
			writeJSONResponse(w, http.StatusOK, `[{"text":"resumed"}]`)
		}
	})
	if err := processCSV(csvPath, journalPath, 1, 900, resumeAPI, io.Discard); err != nil {
		t.Fatal(err)
	}
	if resumePosts.Load() != 0 || len(resumePaths) != 2 || resumePaths[0] != "/v2/actor-runs/CREATED1" || resumePaths[1] != "/v2/datasets/DS1/items" {
		t.Fatalf("resume POSTs=%d paths=%v", resumePosts.Load(), resumePaths)
	}
	latest, _ = readJournal(journalPath)
	if latest["id:r1"].Status != "transcript_success" || latest["id:r1"].RunID != "CREATED1" {
		t.Fatalf("unexpected resumed final record: %+v", latest["id:r1"])
	}
}

func TestCSVURLChangeReconcileAndTerminalReplacement(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	oldURL := defaultVideoURL
	newURL := "https://www.tiktok.com/@new/video/9876543210"
	_ = os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+newURL+"\n"), 0o600)
	line, _ := json.Marshal(batchRecord{Key: "id:r1", RowNum: 2, VideoURL: oldURL, RunID: "OLD", Status: "run_pending"})
	_ = os.WriteFile(journalPath, append(line, '\n'), 0o600)
	var sends atomic.Int32
	blockedAPI, _, _ := testAPI(t, func(w http.ResponseWriter, _ *http.Request) {
		sends.Add(1)
		writeJSONResponse(w, http.StatusOK, `{}`)
	})
	if err := processCSV(csvPath, journalPath, 1, 900, blockedAPI, io.Discard); err == nil {
		t.Fatal("changed unresolved row should require reconciliation")
	}
	if sends.Load() != 0 {
		t.Fatalf("changed unresolved row made %d requests", sends.Load())
	}
	contents, _ := os.ReadFile(journalPath)
	if !strings.Contains(string(contents), `"original_url":"`+oldURL+`"`) || !strings.Contains(string(contents), `"current_url":"`+newURL+`"`) || !strings.Contains(string(contents), `"run_id":"OLD"`) {
		t.Fatalf("reconciliation details missing: %s", contents)
	}
	before := append([]byte(nil), contents...)
	var out bytes.Buffer
	if err := reconcileCSV(csvPath, journalPath, &out); err != nil {
		t.Fatal(err)
	}
	after, _ := os.ReadFile(journalPath)
	if !bytes.Equal(before, after) || !strings.Contains(out.String(), "run_id=OLD") || !strings.Contains(out.String(), "original_url="+oldURL) || !strings.Contains(out.String(), "current_url="+newURL) {
		t.Fatalf("reconcile not read-only or incomplete: %q", out.String())
	}

	line, _ = json.Marshal(batchRecord{Key: "id:r1", RowNum: 2, VideoURL: oldURL, RunID: "OLD", Status: "transcript_success"})
	_ = os.WriteFile(journalPath, append(line, '\n'), 0o600)
	var posts atomic.Int32
	terminalAPI, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			posts.Add(1)
			body, _ := io.ReadAll(r.Body)
			if !bytes.Contains(body, []byte(newURL)) {
				t.Errorf("new Run used wrong URL: %s", body)
			}
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"NEW"}}`)
		} else if r.URL.Path == "/v2/actor-runs/NEW" {
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"NEW","status":"SUCCEEDED","defaultDatasetId":"DNEW"}}`)
		} else {
			writeJSONResponse(w, http.StatusOK, `[{"text":"new transcript"}]`)
		}
	})
	if err := processCSV(csvPath, journalPath, 1, 900, terminalAPI, io.Discard); err != nil {
		t.Fatal(err)
	}
	if posts.Load() != 1 {
		t.Fatalf("terminal URL change should create exactly one fresh Run, got %d", posts.Load())
	}
	latest, _ := readJournal(journalPath)
	if latest["id:r1"].VideoURL != newURL || latest["id:r1"].RunID != "NEW" || latest["id:r1"].Status != "transcript_success" {
		t.Fatalf("fresh URL result mismatched: %+v", latest["id:r1"])
	}
}

func TestCSVCurrentBatchSummaryIgnoresHistoricalRowsAndRejectsInvalidInputs(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "input.csv"), filepath.Join(dir, "out.jsonl")
	_ = os.WriteFile(csvPath, []byte("id,videoUrl\nr1,"+defaultVideoURL+"\n"), 0o600)
	old, _ := json.Marshal(batchRecord{Key: "id:removed", VideoURL: defaultVideoURL, Status: "processing_error", RunID: "OLD"})
	_ = os.WriteFile(journalPath, append(old, '\n'), 0o600)
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			writeJSONResponse(w, http.StatusCreated, `{"data":{"id":"R1"}}`)
		} else if r.URL.Path == "/v2/actor-runs/R1" {
			writeJSONResponse(w, http.StatusOK, `{"data":{"id":"R1","status":"SUCCEEDED","defaultDatasetId":"D1"}}`)
		} else {
			writeJSONResponse(w, http.StatusOK, `[{"text":"ok"}]`)
		}
	})
	if err := processCSV(csvPath, journalPath, 1, 900, api, io.Discard); err != nil {
		t.Fatalf("removed history affected current batch: %v", err)
	}

	for _, csvText := range []string{
		"id,other\nr1,x\n",
		"videoUrl,videoUrl\n" + defaultVideoURL + "," + defaultVideoURL + "\n",
		"videoUrl\n\"unterminated\n",
	} {
		sum := sha256.Sum256([]byte(csvText))
		t.Run(fmt.Sprintf("input-%x", sum[:4]), func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "bad.csv")
			_ = os.WriteFile(path, []byte(csvText), 0o600)
			if _, err := readCSVRows(path); err == nil {
				t.Fatal("expected bad CSV input to be diagnosed")
			}
		})
	}
	for _, test := range []struct {
		name string
		csv  string
		want string
	}{
		{"empty-url", "id,videoUrl\nr1,\n", "input_error"},
		{"duplicate-id", "id,videoUrl\nr1," + defaultVideoURL + "\nr1," + defaultVideoURL + "\n", "duplicate_id"},
	} {
		t.Run(test.name, func(t *testing.T) {
			badDir := t.TempDir()
			badCSV, badJournal := filepath.Join(badDir, "bad.csv"), filepath.Join(badDir, "bad.jsonl")
			_ = os.WriteFile(badCSV, []byte(test.csv), 0o600)
			client := newHTTPClient()
			client.Transport = roundTripFunc(func(*http.Request) (*http.Response, error) {
				t.Fatal("invalid input must not reach HTTP")
				return nil, nil
			})
			if err := processCSV(badCSV, badJournal, 1, 900, NewAPI("fake", client), io.Discard); err == nil {
				t.Fatal("invalid row must fail the batch")
			}
			latest, err := readJournal(badJournal)
			if err != nil {
				t.Fatal(err)
			}
			for _, record := range latest {
				if record.Status != test.want {
					t.Fatalf("got status %s, want %s", record.Status, test.want)
				}
			}
			if len(latest) == 0 {
				t.Fatal("invalid input was not recorded")
			}
		})
	}
}

func TestCSVConcurrencyIsBounded(t *testing.T) {
	dir := t.TempDir()
	csvPath, journalPath := filepath.Join(dir, "many.csv"), filepath.Join(dir, "out.jsonl")
	var csvData strings.Builder
	csvData.WriteString("videoUrl\n")
	for i := 0; i < 6; i++ {
		fmt.Fprintf(&csvData, "https://www.tiktok.com/@user/video/%d\n", i+1)
	}
	_ = os.WriteFile(csvPath, []byte(csvData.String()), 0o600)
	var active, peak, runCount atomic.Int32
	api, _, _ := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			now := active.Add(1)
			for old := peak.Load(); now > old && !peak.CompareAndSwap(old, now); old = peak.Load() {
			}
			time.Sleep(15 * time.Millisecond)
			active.Add(-1)
			id := fmt.Sprintf("R%d", runCount.Add(1))
			writeJSONResponse(w, http.StatusCreated, fmt.Sprintf(`{"data":{"id":%q}}`, id))
		} else if strings.HasPrefix(r.URL.Path, "/v2/actor-runs/") {
			id := filepath.Base(r.URL.Path)
			writeJSONResponse(w, http.StatusOK, fmt.Sprintf(`{"data":{"id":%q,"status":"SUCCEEDED","defaultDatasetId":%q}}`, id, "D"+id))
		} else {
			writeJSONResponse(w, http.StatusOK, `[{"text":"ok"}]`)
		}
	})
	if err := processCSV(csvPath, journalPath, 2, 900, api, io.Discard); err != nil {
		t.Fatal(err)
	}
	if peak.Load() > 2 || runCount.Load() != 6 {
		t.Fatalf("peak concurrency=%d runs=%d", peak.Load(), runCount.Load())
	}
}
