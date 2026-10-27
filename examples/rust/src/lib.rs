use reqwest::redirect::Policy;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::fs::{self, File, OpenOptions};
use tokio::io::AsyncWriteExt;
use tokio::sync::{mpsc, Mutex};

pub const ACTOR_API_ID: &str = "apple_yang~tiktok-transcripts-scraper";
pub const ACTOR_DISPLAY_NAME: &str = "apple_yang/tiktok-transcripts-scraper";
pub const DEFAULT_VIDEO_URL: &str =
    "https://www.tiktok.com/@carter.braydon/video/7647694374876319007";
pub const DEFAULT_MAX_WAIT_SECONDS: u64 = 900;
pub const MAX_MAX_WAIT_SECONDS: u64 = 86_400;
pub const MAX_CONCURRENCY: usize = 16;
const API_ORIGIN: &str = "https://api.apify.com";
const POLL_INTERVAL: Duration = Duration::from_secs(2);
static OUTPUT_PROBE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

pub fn generated_output_path(filename: &str) -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let root = cwd
        .ancestors()
        .find(|candidate| {
            candidate.join(".gitignore").exists() && candidate.join("sample-data").exists()
        })
        .unwrap_or(cwd.as_path());
    root.join("sample-output/generated").join(filename)
}

pub fn preflight_output_directory(directory: &Path) -> ExampleResult<()> {
    std::fs::create_dir_all(directory).map_err(|error| {
        ExampleError::new(
            ErrorKind::Storage,
            format!(
                "Output directory preflight failed for {}: {error}",
                directory.display()
            ),
        )
    })?;
    for _ in 0..32 {
        let sequence = OUTPUT_PROBE_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let probe = directory.join(format!(
            ".tiktok-transcript-output-probe-{}-{sequence}",
            std::process::id()
        ));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&probe)
        {
            Ok(file) => {
                drop(file);
                if let Err(error) = std::fs::remove_file(&probe) {
                    let _ = std::fs::remove_file(&probe);
                    return Err(ExampleError::new(
                        ErrorKind::Storage,
                        format!(
                            "Output directory preflight could not remove its probe file: {error}"
                        ),
                    ));
                }
                return Ok(());
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(ExampleError::new(
                    ErrorKind::Storage,
                    format!(
                        "Output directory preflight failed for {}: {error}",
                        directory.display()
                    ),
                ));
            }
        }
    }
    Err(ExampleError::new(
        ErrorKind::Storage,
        "Output directory preflight could not reserve a unique probe file.",
    ))
}

pub type ExampleResult<T> = Result<T, ExampleError>;
pub type TransportFuture<'a> =
    Pin<Box<dyn Future<Output = Result<HttpResponse, TransportError>> + Send + 'a>>;

#[derive(Clone, PartialEq, Eq)]
pub struct HttpRequest {
    pub method: String,
    pub url: String,
    pub authorization: String,
    pub body: Option<Vec<u8>>,
}

#[derive(Clone, Debug)]
pub struct HttpResponse {
    pub status: u16,
    pub body: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct TransportError;

pub trait HttpTransport: Send + Sync {
    fn send<'a>(&'a self, request: HttpRequest) -> TransportFuture<'a>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ErrorKind {
    Input,
    RunCreationUnknown,
    RunLookup,
    WaitTimeout,
    Dataset,
    Storage,
    RunFailed,
    Transcript,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExampleError {
    pub kind: ErrorKind,
    pub run_id: Option<String>,
    message: String,
}

impl ExampleError {
    fn new(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            run_id: None,
            message: message.into(),
        }
    }

    fn for_run(kind: ErrorKind, run_id: &str, message: impl Into<String>) -> Self {
        Self {
            kind,
            run_id: Some(run_id.to_string()),
            message: message.into(),
        }
    }
}

impl Display for ExampleError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        if self.kind == ErrorKind::WaitTimeout {
            write!(
                f,
                "{}; use the same Run ID to wait again: {}",
                self.message,
                self.run_id.as_deref().unwrap_or("")
            )
        } else {
            f.write_str(&self.message)
        }
    }
}

impl Error for ExampleError {}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct Run {
    pub id: String,
    pub status: String,
    #[serde(rename = "defaultDatasetId", default)]
    pub default_dataset_id: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct JournalRecord {
    pub key: String,
    #[serde(default)]
    pub row_number: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(rename = "videoUrl")]
    pub video_url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub original_url: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub current_url: Option<String>,
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub run_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub items: Option<Vec<Value>>,
}

#[derive(Clone)]
pub struct ApiClient {
    token: Arc<str>,
    transport: Arc<dyn HttpTransport>,
    poll_interval: Duration,
}

impl ApiClient {
    pub fn new(
        token: impl Into<Arc<str>>,
        transport: Arc<dyn HttpTransport>,
    ) -> ExampleResult<Self> {
        let token = token.into();
        if token.trim().is_empty() {
            return Err(ExampleError::new(
                ErrorKind::Input,
                "APIFY_TOKEN is required in the environment.",
            ));
        }
        Ok(Self {
            token,
            transport,
            poll_interval: POLL_INTERVAL,
        })
    }

    pub fn production(token: impl Into<Arc<str>>) -> ExampleResult<Self> {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(900))
            .redirect(Policy::none())
            .build()
            .map_err(|_| {
                ExampleError::new(ErrorKind::Input, "Could not construct the HTTP client.")
            })?;
        Self::new(token, Arc::new(ReqwestTransport { client }))
    }

    #[cfg(test)]
    fn with_poll_interval(mut self, interval: Duration) -> Self {
        self.poll_interval = interval;
        self
    }

    pub async fn start_run(&self, video_url: &str) -> ExampleResult<Run> {
        validate_video_url(video_url)?;
        let body = serde_json::to_vec(&json!({ "videoUrl": video_url.trim() }))
            .map_err(|_| ExampleError::new(ErrorKind::Input, "Could not encode Actor input."))?;
        let request = self.request(
            "POST",
            format!("{API_ORIGIN}/v2/actors/{ACTOR_API_ID}/runs"),
            Some(body),
        );
        let response = self.transport.send(request).await.map_err(|_| {
            ExampleError::new(
                ErrorKind::RunCreationUnknown,
                "Run creation outcome is unknown. Check Apify Console before retrying. One client send attempt does not guarantee server-side exactly-once execution.",
            )
        })?;
        if !(200..300).contains(&response.status) {
            return Err(ExampleError::new(
                ErrorKind::RunCreationUnknown,
                format!("Run creation outcome is unknown (HTTP {}). Check Apify Console before retrying. One client send attempt does not guarantee server-side exactly-once execution.", response.status),
            ));
        }
        let data = parse_data_envelope(&response.body).map_err(|_| {
            ExampleError::new(
                ErrorKind::RunCreationUnknown,
                "Apify returned an invalid Run response. Check Apify Console before retrying; do not create another Run.",
            )
        })?;
        let run_id = data
            .get("id")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .ok_or_else(|| {
                ExampleError::new(
                    ErrorKind::RunCreationUnknown,
                    "Apify response did not contain a valid Run ID. Check Apify Console before retrying; do not create another Run.",
                )
            })?;
        validate_resource_id(run_id, "Run").map_err(|_| {
            ExampleError::new(
                ErrorKind::RunCreationUnknown,
                "Apify response contained an invalid Run ID. Check Apify Console before retrying; do not create another Run.",
            )
        })?;
        Ok(Run {
            id: run_id.to_string(),
            status: data
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string(),
            default_dataset_id: data
                .get("defaultDatasetId")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        })
    }

    pub async fn get_run(&self, run_id: &str) -> ExampleResult<Run> {
        validate_resource_id(run_id, "Run")?;
        let request = self.request("GET", format!("{API_ORIGIN}/v2/actor-runs/{run_id}"), None);
        let response = self.transport.send(request).await.map_err(|_| {
            ExampleError::for_run(
                ErrorKind::RunLookup,
                run_id,
                "Could not read the existing Run.",
            )
        })?;
        if !(200..300).contains(&response.status) {
            let detail = if response.status == 404 {
                "Run was not found."
            } else {
                "Run status could not be read."
            };
            return Err(ExampleError::for_run(
                ErrorKind::RunLookup,
                run_id,
                format!("{detail} HTTP {}.", response.status),
            ));
        }
        let data = parse_data_envelope(&response.body).map_err(|_| {
            ExampleError::for_run(
                ErrorKind::RunLookup,
                run_id,
                "Invalid Run API response envelope.",
            )
        })?;
        let id = data.get("id").and_then(Value::as_str).unwrap_or("");
        if id != run_id {
            return Err(ExampleError::for_run(
                ErrorKind::RunLookup,
                run_id,
                "Run API response ID is missing or does not match the requested Run ID.",
            ));
        }
        let status = data.get("status").and_then(Value::as_str).unwrap_or("");
        if status.trim().is_empty() {
            return Err(ExampleError::for_run(
                ErrorKind::RunLookup,
                run_id,
                "Run API response status is missing or invalid.",
            ));
        }
        Ok(Run {
            id: id.to_string(),
            status: status.to_string(),
            default_dataset_id: data
                .get("defaultDatasetId")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        })
    }

    pub async fn wait_for_run(&self, run_id: &str, max_wait_seconds: u64) -> ExampleResult<Run> {
        validate_max_wait_seconds(max_wait_seconds)?;
        let limit = Duration::from_secs(max_wait_seconds);
        let deadline = tokio::time::Instant::now() + limit;
        loop {
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                return Err(wait_timeout(run_id));
            }
            let run = match tokio::time::timeout(remaining, self.get_run(run_id)).await {
                Ok(Ok(run)) if tokio::time::Instant::now() < deadline => run,
                Ok(Err(error)) if tokio::time::Instant::now() < deadline => return Err(error),
                Ok(_) | Err(_) => return Err(wait_timeout(run_id)),
            };
            if is_terminal_status(&run.status) {
                return Ok(run);
            }
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            if remaining.is_zero() {
                return Err(wait_timeout(run_id));
            }
            tokio::time::sleep(self.poll_interval.min(remaining)).await;
        }
    }

    pub async fn dataset_items(&self, dataset_id: &str) -> ExampleResult<Vec<Value>> {
        validate_resource_id(dataset_id, "Dataset")?;
        let request = self.request(
            "GET",
            format!("{API_ORIGIN}/v2/datasets/{dataset_id}/items"),
            None,
        );
        let response = self.transport.send(request).await.map_err(|_| {
            ExampleError::new(ErrorKind::Dataset, "Dataset Items could not be read.")
        })?;
        if !(200..300).contains(&response.status) {
            return Err(ExampleError::new(
                ErrorKind::Dataset,
                format!(
                    "Dataset Items could not be read (HTTP {}).",
                    response.status
                ),
            ));
        }
        serde_json::from_slice(&response.body).map_err(|_| {
            ExampleError::new(
                ErrorKind::Dataset,
                "Dataset Items response must be a JSON array.",
            )
        })
    }

    fn request(&self, method: &str, url: String, body: Option<Vec<u8>>) -> HttpRequest {
        HttpRequest {
            method: method.to_string(),
            url,
            authorization: format!("Bearer {}", self.token),
            body,
        }
    }
}

struct ReqwestTransport {
    client: reqwest::Client,
}

impl HttpTransport for ReqwestTransport {
    fn send<'a>(&'a self, request: HttpRequest) -> TransportFuture<'a> {
        Box::pin(async move {
            let method = reqwest::Method::from_bytes(request.method.as_bytes())
                .map_err(|_| TransportError)?;
            let mut builder = self
                .client
                .request(method, request.url)
                .header(reqwest::header::AUTHORIZATION, request.authorization)
                .header(reqwest::header::ACCEPT, "application/json");
            if let Some(body) = request.body {
                builder = builder
                    .header(reqwest::header::CONTENT_TYPE, "application/json")
                    .body(body);
            }
            let response = builder.send().await.map_err(|_| TransportError)?;
            let status = response.status().as_u16();
            let body = response.bytes().await.map_err(|_| TransportError)?.to_vec();
            Ok(HttpResponse { status, body })
        })
    }
}

fn parse_data_envelope(body: &[u8]) -> Result<Value, ()> {
    let root: Value = serde_json::from_slice(body).map_err(|_| ())?;
    let data = root
        .get("data")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or(())?;
    Ok(data)
}

pub fn validate_max_wait_seconds(seconds: u64) -> ExampleResult<()> {
    if !(1..=MAX_MAX_WAIT_SECONDS).contains(&seconds) {
        return Err(ExampleError::new(
            ErrorKind::Input,
            format!("--max-wait must be between 1 and {MAX_MAX_WAIT_SECONDS} seconds."),
        ));
    }
    Ok(())
}

pub fn parse_max_wait_seconds(value: &str) -> ExampleResult<u64> {
    let seconds = value.parse::<u64>().map_err(|_| {
        ExampleError::new(
            ErrorKind::Input,
            "--max-wait must be a whole number of seconds.",
        )
    })?;
    validate_max_wait_seconds(seconds)?;
    Ok(seconds)
}

fn wait_timeout(run_id: &str) -> ExampleError {
    ExampleError::for_run(ErrorKind::WaitTimeout, run_id, "Run may still be running")
}

pub fn is_terminal_status(status: &str) -> bool {
    matches!(status, "SUCCEEDED" | "FAILED" | "TIMED-OUT" | "ABORTED")
}

pub fn validate_video_url(raw: &str) -> ExampleResult<()> {
    let trimmed = raw.trim();
    let Some((scheme, remainder)) = trimmed.split_once("://") else {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "Expected an HTTPS TikTok video URL.",
        ));
    };
    if scheme != "https" {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "Expected an HTTPS TikTok video URL.",
        ));
    }
    let authority_and_path = remainder.split(['?', '#']).next().unwrap_or("");
    let Some((host, path)) = authority_and_path.split_once('/') else {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "Expected a TikTok /@user/video/ID URL.",
        ));
    };
    let host = host
        .split('@')
        .next_back()
        .unwrap_or(host)
        .split(':')
        .next()
        .unwrap_or("");
    if !(host.eq_ignore_ascii_case("tiktok.com")
        || host.to_ascii_lowercase().ends_with(".tiktok.com"))
    {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "Expected a TikTok video URL.",
        ));
    }
    let pieces: Vec<&str> = path.trim_end_matches('/').split('/').collect();
    if pieces.len() != 3
        || !pieces[0].starts_with('@')
        || pieces[0].len() < 2
        || pieces[1] != "video"
        || pieces[2].is_empty()
        || !pieces[2].bytes().all(|b| b.is_ascii_digit())
    {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "Expected a TikTok /@user/video/ID URL.",
        ));
    }
    Ok(())
}

fn validate_resource_id(id: &str, kind: &str) -> ExampleResult<()> {
    if id.is_empty()
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
    {
        return Err(ExampleError::new(
            ErrorKind::Input,
            format!("Invalid {kind} ID."),
        ));
    }
    Ok(())
}

pub fn validate_resource_run_id(id: &str) -> ExampleResult<()> {
    validate_resource_id(id, "Run")
}

pub fn transcript_failure(run: &Run, items: &[Value]) -> Option<(String, String)> {
    if run.status != "SUCCEEDED" {
        return Some((
            "actor_failed".to_string(),
            format!("Actor Run finished with status {}.", run.status),
        ));
    }
    if run.default_dataset_id.as_deref().unwrap_or("").is_empty() {
        return Some((
            "dataset_id_missing".to_string(),
            "Run succeeded without a default Dataset ID.".to_string(),
        ));
    }
    if items.is_empty() {
        return Some((
            "dataset_empty".to_string(),
            "Run succeeded but Dataset is empty.".to_string(),
        ));
    }
    let mut has_text = false;
    for item in items {
        if let Some(err_msg) = item.get("errMsg") {
            let non_empty = match err_msg {
                Value::Null => false,
                Value::String(value) => !value.trim().is_empty(),
                _ => true,
            };
            if non_empty {
                return Some((
                    "transcript_failed".to_string(),
                    "Transcript failed: Actor returned a non-empty errMsg.".to_string(),
                ));
            }
        }
        if item
            .get("text")
            .and_then(Value::as_str)
            .is_some_and(|text| !text.trim().is_empty())
        {
            has_text = true;
        }
    }
    if !has_text {
        return Some((
            "transcript_empty".to_string(),
            "Run completed but transcript text is empty or missing.".to_string(),
        ));
    }
    None
}

#[derive(Clone, Debug)]
struct CsvRow {
    key: String,
    row_number: usize,
    id: Option<String>,
    video_url: String,
    input_error: Option<String>,
}

#[derive(Clone)]
struct Journal {
    file: Arc<Mutex<File>>,
}

impl Journal {
    async fn append(&self, record: &JournalRecord) -> ExampleResult<()> {
        let mut line = serde_json::to_vec(record).map_err(|_| {
            ExampleError::new(ErrorKind::Storage, "Could not encode JSONL journal record.")
        })?;
        line.push(b'\n');
        let mut file = self.file.lock().await;
        file.write_all(&line).await.map_err(|_| {
            ExampleError::new(ErrorKind::Storage, "Could not append JSONL journal record.")
        })?;
        file.sync_all().await.map_err(|_| {
            ExampleError::new(
                ErrorKind::Storage,
                "Could not flush JSONL journal record to disk.",
            )
        })
    }
}

pub async fn process_csv(
    csv_path: &Path,
    journal_path: &Path,
    concurrency: usize,
    max_wait_seconds: u64,
    api: ApiClient,
) -> ExampleResult<HashMap<String, usize>> {
    validate_concurrency(concurrency)?;
    validate_max_wait_seconds(max_wait_seconds)?;
    let rows = read_csv_rows(csv_path)?;
    if rows.is_empty() {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "CSV contains no video rows.",
        ));
    }
    let latest = Arc::new(read_journal(journal_path)?);
    if let Some(parent) = journal_path.parent() {
        fs::create_dir_all(parent).await.map_err(|_| {
            ExampleError::new(
                ErrorKind::Storage,
                "Could not create JSONL output directory.",
            )
        })?;
    }
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(journal_path)
        .await
        .map_err(|_| ExampleError::new(ErrorKind::Storage, "Could not open JSONL journal."))?;
    let journal = Journal {
        file: Arc::new(Mutex::new(file)),
    };
    let active_keys: HashSet<String> = rows.iter().map(|row| row.key.clone()).collect();
    let (sender, receiver) = mpsc::channel::<CsvRow>(concurrency);
    let receiver = Arc::new(Mutex::new(receiver));
    let mut workers = Vec::with_capacity(concurrency);
    for _ in 0..concurrency {
        let receiver = Arc::clone(&receiver);
        let journal = journal.clone();
        let api = api.clone();
        let latest = Arc::clone(&latest);
        workers.push(tokio::spawn(async move {
            loop {
                let row = {
                    let mut receiver = receiver.lock().await;
                    receiver.recv().await
                };
                let Some(row) = row else { break };
                let prior = latest.get(&row.key).cloned();
                process_csv_row(row, prior, &journal, &api, max_wait_seconds).await?;
            }
            Ok::<(), ExampleError>(())
        }));
    }
    for row in rows {
        sender.send(row).await.map_err(|_| {
            ExampleError::new(ErrorKind::Storage, "CSV worker stopped unexpectedly.")
        })?;
    }
    drop(sender);
    for worker in workers {
        worker
            .await
            .map_err(|_| ExampleError::new(ErrorKind::Storage, "CSV worker task failed."))??;
    }
    let latest = read_journal(journal_path)?;
    let mut summary = HashMap::new();
    let mut failed = false;
    for key in active_keys {
        let Some(record) = latest.get(&key) else {
            *summary.entry("missing_record".to_string()).or_insert(0) += 1;
            failed = true;
            continue;
        };
        *summary.entry(record.status.clone()).or_insert(0) += 1;
        if !is_success_record_status(&record.status) {
            failed = true;
        }
    }
    if failed {
        return Err(ExampleError::new(
            ErrorKind::Transcript,
            format!("CSV batch has failed or unresolved rows: {summary:?}"),
        ));
    }
    Ok(summary)
}

async fn process_csv_row(
    row: CsvRow,
    mut prior: Option<JournalRecord>,
    journal: &Journal,
    api: &ApiClient,
    max_wait_seconds: u64,
) -> ExampleResult<()> {
    if let Some(old) = prior.as_mut() {
        old.run_id = old
            .run_id
            .take()
            .map(|id| id.trim().to_string())
            .filter(|id| !id.is_empty());
    }
    if let Some(old) = prior
        .as_ref()
        .filter(|record| record.status == "needs_reconciliation")
    {
        if old.current_url.as_deref().unwrap_or("") != row.video_url {
            let mut held = old.clone();
            held.current_url = Some(row.video_url.clone());
            held.error = Some(
                "This row remains under manual reconciliation; the input URL changed again."
                    .to_string(),
            );
            return journal.append(&held).await;
        }
        return Ok(());
    }
    if let Some(old) = prior
        .as_ref()
        .filter(|record| record.video_url != row.video_url)
    {
        if is_terminal_record_status(&old.status) {
            prior = None;
        } else {
            let mut message =
                "Input URL changed while the previous Run was unresolved.".to_string();
            if old.run_id.is_none() && is_resumable_status(&old.status) {
                message = "Input URL changed while the previous Run was unresolved, and the journal has no valid Run ID; check the Apify Console and reconcile manually.".to_string();
            }
            let mut held = record_for(
                &row,
                "needs_reconciliation",
                old.run_id.clone(),
                Some(message),
                None,
            );
            held.video_url = old.video_url.clone();
            held.original_url = Some(old.video_url.clone());
            held.current_url = Some(row.video_url.clone());
            return journal.append(&held).await;
        }
    }
    if let Some(input_error) = row.input_error.as_deref() {
        let status = if input_error.starts_with("duplicate id") {
            "duplicate_id"
        } else {
            "input_error"
        };
        return journal
            .append(&record_for(
                &row,
                status,
                None,
                Some(input_error.to_string()),
                None,
            ))
            .await;
    }
    if let Some(old) = prior.as_ref() {
        if is_terminal_record_status(&old.status) {
            return Ok(());
        }
        if old.status == "start_attempted" || old.status == "run_creation_unknown" {
            return Ok(());
        }
        if is_resumable_status(&old.status) && old.run_id.is_none() {
            let mut held = old.clone();
            held.status = "needs_reconciliation".to_string();
            held.original_url = Some(old.video_url.clone());
            held.current_url = Some(row.video_url.clone());
            held.run_id = None;
            held.error = Some("Journal record has a resumable Run state but no valid Run ID; check the Apify Console and reconcile manually before continuing.".to_string());
            return journal.append(&held).await;
        }
    }
    if let Some(old) = prior.as_ref() {
        if is_resumable_status(&old.status) {
            let run_id = old.run_id.as_deref().unwrap_or_default();
            return resume_row(row, run_id, journal, api, max_wait_seconds).await;
        }
    }
    if let Err(error) = validate_video_url(&row.video_url) {
        return journal
            .append(&record_for(
                &row,
                "input_error",
                None,
                Some(error.to_string()),
                None,
            ))
            .await;
    }
    let intent = record_for(
        &row,
        "start_attempted",
        None,
        Some("Creation intent flushed before POST.".to_string()),
        None,
    );
    journal.append(&intent).await?;
    let run = match api.start_run(&row.video_url).await {
        Ok(run) => run,
        Err(error) => {
            let status = if error.kind == ErrorKind::RunCreationUnknown {
                "run_creation_unknown"
            } else {
                "processing_error"
            };
            let failed = record_for(&row, status, None, Some(error.to_string()), None);
            return journal.append(&failed).await;
        }
    };
    journal
        .append(&record_for(
            &row,
            "run_pending",
            Some(run.id.clone()),
            None,
            None,
        ))
        .await?;
    resolve_row(row, run.id, journal, api, max_wait_seconds).await
}

async fn resume_row(
    row: CsvRow,
    run_id: &str,
    journal: &Journal,
    api: &ApiClient,
    max_wait_seconds: u64,
) -> ExampleResult<()> {
    resolve_row(row, run_id.to_string(), journal, api, max_wait_seconds).await
}

async fn resolve_row(
    row: CsvRow,
    run_id: String,
    journal: &Journal,
    api: &ApiClient,
    max_wait_seconds: u64,
) -> ExampleResult<()> {
    let run = match api.wait_for_run(&run_id, max_wait_seconds).await {
        Ok(run) => run,
        Err(error) => {
            let status = if error.kind == ErrorKind::WaitTimeout {
                "run_pending"
            } else {
                "processing_error"
            };
            return journal
                .append(&record_for(
                    &row,
                    status,
                    Some(run_id),
                    Some(error.to_string()),
                    None,
                ))
                .await;
        }
    };
    if run.status != "SUCCEEDED" {
        return journal
            .append(&record_for(
                &row,
                "actor_failed",
                Some(run_id),
                Some(format!("Actor Run finished with status {}.", run.status)),
                None,
            ))
            .await;
    }
    let Some(dataset_id) = run
        .default_dataset_id
        .as_deref()
        .filter(|id| !id.is_empty())
    else {
        return journal
            .append(&record_for(
                &row,
                "dataset_id_missing",
                Some(run_id),
                Some("Run succeeded without a default Dataset ID.".to_string()),
                None,
            ))
            .await;
    };
    let items = match api.dataset_items(dataset_id).await {
        Ok(items) => items,
        Err(error) => {
            return journal
                .append(&record_for(
                    &row,
                    "dataset_error",
                    Some(run_id),
                    Some(error.to_string()),
                    None,
                ))
                .await
        }
    };
    if let Some((status, message)) = transcript_failure(&run, &items) {
        return journal
            .append(&record_for(
                &row,
                &status,
                Some(run_id),
                Some(message),
                Some(items),
            ))
            .await;
    }
    journal
        .append(&record_for(
            &row,
            "transcript_success",
            Some(run_id),
            None,
            Some(items),
        ))
        .await
}

fn record_for(
    row: &CsvRow,
    status: &str,
    run_id: Option<String>,
    error: Option<String>,
    items: Option<Vec<Value>>,
) -> JournalRecord {
    JournalRecord {
        key: row.key.clone(),
        row_number: row.row_number,
        id: row.id.clone(),
        video_url: row.video_url.clone(),
        original_url: None,
        current_url: None,
        status: status.to_string(),
        run_id,
        error,
        items,
    }
}

fn is_terminal_record_status(status: &str) -> bool {
    matches!(
        status,
        "transcript_success"
            | "completed_with_transcript"
            | "transcript_empty"
            | "transcript_failed"
            | "actor_failed"
            | "dataset_empty"
            | "dataset_id_missing"
            | "input_error"
            | "duplicate_id"
    )
}

fn is_success_record_status(status: &str) -> bool {
    matches!(status, "transcript_success" | "completed_with_transcript")
}

fn is_resumable_status(status: &str) -> bool {
    matches!(status, "run_pending" | "dataset_error" | "processing_error")
}

pub fn validate_concurrency(concurrency: usize) -> ExampleResult<()> {
    if !(1..=MAX_CONCURRENCY).contains(&concurrency) {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "--concurrency must be between 1 and 16.",
        ));
    }
    Ok(())
}

fn read_csv_rows(path: &Path) -> ExampleResult<Vec<CsvRow>> {
    let content = std::fs::read(path)
        .map_err(|_| ExampleError::new(ErrorKind::Input, "Could not read input CSV."))?;
    let content = content
        .strip_prefix(&[0xef, 0xbb, 0xbf])
        .unwrap_or(&content);
    let text = std::str::from_utf8(content)
        .map_err(|_| ExampleError::new(ErrorKind::Input, "CSV must be UTF-8."))?;
    let records = parse_csv(text)?;
    let Some(header) = records.first() else {
        return Err(ExampleError::new(ErrorKind::Input, "CSV is empty."));
    };
    let mut columns = HashMap::new();
    for (index, column) in header.iter().enumerate() {
        if columns.insert(column.clone(), index).is_some() {
            return Err(ExampleError::new(
                ErrorKind::Input,
                format!("CSV has duplicate column {column:?}."),
            ));
        }
    }
    let url_index = *columns.get("videoUrl").ok_or_else(|| {
        ExampleError::new(ErrorKind::Input, "CSV must contain a videoUrl column.")
    })?;
    let id_index = columns.get("id").copied();
    let data_rows = &records[1..];
    for (index, row) in data_rows.iter().enumerate() {
        if row.len() != header.len() {
            return Err(ExampleError::new(
                ErrorKind::Input,
                format!("CSV row {} has an invalid number of columns.", index + 2),
            ));
        }
    }
    let mut id_counts = HashMap::<String, usize>::new();
    if let Some(id_index) = id_index {
        for row in data_rows {
            let id = row[id_index].trim();
            if !id.is_empty() {
                *id_counts.entry(id.to_string()).or_default() += 1;
            }
        }
    }
    let mut url_occurrences = HashMap::<String, usize>::new();
    let mut id_occurrences = HashMap::<String, usize>::new();
    let mut rows = Vec::with_capacity(data_rows.len());
    for (index, fields) in data_rows.iter().enumerate() {
        let row_number = index + 2;
        let video_url = fields[url_index].trim().to_string();
        let id = id_index.map(|position| fields[position].trim().to_string());
        let (key, input_error) = match id.as_deref() {
            Some("") => (
                format!("empty-id-row:{row_number}"),
                Some("id column is empty".to_string()),
            ),
            Some(id) if id_counts.get(id).copied().unwrap_or(0) > 1 => {
                let ordinal = id_occurrences.entry(id.to_string()).or_default();
                *ordinal += 1;
                (
                    format!("duplicate-id:{}:{ordinal}", stable_hash(id)),
                    Some(format!("duplicate id {id:?} appears more than once")),
                )
            }
            Some(id) => (format!("id:{id}"), None),
            None => {
                // Without an id column, URL changes or duplicate URL reordering change the stable key.
                let ordinal = url_occurrences.entry(video_url.clone()).or_default();
                *ordinal += 1;
                (format!("url:{}:{ordinal}", stable_hash(&video_url)), None)
            }
        };
        let input_error = input_error.or_else(|| {
            video_url
                .is_empty()
                .then(|| "videoUrl is empty".to_string())
        });
        rows.push(CsvRow {
            key,
            row_number,
            id,
            video_url,
            input_error,
        });
    }
    Ok(rows)
}

fn parse_csv(input: &str) -> ExampleResult<Vec<Vec<String>>> {
    let bytes = input.as_bytes();
    let mut records = Vec::new();
    let mut row = Vec::new();
    let mut cell = Vec::new();
    let mut quoted = false;
    let mut closed_quote = false;
    let mut index = 0;
    while index < bytes.len() {
        let byte = bytes[index];
        if quoted {
            if byte == b'"' {
                if bytes.get(index + 1) == Some(&b'"') {
                    cell.push(b'"');
                    index += 1;
                } else {
                    quoted = false;
                    closed_quote = true;
                }
            } else if byte == b'\r' {
                cell.push(b'\n');
                if bytes.get(index + 1) == Some(&b'\n') {
                    index += 1;
                }
            } else {
                cell.push(byte);
            }
        } else {
            match byte {
                b'"' if cell.is_empty() && !closed_quote => quoted = true,
                b'"' => {
                    return Err(ExampleError::new(
                        ErrorKind::Input,
                        "Malformed quoted CSV field.",
                    ))
                }
                b',' => {
                    row.push(
                        String::from_utf8(std::mem::take(&mut cell)).map_err(|_| {
                            ExampleError::new(ErrorKind::Input, "CSV must be UTF-8.")
                        })?,
                    );
                    closed_quote = false;
                }
                b'\n' | b'\r' => {
                    if byte == b'\r' && bytes.get(index + 1) == Some(&b'\n') {
                        index += 1;
                    }
                    row.push(
                        String::from_utf8(std::mem::take(&mut cell)).map_err(|_| {
                            ExampleError::new(ErrorKind::Input, "CSV must be UTF-8.")
                        })?,
                    );
                    if !(row.len() == 1 && row[0].is_empty()) {
                        records.push(std::mem::take(&mut row));
                    }
                    closed_quote = false;
                }
                _ => {
                    if closed_quote && !byte.is_ascii_whitespace() {
                        return Err(ExampleError::new(
                            ErrorKind::Input,
                            "Unexpected characters after a quoted CSV field.",
                        ));
                    }
                    if !closed_quote {
                        cell.push(byte);
                    }
                }
            }
        }
        index += 1;
    }
    if quoted {
        return Err(ExampleError::new(
            ErrorKind::Input,
            "CSV has an unterminated quoted field.",
        ));
    }
    if !cell.is_empty() || !row.is_empty() {
        row.push(
            String::from_utf8(cell)
                .map_err(|_| ExampleError::new(ErrorKind::Input, "CSV must be UTF-8."))?,
        );
        records.push(row);
    }
    Ok(records)
}

fn stable_hash(value: &str) -> String {
    let mut hash = 0xcbf29ce484222325_u64;
    for byte in value.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")
}

fn read_journal(path: &Path) -> ExampleResult<HashMap<String, JournalRecord>> {
    let mut latest = HashMap::new();
    let content = match std::fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(latest),
        Err(_) => {
            return Err(ExampleError::new(
                ErrorKind::Storage,
                "Could not read JSONL journal.",
            ))
        }
    };
    for (index, line) in content.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let record: JournalRecord = serde_json::from_str(line).map_err(|_| {
            ExampleError::new(
                ErrorKind::Storage,
                format!("Invalid JSONL journal record at line {}.", index + 1),
            )
        })?;
        if record.key.is_empty() {
            return Err(ExampleError::new(
                ErrorKind::Storage,
                format!("JSONL journal record at line {} has no key.", index + 1),
            ));
        }
        latest.insert(record.key.clone(), record);
    }
    Ok(latest)
}

pub fn reconcile_csv(csv_path: &Path, journal_path: &Path) -> ExampleResult<Vec<JournalRecord>> {
    let rows = read_csv_rows(csv_path)?;
    let latest = read_journal(journal_path)?;
    let mut results = Vec::new();
    for row in rows {
        let Some(prior) = latest.get(&row.key) else {
            continue;
        };
        let unresolved = matches!(
            prior.status.as_str(),
            "needs_reconciliation" | "start_attempted" | "run_creation_unknown"
        ) || (is_resumable_status(&prior.status)
            && prior.run_id.as_deref().unwrap_or("").trim().is_empty())
            || (row.video_url != prior.video_url && !is_terminal_record_status(&prior.status));
        if unresolved {
            let mut result = prior.clone();
            result.current_url = Some(row.video_url);
            results.push(result);
        }
    }
    Ok(results)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::{SystemTime, UNIX_EPOCH};

    static TEMP_DIR_SEQUENCE: AtomicUsize = AtomicUsize::new(0);

    struct TestTempDir(std::path::PathBuf);

    impl std::ops::Deref for TestTempDir {
        type Target = Path;

        fn deref(&self) -> &Self::Target {
            &self.0
        }
    }

    impl AsRef<Path> for TestTempDir {
        fn as_ref(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestTempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[derive(Clone)]
    struct FakeTransport {
        handler: Arc<dyn Fn(HttpRequest) -> Result<HttpResponse, TransportError> + Send + Sync>,
    }

    impl HttpTransport for FakeTransport {
        fn send<'a>(&'a self, request: HttpRequest) -> TransportFuture<'a> {
            Box::pin(async move { (self.handler)(request) })
        }
    }

    #[derive(Clone)]
    struct DelayedFakeTransport {
        handler: Arc<dyn Fn(HttpRequest) -> Result<HttpResponse, TransportError> + Send + Sync>,
        active: Arc<AtomicUsize>,
        maximum: Arc<AtomicUsize>,
        delay: Duration,
    }

    impl HttpTransport for DelayedFakeTransport {
        fn send<'a>(&'a self, request: HttpRequest) -> TransportFuture<'a> {
            let handler = Arc::clone(&self.handler);
            let active = Arc::clone(&self.active);
            let maximum = Arc::clone(&self.maximum);
            let delay = self.delay;
            Box::pin(async move {
                let current = active.fetch_add(1, Ordering::SeqCst) + 1;
                maximum.fetch_max(current, Ordering::SeqCst);
                tokio::time::sleep(delay).await;
                let result = handler(request);
                active.fetch_sub(1, Ordering::SeqCst);
                result
            })
        }
    }

    fn response(status: u16, body: &str) -> HttpResponse {
        HttpResponse {
            status,
            body: body.as_bytes().to_vec(),
        }
    }

    fn fake_api<F>(handler: F) -> ApiClient
    where
        F: Fn(HttpRequest) -> Result<HttpResponse, TransportError> + Send + Sync + 'static,
    {
        ApiClient::new(
            "fake-token-never-log",
            Arc::new(FakeTransport {
                handler: Arc::new(handler),
            }),
        )
        .unwrap()
        .with_poll_interval(Duration::from_millis(1))
    }

    #[test]
    fn validates_wait_bounds_before_duration_conversion() {
        assert_eq!(parse_max_wait_seconds("900").unwrap(), 900);
        assert_eq!(parse_max_wait_seconds("1").unwrap(), 1);
        assert_eq!(parse_max_wait_seconds("86400").unwrap(), 86400);
        for invalid in ["0", "86401", "18446744073709551615", "1.5", "nope"] {
            assert!(
                parse_max_wait_seconds(invalid).is_err(),
                "accepted {invalid}"
            );
        }
        assert!(validate_max_wait_seconds(u64::MAX).is_err());
    }

    #[test]
    fn validates_supported_tiktok_video_url() {
        assert!(validate_video_url(DEFAULT_VIDEO_URL).is_ok());
        assert!(validate_video_url("https://vm.tiktok.com/abcd").is_err());
        assert!(validate_video_url("https://example.com/@user/video/123").is_err());
        assert!(validate_video_url("http://www.tiktok.com/@user/video/123").is_err());
    }

    fn ok(body: &str) -> Result<HttpResponse, TransportError> {
        Ok(response(200, body))
    }

    fn temp_dir() -> TestTempDir {
        loop {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let sequence = TEMP_DIR_SEQUENCE.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "tiktok-rust-offline-{}-{nonce}-{sequence}",
                std::process::id()
            ));
            match std::fs::create_dir(&path) {
                Ok(()) => return TestTempDir(path),
                Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
                Err(error) => panic!("could not create isolated test directory: {error}"),
            }
        }
    }

    #[test]
    fn temporary_directories_are_unique_during_parallel_test_setup() {
        let workers: Vec<_> = (0..16).map(|_| std::thread::spawn(temp_dir)).collect();
        let directories: Vec<_> = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect();
        let unique: HashSet<_> = directories
            .iter()
            .map(|directory| directory.to_path_buf())
            .collect();
        assert_eq!(unique.len(), directories.len());
        assert!(directories.iter().all(|directory| directory.is_dir()));
    }

    #[tokio::test]
    async fn start_uses_fixed_actor_request_and_posts_once() {
        std::env::set_var("APIFY_ACTOR_ID", "S9A11NvceWaGorwwh");
        let count = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&count);
        let api = fake_api(move |request| {
            observed.fetch_add(1, Ordering::SeqCst);
            assert_eq!(request.method, "POST");
            assert_eq!(
                request.url,
                "https://api.apify.com/v2/actors/apple_yang~tiktok-transcripts-scraper/runs"
            );
            assert_eq!(request.authorization, "Bearer fake-token-never-log");
            assert!(!request.url.contains("fake-token-never-log"));
            assert_eq!(
                serde_json::from_slice::<Value>(request.body.as_deref().unwrap()).unwrap(),
                json!({"videoUrl": DEFAULT_VIDEO_URL})
            );
            ok(r#"{"data":{"id":"RUN1","status":"READY"}}"#)
        });
        let run = api.start_run(DEFAULT_VIDEO_URL).await.unwrap();
        assert_eq!(run.id, "RUN1");
        assert_eq!(count.load(Ordering::SeqCst), 1);
        std::env::remove_var("APIFY_ACTOR_ID");
    }

    #[tokio::test]
    async fn malformed_successful_create_is_unknown_and_never_retried() {
        for body in ["null", "[]", r#"{"data":null}"#] {
            let count = Arc::new(AtomicUsize::new(0));
            let seen = Arc::clone(&count);
            let api = fake_api(move |_| {
                seen.fetch_add(1, Ordering::SeqCst);
                ok(body)
            });
            let error = api.start_run(DEFAULT_VIDEO_URL).await.unwrap_err();
            assert_eq!(error.kind, ErrorKind::RunCreationUnknown);
            assert!(error.to_string().contains("Check Apify Console"));
            assert!(!error.to_string().contains("fake-token-never-log"));
            assert_eq!(count.load(Ordering::SeqCst), 1);
        }
    }

    #[tokio::test]
    async fn run_envelope_terminal_wait_dataset_and_transcript_are_parsed() {
        let requests = Arc::new(std::sync::Mutex::new(Vec::<HttpRequest>::new()));
        let recorded = Arc::clone(&requests);
        let api = fake_api(move |request| {
            recorded.lock().unwrap().push(request.clone());
            if request.url.ends_with("/v2/actor-runs/RUN2") {
                ok(r#"{"data":{"id":"RUN2","status":"SUCCEEDED","defaultDatasetId":"DS2"}}"#)
            } else if request.url.ends_with("/v2/datasets/DS2/items") {
                ok(r#"[{"text":"transcript","segments":[],"errMsg":""}]"#)
            } else {
                panic!("unexpected request: {}", request.url);
            }
        });
        let run = api.wait_for_run("RUN2", 1).await.unwrap();
        let items = api
            .dataset_items(run.default_dataset_id.as_deref().unwrap())
            .await
            .unwrap();
        assert_eq!(run.status, "SUCCEEDED");
        assert!(transcript_failure(&run, &items).is_none());
        let got = requests.lock().unwrap();
        assert_eq!(got.len(), 2);
        assert!(got.iter().all(|request| request.method == "GET"));
        assert_eq!(got[0].url, "https://api.apify.com/v2/actor-runs/RUN2");
    }

    #[tokio::test]
    async fn malformed_run_envelope_is_an_error_not_a_pending_status() {
        let api = fake_api(|_| ok(r#"{"data":[]}"#));
        let error = api.wait_for_run("RUN3", 1).await.unwrap_err();
        assert_eq!(error.kind, ErrorKind::RunLookup);
        assert!(error
            .to_string()
            .contains("Invalid Run API response envelope"));
    }

    #[test]
    fn transcript_outcomes_distinguish_run_dataset_and_text_errors() {
        let run = Run {
            id: "R".into(),
            status: "SUCCEEDED".into(),
            default_dataset_id: Some("D".into()),
        };
        assert_eq!(transcript_failure(&run, &[]).unwrap().0, "dataset_empty");
        assert_eq!(
            transcript_failure(&run, &[json!({"text":""})]).unwrap().0,
            "transcript_empty"
        );
        assert_eq!(
            transcript_failure(&run, &[json!({"segments":[]})])
                .unwrap()
                .0,
            "transcript_empty"
        );
        assert_eq!(
            transcript_failure(&run, &[json!({"text":"ok", "errMsg":"failed"})])
                .unwrap()
                .0,
            "transcript_failed"
        );
        let failed = Run {
            status: "FAILED".into(),
            ..run
        };
        assert_eq!(transcript_failure(&failed, &[]).unwrap().0, "actor_failed");
    }

    #[tokio::test]
    async fn wait_timeout_keeps_same_run_id_and_never_posts() {
        let gets = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&gets);
        let api = fake_api(move |request| {
            assert_eq!(request.method, "GET");
            observed.fetch_add(1, Ordering::SeqCst);
            ok(r#"{"data":{"id":"RUN4","status":"RUNNING"}}"#)
        })
        .with_poll_interval(Duration::from_millis(10));
        let error = api.wait_for_run("RUN4", 1).await.unwrap_err();
        assert_eq!(error.kind, ErrorKind::WaitTimeout);
        assert!(error.to_string().contains("RUN4"));
        assert!(gets.load(Ordering::SeqCst) >= 1);
    }

    #[tokio::test]
    async fn max_wait_cancels_a_single_get_that_outlives_the_deadline() {
        let handler = Arc::new(|request: HttpRequest| {
            assert_eq!(request.method, "GET");
            ok(r#"{"data":{"id":"SLOW_RUN","status":"SUCCEEDED"}}"#)
        });
        let api = ApiClient::new(
            "test",
            Arc::new(DelayedFakeTransport {
                handler,
                active: Arc::new(AtomicUsize::new(0)),
                maximum: Arc::new(AtomicUsize::new(0)),
                delay: Duration::from_millis(1_100),
            }),
        )
        .unwrap();
        let error = api.wait_for_run("SLOW_RUN", 1).await.unwrap_err();
        assert_eq!(error.kind, ErrorKind::WaitTimeout);
        assert!(error.to_string().contains("SLOW_RUN"));
    }

    #[tokio::test]
    async fn csv_flushes_intent_before_single_post_and_summarizes_current_rows() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        std::fs::write(&csv, format!("videoUrl\n{}\n", DEFAULT_VIDEO_URL)).unwrap();
        let journal_for_post = journal.clone();
        let posts = Arc::new(AtomicUsize::new(0));
        let seen = Arc::clone(&posts);
        let api = fake_api(move |request| {
            if request.method == "POST" {
                seen.fetch_add(1, Ordering::SeqCst);
                let content = std::fs::read_to_string(&journal_for_post).unwrap();
                assert!(content.lines().last().unwrap().contains("start_attempted"));
                ok(r#"{"data":{"id":"CSV_RUN","status":"READY"}}"#)
            } else if request.url.ends_with("/v2/actor-runs/CSV_RUN") {
                ok(r#"{"data":{"id":"CSV_RUN","status":"SUCCEEDED","defaultDatasetId":"CSV_DS"}}"#)
            } else {
                ok(r#"[{"text":"ok","errMsg":""}]"#)
            }
        });
        let summary = process_csv(&csv, &journal, 1, 1, api).await.unwrap();
        assert_eq!(summary.get("transcript_success"), Some(&1));
        assert_eq!(posts.load(Ordering::SeqCst), 1);
        let contents = std::fs::read_to_string(&journal).unwrap();
        assert!(contents.contains("start_attempted"));
        assert!(contents.contains("transcript_success"));
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn csv_unknown_creation_is_reconcile_only_on_resume() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        std::fs::write(&csv, format!("videoUrl\n{}\n", DEFAULT_VIDEO_URL)).unwrap();
        let posts = Arc::new(AtomicUsize::new(0));
        let observed = Arc::clone(&posts);
        let api = fake_api(move |_| {
            observed.fetch_add(1, Ordering::SeqCst);
            Err(TransportError)
        });
        assert!(process_csv(&csv, &journal, 1, 1, api.clone())
            .await
            .is_err());
        assert!(process_csv(&csv, &journal, 1, 1, api).await.is_err());
        assert_eq!(posts.load(Ordering::SeqCst), 1);
        let rows = reconcile_csv(&csv, &journal).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "run_creation_unknown");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn csv_resumes_known_run_without_post_and_url_change_requires_reconcile() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        let old_url = "https://www.tiktok.com/@user/video/111";
        let new_url = "https://www.tiktok.com/@user/video/222";
        std::fs::write(&csv, format!("id,videoUrl\na,{old_url}\n")).unwrap();
        let seed = json!({"key":"id:a","id":"a","videoUrl":old_url,"status":"run_pending","run_id":"OLD_RUN"});
        std::fs::write(&journal, format!("{seed}\n")).unwrap();
        assert_eq!(read_csv_rows(&csv).unwrap()[0].key, "id:a");
        assert_eq!(
            read_journal(&journal).unwrap()["id:a"].status,
            "run_pending"
        );
        let gets = Arc::new(AtomicUsize::new(0));
        let posts = Arc::new(AtomicUsize::new(0));
        let gets_seen = Arc::clone(&gets);
        let posts_seen = Arc::clone(&posts);
        let api = fake_api(move |request| {
            if request.method == "POST" {
                posts_seen.fetch_add(1, Ordering::SeqCst);
            }
            if request.url.ends_with("/v2/actor-runs/OLD_RUN") {
                gets_seen.fetch_add(1, Ordering::SeqCst);
                ok(r#"{"data":{"id":"OLD_RUN","status":"SUCCEEDED","defaultDatasetId":"D1"}}"#)
            } else {
                ok(r#"[{"text":"old transcript","errMsg":""}]"#)
            }
        });
        let summary = process_csv(&csv, &journal, 1, 1, api).await.unwrap();
        assert_eq!(summary.get("transcript_success"), Some(&1));
        assert_eq!(gets.load(Ordering::SeqCst), 1);
        assert_eq!(posts.load(Ordering::SeqCst), 0);

        let unresolved = json!({"key":"id:a","id":"a","videoUrl":old_url,"status":"run_pending","run_id":"OLD_RUN"});
        std::fs::write(&journal, format!("{unresolved}\n")).unwrap();
        std::fs::write(&csv, format!("id,videoUrl\na,{new_url}\n")).unwrap();
        let forbidden =
            fake_api(|_| panic!("changed URL must not read old Run or create a new Run"));
        assert!(process_csv(&csv, &journal, 1, 1, forbidden).await.is_err());
        let reconciled = reconcile_csv(&csv, &journal).unwrap();
        assert_eq!(reconciled.len(), 1);
        assert_eq!(reconciled[0].status, "needs_reconciliation");
        assert_eq!(reconciled[0].video_url, old_url);
        assert_eq!(reconciled[0].current_url.as_deref(), Some(new_url));
        assert_eq!(reconciled[0].run_id.as_deref(), Some("OLD_RUN"));
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn csv_resumable_records_without_run_id_fail_closed_and_reconcile() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        let url = DEFAULT_VIDEO_URL;
        std::fs::write(&csv, format!("id,videoUrl\na,{url}\n")).unwrap();
        for status in ["run_pending", "dataset_error", "processing_error"] {
            let seed = json!({"key":"id:a","id":"a","videoUrl":url,"status":status});
            std::fs::write(&journal, format!("{seed}\n")).unwrap();
            let forbidden = fake_api(|_| panic!("missing run_id must not issue HTTP requests"));
            assert!(process_csv(&csv, &journal, 1, 1, forbidden).await.is_err());
            let latest = read_journal(&journal).unwrap();
            assert_eq!(latest["id:a"].status, "needs_reconciliation");
            assert!(latest["id:a"].run_id.is_none());
            let listed = reconcile_csv(&csv, &journal).unwrap();
            assert_eq!(listed.len(), 1);
            assert_eq!(listed[0].status, "needs_reconciliation");
        }
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn empty_changed_url_preserves_unresolved_run_for_reconciliation() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        let original = "https://www.tiktok.com/@user/video/456";
        std::fs::write(&csv, "id,videoUrl\na,\n").unwrap();
        let seed = json!({"key":"id:a","id":"a","videoUrl":original,"status":"run_pending","run_id":"KEEP_RUN"});
        std::fs::write(&journal, format!("{seed}\n")).unwrap();
        let forbidden = fake_api(|_| panic!("URL change must not read or create a Run"));
        assert!(process_csv(&csv, &journal, 1, 1, forbidden).await.is_err());
        let rows = reconcile_csv(&csv, &journal).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, "needs_reconciliation");
        assert_eq!(rows[0].video_url, original);
        assert_eq!(rows[0].current_url.as_deref(), Some(""));
        assert_eq!(rows[0].run_id.as_deref(), Some("KEEP_RUN"));
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn csv_terminal_url_change_starts_new_run_without_reusing_old_dataset() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        let old_url = "https://www.tiktok.com/@user/video/111";
        let new_url = "https://www.tiktok.com/@user/video/222";
        std::fs::write(&csv, format!("id,videoUrl\na,{new_url}\n")).unwrap();
        let seed = json!({"key":"id:a","id":"a","videoUrl":old_url,"status":"completed_with_transcript","run_id":"OLD_RUN","items":[{"text":"old transcript"}]});
        std::fs::write(&journal, format!("{seed}\n")).unwrap();
        let posts = Arc::new(AtomicUsize::new(0));
        let datasets = Arc::new(std::sync::Mutex::new(Vec::<String>::new()));
        let posts_seen = Arc::clone(&posts);
        let datasets_seen = Arc::clone(&datasets);
        let api = fake_api(move |request| {
            if request.method == "POST" {
                posts_seen.fetch_add(1, Ordering::SeqCst);
                assert_eq!(
                    serde_json::from_slice::<Value>(request.body.as_deref().unwrap()).unwrap()
                        ["videoUrl"],
                    new_url
                );
                ok(r#"{"data":{"id":"NEW_RUN"}}"#)
            } else if request.url.ends_with("/v2/actor-runs/NEW_RUN") {
                ok(r#"{"data":{"id":"NEW_RUN","status":"SUCCEEDED","defaultDatasetId":"NEW_DS"}}"#)
            } else {
                datasets_seen.lock().unwrap().push(request.url.clone());
                ok(r#"[{"text":"new transcript","errMsg":""}]"#)
            }
        });
        let summary = process_csv(&csv, &journal, 1, 1, api).await.unwrap();
        assert_eq!(summary.get("transcript_success"), Some(&1));
        assert_eq!(posts.load(Ordering::SeqCst), 1);
        assert_eq!(
            datasets.lock().unwrap().as_slice(),
            &["https://api.apify.com/v2/datasets/NEW_DS/items"]
        );
        let latest = read_journal(&journal).unwrap();
        assert_eq!(latest["id:a"].video_url, new_url);
        assert_eq!(latest["id:a"].run_id.as_deref(), Some("NEW_RUN"));
        assert_eq!(latest["id:a"].status, "transcript_success");
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn csv_concurrency_is_bounded_by_requested_limit() {
        let dir = temp_dir();
        let csv = dir.join("input.csv");
        let journal = dir.join("journal.jsonl");
        std::fs::write(
            &csv,
            format!(
                "videoUrl\n{}\n{}\n",
                DEFAULT_VIDEO_URL, "https://www.tiktok.com/@user/video/123"
            ),
        )
        .unwrap();
        let sequence = Arc::new(AtomicUsize::new(0));
        let sequence_seen = Arc::clone(&sequence);
        let handler = Arc::new(move |request: HttpRequest| {
            if request.method == "POST" {
                let id = sequence_seen.fetch_add(1, Ordering::SeqCst) + 1;
                ok(&format!(r#"{{"data":{{"id":"R{id}"}}}}"#))
            } else if request.url.contains("/v2/actor-runs/") {
                let id = request.url.rsplit('/').next().unwrap();
                ok(&format!(
                    r#"{{"data":{{"id":"{id}","status":"SUCCEEDED","defaultDatasetId":"DS"}}}}"#
                ))
            } else {
                ok(r#"[{"text":"valid","errMsg":""}]"#)
            }
        });
        let active = Arc::new(AtomicUsize::new(0));
        let maximum = Arc::new(AtomicUsize::new(0));
        let api = ApiClient::new(
            "test",
            Arc::new(DelayedFakeTransport {
                handler,
                active,
                maximum: Arc::clone(&maximum),
                delay: Duration::from_millis(10),
            }),
        )
        .unwrap()
        .with_poll_interval(Duration::from_millis(1));
        let summary = process_csv(&csv, &journal, 2, 1, api).await.unwrap();
        assert_eq!(summary.get("transcript_success"), Some(&2));
        assert!(maximum.load(Ordering::SeqCst) <= 2);
        assert_eq!(maximum.load(Ordering::SeqCst), 2);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn csv_parser_handles_bom_crlf_quoted_commas_and_rejects_duplicate_headers() {
        let dir = temp_dir();
        let path = dir.join("input.csv");
        std::fs::write(
            &path,
            format!(
                "\u{feff}id,videoUrl\r\n\"one, two\",{}\r\n",
                DEFAULT_VIDEO_URL
            ),
        )
        .unwrap();
        let rows = read_csv_rows(&path).unwrap();
        assert_eq!(rows[0].id.as_deref(), Some("one, two"));
        assert!(validate_concurrency(0).is_err());
        assert!(validate_concurrency(17).is_err());
        std::fs::write(&path, "videoUrl,videoUrl\n").unwrap();
        assert!(read_csv_rows(&path).is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }
}
