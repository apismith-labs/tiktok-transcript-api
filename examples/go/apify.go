package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const (
	actorAPIID       = "apple_yang~tiktok-transcripts-scraper"
	actorDisplayName = "apple_yang/tiktok-transcripts-scraper"
	apiHost          = "https://api.apify.com"
	defaultVideoURL  = "https://www.tiktok.com/@carter.braydon/video/7647694374876319007"
	defaultMaxWait   = int64(900)
	maxMaxWait       = int64(86400)
)

type HTTPDoer interface {
	Do(*http.Request) (*http.Response, error)
}

type APIError struct {
	Kind   string
	RunID  string
	Status int
	Detail string
}

func (e *APIError) Error() string {
	if e.Kind == "wait_timeout" && e.RunID != "" {
		return e.Kind + ": " + e.Detail + ": " + e.RunID
	}
	if e.Detail == "" {
		return e.Kind
	}
	return e.Kind + ": " + e.Detail
}

type API struct {
	token        string
	client       HTTPDoer
	pollInterval time.Duration
}

func NewAPI(token string, client HTTPDoer) *API {
	if client == nil {
		client = newHTTPClient()
	}
	return &API{token: token, client: client, pollInterval: 2 * time.Second}
}

func newHTTPClient() *http.Client {
	return &http.Client{
		Timeout: 15 * time.Minute,
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

func validateMaxWait(seconds int64) error {
	if seconds < 1 || seconds > maxMaxWait {
		return fmt.Errorf("--max-wait must be between 1 and %d seconds", maxMaxWait)
	}
	return nil
}

func parseMaxWait(value string) (int64, error) {
	if value == "" || strings.TrimSpace(value) != value {
		return 0, errors.New("--max-wait must be a whole number of seconds")
	}
	seconds, err := strconv.ParseInt(value, 10, 64)
	if err != nil {
		return 0, errors.New("--max-wait must be a whole number of seconds")
	}
	if err := validateMaxWait(seconds); err != nil {
		return 0, err
	}
	return seconds, nil
}

func validateVideoURL(raw string) error {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || u.Scheme != "https" || u.Host == "" || (u.Hostname() != "tiktok.com" && !strings.HasSuffix(strings.ToLower(u.Hostname()), ".tiktok.com")) {
		return errors.New("expected an HTTPS TikTok video URL in the form https://www.tiktok.com/@user/video/123")
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) != 3 || !strings.HasPrefix(parts[0], "@") || len(parts[0]) < 2 || parts[1] != "video" || parts[2] == "" {
		return errors.New("expected an HTTPS TikTok video URL in the form https://www.tiktok.com/@user/video/123")
	}
	for _, r := range parts[2] {
		if r < '0' || r > '9' {
			return errors.New("expected a numeric TikTok video ID in the video URL")
		}
	}
	return nil
}

type runEnvelope struct {
	Data json.RawMessage `json:"data"`
}

type Run struct {
	ID               string `json:"id"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
}

func (a *API) startRun(videoURL string) (Run, error) {
	if err := validateVideoURL(videoURL); err != nil {
		return Run{}, err
	}
	if strings.TrimSpace(a.token) == "" {
		return Run{}, errors.New("APIFY_TOKEN is required in the environment")
	}
	payload, _ := json.Marshal(struct {
		VideoURL string `json:"videoUrl"`
	}{strings.TrimSpace(videoURL)})
	response, err := a.send(context.Background(), http.MethodPost, "/v2/actors/"+actorAPIID+"/runs", payload)
	if err != nil {
		return Run{}, &APIError{Kind: "run_creation_unknown", Detail: "Run creation outcome is unknown; check Apify Console before retrying. One client send attempt is not a server-side exactly-once guarantee."}
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode < 200 || response.StatusCode >= 300 {
		return Run{}, &APIError{Kind: "run_creation_unknown", Status: response.StatusCode, Detail: "Run creation outcome is unknown; check Apify Console before retrying."}
	}
	var envelope runEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil || len(envelope.Data) == 0 || string(envelope.Data) == "null" {
		return Run{}, &APIError{Kind: "run_creation_unknown", Detail: "Apify returned an invalid Run response; check Apify Console before retrying."}
	}
	var run Run
	if err := json.Unmarshal(envelope.Data, &run); err != nil || strings.TrimSpace(run.ID) == "" {
		return Run{}, &APIError{Kind: "run_creation_unknown", Detail: "Apify returned a Run response without a valid Run ID; check Apify Console before retrying."}
	}
	return run, nil
}

func (a *API) getRun(ctx context.Context, requestedID string) (Run, error) {
	if requestedID == "" || strings.ContainsAny(requestedID, "/?#") {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "invalid Run ID"}
	}
	response, err := a.send(ctx, http.MethodGet, "/v2/actor-runs/"+url.PathEscape(requestedID), nil)
	if err != nil {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "could not read the existing Run"}
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode < 200 || response.StatusCode >= 300 {
		if response.StatusCode == http.StatusNotFound {
			return Run{}, &APIError{Kind: "run_lookup_error", Status: response.StatusCode, Detail: "Run was not found"}
		}
		return Run{}, &APIError{Kind: "run_lookup_error", Status: response.StatusCode, Detail: "Run status could not be read"}
	}
	var envelope runEnvelope
	if err := json.Unmarshal(body, &envelope); err != nil || len(envelope.Data) == 0 || string(envelope.Data) == "null" {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "invalid Run API response envelope"}
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(envelope.Data, &fields); err != nil || fields == nil {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "Run API response data must be an object"}
	}
	var run Run
	if err := json.Unmarshal(envelope.Data, &run); err != nil || strings.TrimSpace(run.ID) == "" || run.ID != requestedID {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "Run API response ID is missing or does not match the requested Run ID"}
	}
	statusRaw, ok := fields["status"]
	var status string
	if !ok || json.Unmarshal(statusRaw, &status) != nil || strings.TrimSpace(status) == "" {
		return Run{}, &APIError{Kind: "run_lookup_error", Detail: "Run API response status is missing or invalid"}
	}
	run.Status = status
	return run, nil
}

func isTerminal(status string) bool {
	switch status {
	case "SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED":
		return true
	default:
		return false
	}
}

func (a *API) waitForRun(runID string, maxWaitSeconds int64) (Run, error) {
	if err := validateMaxWait(maxWaitSeconds); err != nil {
		return Run{}, err
	}
	// Range validation happens before converting seconds to a time.Duration.
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(maxWaitSeconds)*time.Second)
	defer cancel()
	for {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return Run{}, &APIError{Kind: "wait_timeout", RunID: runID, Detail: "Run may still be running; use the same Run ID to wait again"}
		}
		run, err := a.getRun(ctx, runID)
		if err != nil {
			if errors.Is(ctx.Err(), context.DeadlineExceeded) {
				return Run{}, &APIError{Kind: "wait_timeout", RunID: runID, Detail: "Run may still be running; use the same Run ID to wait again"}
			}
			return Run{}, err
		}
		if isTerminal(run.Status) {
			return run, nil
		}
		timer := time.NewTimer(a.pollInterval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return Run{}, &APIError{Kind: "wait_timeout", RunID: runID, Detail: "Run may still be running; use the same Run ID to wait again"}
		case <-timer.C:
		}
	}
}

func (a *API) datasetItems(datasetID string) ([]json.RawMessage, error) {
	if datasetID == "" || strings.ContainsAny(datasetID, "/?#") {
		return nil, &APIError{Kind: "dataset_error", Detail: "invalid Dataset ID"}
	}
	response, err := a.send(context.Background(), http.MethodGet, "/v2/datasets/"+url.PathEscape(datasetID)+"/items", nil)
	if err != nil {
		return nil, &APIError{Kind: "dataset_error", Detail: "Dataset Items could not be read"}
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, &APIError{Kind: "dataset_error", Status: response.StatusCode, Detail: "Dataset Items could not be read"}
	}
	var items []json.RawMessage
	if err := json.Unmarshal(body, &items); err != nil || items == nil {
		return nil, &APIError{Kind: "dataset_error", Detail: "Dataset Items response must be a JSON array"}
	}
	return items, nil
}

func (a *API) send(ctx context.Context, method, path string, payload []byte) (*http.Response, error) {
	endpoint := apiHost + path
	var body io.Reader
	if payload != nil {
		body = bytes.NewReader(payload)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+a.token)
	req.Header.Set("Accept", "application/json")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return a.client.Do(req)
}

func transcriptFailure(run Run, items []json.RawMessage) string {
	if run.Status != "SUCCEEDED" {
		return "Actor Run failed with status " + run.Status
	}
	if run.DefaultDatasetID == "" {
		return "Run succeeded without a default Dataset ID"
	}
	if len(items) == 0 {
		return "Run succeeded but the Dataset is empty"
	}
	var hasText bool
	for _, raw := range items {
		var item struct {
			Text   *string         `json:"text"`
			ErrMsg json.RawMessage `json:"errMsg"`
		}
		if err := json.Unmarshal(raw, &item); err != nil {
			return "Dataset Item is not a valid transcript object"
		}
		if nonEmptyJSON(item.ErrMsg) {
			return "Transcript failed: Actor returned a non-empty errMsg"
		}
		if item.Text != nil && strings.TrimSpace(*item.Text) != "" {
			hasText = true
		}
	}
	if !hasText {
		return "Run completed but transcript text is empty or missing"
	}
	return ""
}

func nonEmptyJSON(raw json.RawMessage) bool {
	if len(raw) == 0 || string(raw) == "null" {
		return false
	}
	var value string
	if json.Unmarshal(raw, &value) == nil {
		return strings.TrimSpace(value) != ""
	}
	return true
}
