package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

const defaultConcurrency = 2

var terminalRecordStatuses = map[string]bool{
	"transcript_success": true, "completed_with_transcript": true, "transcript_empty": true, "transcript_failed": true,
	"actor_failed": true, "dataset_empty": true, "dataset_id_missing": true,
	"input_error": true, "duplicate_id": true,
}

var successfulRecordStatuses = map[string]bool{
	"transcript_success":        true,
	"completed_with_transcript": true,
}

type csvOptions struct {
	input       string
	journal     string
	concurrency int
	maxWait     int64
	reconcile   bool
}

type batchRow struct {
	Key      string
	RowNum   int
	ID       string
	VideoURL string
	InputErr string
}

type batchRecord struct {
	Key            string            `json:"key"`
	RowNum         int               `json:"row_number"`
	ID             string            `json:"id,omitempty"`
	VideoURL       string            `json:"videoUrl"`
	OriginalURL    string            `json:"original_url,omitempty"`
	CurrentURL     string            `json:"current_url,omitempty"`
	Status         string            `json:"status"`
	PreviousStatus string            `json:"previous_status,omitempty"`
	RunID          string            `json:"run_id,omitempty"`
	Error          string            `json:"error,omitempty"`
	Items          []json.RawMessage `json:"items,omitempty"`
}

type journal struct {
	mu   sync.Mutex
	file *os.File
}

func (j *journal) append(record batchRecord) error {
	j.mu.Lock()
	defer j.mu.Unlock()
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	if _, err := j.file.Write(append(data, '\n')); err != nil {
		return err
	}
	return j.file.Sync()
}

func parseCSVOptions(args []string) (csvOptions, error) {
	options := csvOptions{concurrency: defaultConcurrency, maxWait: defaultMaxWait}
	fs := flag.NewFlagSet("csv_batch", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&options.input, "csv", "", "input CSV containing videoUrl")
	fs.StringVar(&options.journal, "journal", "", "JSONL result journal")
	fs.IntVar(&options.concurrency, "concurrency", defaultConcurrency, "worker limit (1-16)")
	maxWait := fs.String("max-wait", fmt.Sprint(defaultMaxWait), "maximum Run wait in seconds (1-86400)")
	fs.BoolVar(&options.reconcile, "reconcile", false, "read-only list of records needing manual review")
	if err := fs.Parse(args); err != nil {
		return csvOptions{}, fmt.Errorf("invalid CSV arguments: %w", err)
	}
	if fs.NArg() != 0 || options.input == "" {
		return csvOptions{}, errors.New("usage: csv_batch --csv FILE [--journal FILE] [--concurrency 1-16] [--max-wait SECONDS] [--reconcile]")
	}
	if options.concurrency < 1 || options.concurrency > 16 {
		return csvOptions{}, errors.New("--concurrency must be between 1 and 16")
	}
	seconds, err := parseMaxWait(*maxWait)
	if err != nil {
		return csvOptions{}, err
	}
	options.maxWait = seconds
	return options, nil
}

func runCSV(args []string, api *API, out io.Writer, root string) error {
	options, err := parseCSVOptions(args)
	if err != nil {
		return err
	}
	if options.journal == "" {
		if root == "" {
			root, err = findRepoRoot()
			if err != nil {
				return err
			}
		}
		options.journal = filepath.Join(root, "sample-output", "generated", "go-csv-batch-results.jsonl")
	}
	if options.reconcile {
		return reconcileCSV(options.input, options.journal, out)
	}
	if api == nil {
		token := os.Getenv("APIFY_TOKEN")
		if strings.TrimSpace(token) == "" {
			return errors.New("APIFY_TOKEN is required in the environment")
		}
		api = NewAPI(token, nil)
	}
	return processCSV(options.input, options.journal, options.concurrency, options.maxWait, api, out)
}

func processCSV(inputPath, journalPath string, concurrency int, maxWaitSeconds int64, api *API, out io.Writer) error {
	if concurrency < 1 || concurrency > 16 {
		return errors.New("concurrency must be between 1 and 16")
	}
	if err := validateMaxWait(maxWaitSeconds); err != nil {
		return err
	}
	rows, err := readCSVRows(inputPath)
	if err != nil {
		return err
	}
	if len(rows) == 0 {
		return errors.New("CSV contains no video rows")
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		return err
	}
	active := make(map[string]bool, len(rows))
	for _, row := range rows {
		active[row.Key] = true
	}
	if err := os.MkdirAll(filepath.Dir(journalPath), 0o755); err != nil {
		return fmt.Errorf("could not create JSONL directory: %w", err)
	}
	file, err := os.OpenFile(journalPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return fmt.Errorf("could not open JSONL journal: %w", err)
	}
	store := &journal{file: file}
	defer file.Close()

	jobs := make(chan batchRow)
	var workers sync.WaitGroup
	var workerErrMu sync.Mutex
	var workerErr error
	for i := 0; i < concurrency; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for row := range jobs {
				if err := processCSVRow(row, latest[row.Key], store, api, maxWaitSeconds); err != nil {
					workerErrMu.Lock()
					if workerErr == nil {
						workerErr = err
					}
					workerErrMu.Unlock()
				}
			}
		}()
	}
	for _, row := range rows {
		jobs <- row
	}
	close(jobs)
	workers.Wait()
	if workerErr != nil {
		fmt.Fprintf(out, "Batch processing error: %v\n", workerErr)
	}
	latest, err = readJournal(journalPath)
	if err != nil {
		return err
	}
	counts := make(map[string]int)
	failed := workerErr != nil
	for key := range active {
		record, ok := latest[key]
		if !ok {
			counts["missing_record"]++
			failed = true
			continue
		}
		counts[record.Status]++
		if !successfulRecordStatuses[record.Status] {
			failed = true
		}
	}
	fmt.Fprintf(out, "Batch summary (current CSV rows only): %v\n", counts)
	if failed {
		return errors.New("CSV batch completed with failed or unresolved rows")
	}
	return nil
}

func processCSVRow(row batchRow, prior batchRecord, store *journal, api *API, maxWaitSeconds int64) error {
	appendRecord := func(record batchRecord) error { return store.append(record) }
	priorExists := prior.Key != ""
	if priorExists {
		prior.RunID = strings.TrimSpace(prior.RunID)
	}
	if priorExists && prior.Status == "needs_reconciliation" {
		if prior.CurrentURL != row.VideoURL {
			prior.CurrentURL = row.VideoURL
			prior.Error = appendDiagnostic(prior.Error, "This row remains under manual reconciliation; the input URL changed again.")
			return appendRecord(prior)
		}
		return nil
	}
	if priorExists && prior.VideoURL != row.VideoURL {
		if terminalRecordStatuses[prior.Status] {
			priorExists = false
			prior.RunID = ""
		} else {
			diagnostic := "Input URL changed while the previous Run was unresolved."
			if prior.RunID == "" && (prior.Status == "run_pending" || prior.Status == "dataset_error" || prior.Status == "processing_error") {
				diagnostic = "Input URL changed while the previous Run was unresolved, and the journal has no valid Run ID; check the Apify Console and reconcile manually."
			}
			record := batchRecord{
				Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: prior.VideoURL,
				OriginalURL: prior.VideoURL, CurrentURL: row.VideoURL, RunID: prior.RunID,
				Status: "needs_reconciliation", PreviousStatus: prior.Status, Error: appendDiagnostic(prior.Error, diagnostic),
			}
			return appendRecord(record)
		}
	}
	if priorExists && terminalRecordStatuses[prior.Status] {
		return nil
	}
	if priorExists && (prior.Status == "start_attempted" || prior.Status == "run_creation_unknown") {
		return nil
	}
	runID := ""
	if priorExists {
		runID = strings.TrimSpace(prior.RunID)
		if runID != "" && prior.Status == "needs_reconciliation" {
			return nil
		}
		if runID == "" && (prior.Status == "run_pending" || prior.Status == "dataset_error" || prior.Status == "processing_error") {
			prior.RunID = ""
			prior.OriginalURL = prior.VideoURL
			prior.CurrentURL = row.VideoURL
			prior.PreviousStatus = prior.Status
			prior.Status = "needs_reconciliation"
			prior.Error = appendDiagnostic(prior.Error, "Journal record has a resumable Run state but no valid Run ID; check the Apify Console and reconcile manually before continuing.")
			return appendRecord(prior)
		}
		if runID != "" && prior.Status != "run_pending" && prior.Status != "dataset_error" && prior.Status != "processing_error" {
			return nil
		}
	}
	if row.InputErr != "" {
		status := "input_error"
		if strings.HasPrefix(row.InputErr, "duplicate id") {
			status = "duplicate_id"
		}
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL, Status: status, Error: row.InputErr})
	}
	if err := validateVideoURL(row.VideoURL); err != nil {
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL, Status: "input_error", Error: err.Error()})
	}
	if runID == "" {
		intent := batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL, Status: "start_attempted", Error: "Creation intent persisted before POST."}
		if err := appendRecord(intent); err != nil {
			return err
		}
		run, err := api.startRun(row.VideoURL)
		if err != nil {
			status := "processing_error"
			if apiErrorKind(err) == "run_creation_unknown" {
				status = "run_creation_unknown"
			}
			intent.Status = status
			intent.Error = err.Error()
			if writeErr := appendRecord(intent); writeErr != nil {
				return writeErr
			}
			return nil
		}
		runID = run.ID
		if err := appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL, RunID: runID, Status: "run_pending"}); err != nil {
			return err
		}
	}

	run, err := api.waitForRun(runID, maxWaitSeconds)
	if err != nil {
		state := "processing_error"
		if apiErrorKind(err) == "wait_timeout" {
			state = "run_pending"
		}
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
			RunID: runID, Status: state, Error: err.Error()})
	}
	if run.Status != "SUCCEEDED" {
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
			RunID: runID, Status: "actor_failed", Error: "Actor Run finished with status " + run.Status})
	}
	if run.DefaultDatasetID == "" {
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
			RunID: runID, Status: "dataset_id_missing", Error: "Run succeeded without a default Dataset ID"})
	}
	items, err := api.datasetItems(run.DefaultDatasetID)
	if err != nil {
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
			RunID: runID, Status: "dataset_error", Error: err.Error()})
	}
	failure := transcriptFailure(run, items)
	if failure != "" {
		status := "transcript_empty"
		if strings.Contains(failure, "errMsg") {
			status = "transcript_failed"
		}
		if strings.Contains(failure, "Dataset is empty") {
			status = "dataset_empty"
		}
		return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
			RunID: runID, Status: status, Error: failure, Items: items})
	}
	return appendRecord(batchRecord{Key: row.Key, RowNum: row.RowNum, ID: row.ID, VideoURL: row.VideoURL,
		RunID: runID, Status: "transcript_success", Items: items})
}

func appendDiagnostic(previous, current string) string {
	previous = strings.TrimSpace(previous)
	if previous == "" {
		return current
	}
	return previous + "; " + current
}

func apiErrorKind(err error) string {
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		return apiErr.Kind
	}
	return ""
}

func readCSVRows(path string) ([]batchRow, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("could not open CSV: %w", err)
	}
	defer file.Close()
	reader := csv.NewReader(bufio.NewReader(file))
	reader.FieldsPerRecord = -1
	records, err := reader.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("invalid CSV: %w", err)
	}
	if len(records) == 0 {
		return nil, errors.New("CSV is empty")
	}
	header := records[0]
	if len(header) > 0 {
		header[0] = strings.TrimPrefix(header[0], "\uFEFF")
	}
	indices := make(map[string]int, len(header))
	for i, name := range header {
		if _, exists := indices[name]; exists {
			return nil, fmt.Errorf("CSV has duplicate column %q", name)
		}
		indices[name] = i
	}
	urlIndex, ok := indices["videoUrl"]
	if !ok {
		return nil, errors.New("CSV must contain a videoUrl column")
	}
	idIndex, hasID := indices["id"]
	values := make([][]string, 0, len(records)-1)
	for i, record := range records[1:] {
		if len(record) != len(header) {
			return nil, fmt.Errorf("CSV row %d has %d columns; expected %d", i+2, len(record), len(header))
		}
		values = append(values, record)
	}
	idCounts := make(map[string]int)
	if hasID {
		for _, record := range values {
			id := strings.TrimSpace(record[idIndex])
			if id != "" {
				idCounts[id]++
			}
		}
	}
	occurrences := make(map[string]int)
	rows := make([]batchRow, 0, len(values))
	dupOrdinal := make(map[string]int)
	for idx, record := range values {
		videoURL := strings.TrimSpace(record[urlIndex])
		id := ""
		if hasID {
			id = strings.TrimSpace(record[idIndex])
		}
		row := batchRow{RowNum: idx + 2, ID: id, VideoURL: videoURL}
		if hasID && id != "" {
			if idCounts[id] > 1 {
				dupOrdinal[id]++
				row.Key = fmt.Sprintf("duplicate-id:%s:%d", shortHash(id), dupOrdinal[id])
				row.InputErr = fmt.Sprintf("duplicate id %q appears more than once", id)
			} else {
				row.Key = "id:" + id
			}
		} else if hasID {
			row.Key = fmt.Sprintf("empty-id-row:%d", row.RowNum)
			row.InputErr = "id column is empty"
		} else {
			occurrences[videoURL]++
			row.Key = fmt.Sprintf("url:%s:%d", shortHash(videoURL), occurrences[videoURL])
		}
		if row.InputErr == "" && videoURL == "" {
			row.InputErr = "videoUrl is empty"
		}
		rows = append(rows, row)
	}
	return rows, nil
}

func readJournal(path string) (map[string]batchRecord, error) {
	latest := make(map[string]batchRecord)
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return latest, nil
	}
	if err != nil {
		return nil, fmt.Errorf("could not read JSONL journal: %w", err)
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 4096), 16*1024*1024)
	for line := 1; scanner.Scan(); line++ {
		if strings.TrimSpace(scanner.Text()) == "" {
			continue
		}
		var record batchRecord
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			return nil, fmt.Errorf("invalid JSONL record at line %d", line)
		}
		if record.Key == "" {
			return nil, fmt.Errorf("JSONL record at line %d has no key", line)
		}
		latest[record.Key] = record
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("could not read JSONL journal: %w", err)
	}
	return latest, nil
}

func reconcileCSV(inputPath, journalPath string, out io.Writer) error {
	rows, err := readCSVRows(inputPath)
	if err != nil {
		return err
	}
	latest, err := readJournal(journalPath)
	if err != nil {
		return err
	}
	found := false
	for _, row := range rows {
		prior, ok := latest[row.Key]
		if !ok {
			continue
		}
		unresolved := prior.Status == "needs_reconciliation" || prior.Status == "start_attempted" || prior.Status == "run_creation_unknown"
		if prior.VideoURL != row.VideoURL && !terminalRecordStatuses[prior.Status] {
			unresolved = true
		}
		if !unresolved {
			continue
		}
		found = true
		original := prior.OriginalURL
		if original == "" {
			original = prior.VideoURL
		}
		fmt.Fprintf(out, "key=%s row=%d status=%s previous_status=%s original_url=%s current_url=%s run_id=%s error=%s\n",
			row.Key, row.RowNum, prior.Status, prior.PreviousStatus, original, row.VideoURL, prior.RunID, prior.Error)
	}
	if !found {
		fmt.Fprintln(out, "No records need reconciliation.")
	}
	return nil
}

func shortHash(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:12])
}
