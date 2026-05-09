package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

const (
	defaultActorID  = "apple_yang/tiktok-transcripts-scraper"
	defaultVideoURL = "https://www.tiktok.com/@foxfamilyguy/video/7587841579029679392"
	apiBaseURL      = "https://api.apify.com/v2"
)

type apiResponse struct {
	Data runInfo `json:"data"`
}

type runInfo struct {
	ID               string `json:"id"`
	Status           string `json:"status"`
	DefaultDatasetID string `json:"defaultDatasetId"`
}

func main() {
	if err := runSingle(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func runSingle() error {
	repoRoot, err := findRepoRoot()
	if err != nil {
		return err
	}
	_ = godotenv.Load(filepath.Join(repoRoot, ".env"))

	token, err := requireEnv("APIFY_TOKEN")
	if err != nil {
		return err
	}
	actorID := envOrDefault("APIFY_ACTOR_ID", defaultActorID)
	videoURL := firstNonEmpty(argAt(1), os.Getenv("TIKTOK_VIDEO_URL"), defaultVideoURL)

	client := &http.Client{Timeout: 10 * time.Minute}
	fmt.Println("Actor ID:", actorID)
	fmt.Println("Running request...")

	run, err := startActorRun(client, token, actorID, videoURL)
	if err != nil {
		return err
	}
	if run.ID == "" {
		return errors.New("Error: Actor run response did not include an id.")
	}

	finishedRun, err := waitForRun(client, token, run.ID)
	if err != nil {
		return err
	}
	if finishedRun.Status != "SUCCEEDED" {
		return fmt.Errorf("Error: Actor run finished with status %s.", finishedRun.Status)
	}
	if finishedRun.DefaultDatasetID == "" {
		return errors.New("Error: Actor run completed without a defaultDatasetId.")
	}

	items, err := fetchDatasetItems(client, token, finishedRun.DefaultDatasetID)
	if err != nil {
		return err
	}
	if len(items) == 0 {
		return errors.New("Error: Actor returned an empty dataset.")
	}

	outputDir := filepath.Join(repoRoot, "sample-output", "generated")
	outputFile := filepath.Join(outputDir, "go-single-url-response.json")
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return err
	}
	output, err := json.MarshalIndent(items, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(outputFile, append(output, '\n'), 0o644); err != nil {
		return err
	}

	text := firstString(items, "text")
	fmt.Println("Output path:", outputFile)
	fmt.Println("Items:", len(items))
	fmt.Println("Title:", firstString(items, "title"))
	fmt.Println("Creator:", firstString(items, "nickname"))
	fmt.Println("Play count:", valueString(firstValue(items, "playCount")))
	fmt.Println("Transcript characters:", len([]rune(text)))
	if text != "" {
		fmt.Println("Transcript preview:")
		fmt.Println(truncateRunes(text, 500))
	}
	if errMsg := firstString(items, "errMsg"); errMsg != "" {
		fmt.Println("errMsg:", errMsg)
	}

	return nil
}

func startActorRun(client *http.Client, token string, actorID string, videoURL string) (runInfo, error) {
	actorIDForURL := strings.ReplaceAll(actorID, "/", "~")
	url := fmt.Sprintf("%s/acts/%s/runs", apiBaseURL, actorIDForURL)
	body, err := json.Marshal(map[string]string{"videoUrl": videoURL})
	if err != nil {
		return runInfo{}, err
	}

	var response apiResponse
	if err := sendJSON(client, token, http.MethodPost, url, body, &response); err != nil {
		return runInfo{}, err
	}
	return response.Data, nil
}

func waitForRun(client *http.Client, token string, runID string) (runInfo, error) {
	for attempt := 0; attempt < 150; attempt++ {
		url := fmt.Sprintf("%s/actor-runs/%s", apiBaseURL, runID)
		var response apiResponse
		if err := sendJSON(client, token, http.MethodGet, url, nil, &response); err != nil {
			return runInfo{}, err
		}
		if isFinished(response.Data.Status) {
			return response.Data, nil
		}
		time.Sleep(2 * time.Second)
	}
	return runInfo{}, errors.New("Error: Timed out waiting for Actor run to finish.")
}

func fetchDatasetItems(client *http.Client, token string, datasetID string) ([]map[string]any, error) {
	url := fmt.Sprintf("%s/datasets/%s/items", apiBaseURL, datasetID)
	var items []map[string]any
	err := sendJSON(client, token, http.MethodGet, url, nil, &items)
	return items, err
}

func sendJSON(client *http.Client, token string, method string, url string, body []byte, target any) error {
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	request, err := http.NewRequest(method, url, reader)
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("Apify API request failed: %w", err)
	}
	defer response.Body.Close()

	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		return err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("HTTP %d from Apify API: %s", response.StatusCode, string(responseBody))
	}
	if len(responseBody) == 0 {
		return nil
	}
	return json.Unmarshal(responseBody, target)
}

func isFinished(status string) bool {
	return status == "SUCCEEDED" || status == "FAILED" || status == "TIMED-OUT" || status == "ABORTED"
}

func firstValue(items []map[string]any, key string) any {
	for _, item := range items {
		value, ok := item[key]
		if ok && value != nil && value != "" {
			return value
		}
	}
	return nil
}

func firstString(items []map[string]any, key string) string {
	value, ok := firstValue(items, key).(string)
	if !ok {
		return ""
	}
	return value
}

func valueString(value any) string {
	if value == nil {
		return ""
	}
	return fmt.Sprint(value)
}

func truncateRunes(value string, limit int) string {
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit])
}

func requireEnv(name string) (string, error) {
	value := os.Getenv(name)
	if strings.TrimSpace(value) == "" {
		return "", fmt.Errorf("Error: %s is required. Set it in .env or your environment.", name)
	}
	return value, nil
}

func envOrDefault(name string, defaultValue string) string {
	value := os.Getenv(name)
	if strings.TrimSpace(value) == "" {
		return defaultValue
	}
	return value
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func argAt(index int) string {
	if len(os.Args) <= index {
		return ""
	}
	return os.Args[index]
}

func findRepoRoot() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if fileExists(filepath.Join(current, ".env.example")) && fileExists(filepath.Join(current, "sample-data", "tiktok-video-urls.csv")) {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}
	return "", errors.New("Error: Could not locate repository root.")
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
