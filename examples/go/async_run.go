package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
)

func runAsync(args []string, api *API, out io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: async_run start [--video-url URL] | wait --run-id ID [--max-wait SECONDS]")
	}
	if api == nil {
		token := os.Getenv("APIFY_TOKEN")
		if strings.TrimSpace(token) == "" {
			return errors.New("APIFY_TOKEN is required in the environment")
		}
		api = NewAPI(token, nil)
	}
	switch args[0] {
	case "start":
		fs := flag.NewFlagSet("async_run start", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		videoURL := fs.String("video-url", defaultVideoURL, "TikTok video URL")
		if err := fs.Parse(args[1:]); err != nil {
			return fmt.Errorf("invalid start arguments: %w", err)
		}
		if fs.NArg() != 0 {
			return errors.New("usage: async_run start [--video-url URL]")
		}
		if err := validateVideoURL(*videoURL); err != nil {
			return err
		}
		fmt.Fprintln(out, "Actor:", actorDisplayName)
		run, err := api.startRun(*videoURL)
		if err != nil {
			return err
		}
		fmt.Fprintln(out, "Run ID:", run.ID)
		if file, ok := out.(*os.File); ok {
			_ = file.Sync()
		}
		fmt.Fprintf(out, "Run started. Later, use: async_run wait --run-id %s\n", run.ID)
		return nil
	case "wait":
		fs := flag.NewFlagSet("async_run wait", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		runID := fs.String("run-id", "", "existing Apify Run ID")
		maxWaitFlag := fs.String("max-wait", "900", "maximum Run wait in seconds (1-86400)")
		if err := fs.Parse(args[1:]); err != nil {
			return fmt.Errorf("invalid wait arguments: %w", err)
		}
		if fs.NArg() != 0 || strings.TrimSpace(*runID) == "" {
			return errors.New("usage: async_run wait --run-id ID [--max-wait SECONDS]")
		}
		maxWait, err := parseMaxWait(*maxWaitFlag)
		if err != nil {
			return err
		}
		run, err := api.waitForRun(*runID, maxWait)
		if err != nil {
			return err
		}
		if run.Status != "SUCCEEDED" {
			return fmt.Errorf("Actor Run finished with status %s", run.Status)
		}
		if run.DefaultDatasetID == "" {
			return errors.New("Run succeeded without a default Dataset ID")
		}
		items, err := api.datasetItems(run.DefaultDatasetID)
		if err != nil {
			return err
		}
		if failure := transcriptFailure(run, items); failure != "" {
			return errors.New(failure)
		}
		fmt.Fprintf(out, "Run %s completed with transcript in %d Dataset Item(s).\n", run.ID, len(items))
		return nil
	default:
		return errors.New("expected 'start' or 'wait'")
	}
}
