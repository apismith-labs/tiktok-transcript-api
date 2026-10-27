package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	args := os.Args[1:]
	var err error
	switch {
	case len(args) > 0 && (args[0] == "start" || args[0] == "wait"):
		err = runAsync(args, nil, os.Stdout)
	case len(args) > 0 && args[0] == "batch":
		err = runCSV(args[1:], nil, os.Stdout, "")
	default:
		err = runSingle(args, nil, os.Stdout, "")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func runSingle(args []string, api *API, out io.Writer, outputRoot string) error {
	fs := flag.NewFlagSet("single_url", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	videoURL := fs.String("video-url", defaultVideoURL, "TikTok video URL")
	maxWaitFlag := fs.String("max-wait", "900", "maximum Run wait in seconds (1-86400)")
	if err := fs.Parse(args); err != nil {
		return fmt.Errorf("invalid command line: %w", err)
	}
	remaining := fs.Args()
	videoURLSet := false
	fs.Visit(func(f *flag.Flag) {
		if f.Name == "video-url" {
			videoURLSet = true
		}
	})
	if len(remaining) > 1 || (len(remaining) == 1 && videoURLSet) {
		return errors.New("usage: single_url [--video-url URL | URL] [--max-wait SECONDS]")
	}
	if len(remaining) == 1 {
		*videoURL = remaining[0]
	}
	maxWait, err := parseMaxWait(*maxWaitFlag)
	if err != nil {
		return err
	}
	if err := validateVideoURL(*videoURL); err != nil {
		return err
	}
	outputPath, err := singleOutputPath(outputRoot)
	if err != nil {
		return fmt.Errorf("output preflight failed before Run creation: %w", err)
	}
	if api == nil {
		token := os.Getenv("APIFY_TOKEN")
		if strings.TrimSpace(token) == "" {
			return errors.New("APIFY_TOKEN is required in the environment")
		}
		api = NewAPI(token, nil)
	}
	fmt.Fprintln(out, "Actor:", actorDisplayName)
	fmt.Fprintln(out, "Starting Run and waiting for completion...")
	run, err := api.startRun(*videoURL)
	if err != nil {
		return err
	}
	fmt.Fprintln(out, "Run ID:", run.ID)
	if flusher, ok := out.(interface{ Flush() error }); ok {
		_ = flusher.Flush()
	}
	if file, ok := out.(*os.File); ok {
		_ = file.Sync()
	}
	finished, err := api.waitForRun(run.ID, maxWait)
	if err != nil {
		return err
	}
	if finished.Status != "SUCCEEDED" {
		return fmt.Errorf("Actor Run finished with status %s", finished.Status)
	}
	if finished.DefaultDatasetID == "" {
		return errors.New("Run succeeded without a default Dataset ID")
	}
	items, err := api.datasetItems(finished.DefaultDatasetID)
	if err != nil {
		return err
	}
	if err := writeJSON(outputPath, items); err != nil {
		return fmt.Errorf("could not save Dataset Items: %w", err)
	}
	fmt.Fprintln(out, "Output path:", outputPath)
	if failure := transcriptFailure(finished, items); failure != "" {
		return errors.New(failure)
	}
	fmt.Fprintln(out, "Dataset Items:", len(items))
	fmt.Fprintln(out, "Transcript:")
	for _, raw := range items {
		var item struct {
			Text string `json:"text"`
		}
		if err := json.Unmarshal(raw, &item); err != nil {
			return errors.New("Dataset Item is not a valid transcript object")
		}
		if strings.TrimSpace(item.Text) != "" {
			fmt.Fprintln(out, item.Text)
		}
	}
	return nil
}

// singleOutputPath resolves and verifies the destination before creating a Run.
// If this example is copied without the repository markers, it falls back to
// the current working directory's sample-output/generated folder.
func singleOutputPath(outputRoot string) (string, error) {
	base := outputRoot
	if base == "" {
		root, err := findRepoRoot()
		if err == nil {
			base = root
		} else {
			base, err = os.Getwd()
			if err != nil {
				return "", err
			}
		}
	}
	path := filepath.Join(base, "sample-output", "generated", "go-single-url-response.json")
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	if err := preflightOutputFile(absolute); err != nil {
		return "", err
	}
	return absolute, nil
}

func preflightOutputFile(path string) error {
	info, err := os.Stat(path)
	if err == nil {
		if info.IsDir() {
			return fmt.Errorf("output path is a directory: %s", path)
		}
		file, openErr := os.OpenFile(path, os.O_WRONLY, 0)
		if openErr != nil {
			return openErr
		}
		return file.Close()
	}
	if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	directory := filepath.Dir(path)
	if err := os.MkdirAll(directory, 0o755); err != nil {
		return err
	}
	testFile, err := os.CreateTemp(directory, ".go-single-output-preflight-*")
	if err != nil {
		return err
	}
	name := testFile.Name()
	if err := testFile.Close(); err != nil {
		_ = os.Remove(name)
		return err
	}
	return os.Remove(name)
}

func writeJSON(path string, value any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0o644)
}

func findRepoRoot() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		if fileExists(filepath.Join(current, "sample-data", "tiktok-video-urls.csv")) && fileExists(filepath.Join(current, "examples", "go", "go.mod")) {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}
	return "", errors.New("could not locate repository root")
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
