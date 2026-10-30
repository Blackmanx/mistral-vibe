//! The PyPI update gateway.

use std::time::Duration;

use serde_json::Value;

use super::pep440::{parse_pep440_version, Pep440Version};
pub use crate::utils::tls::{
    apply_tls_trust, apply_tls_trust_for, configure_tls_trust, custom_root_certificates,
    tls_trust_store, TlsTrustStore,
};

const DEFAULT_BASE_URL: &str = "https://pypi.org";
/// The fork this build tracks: its `main` is what an install of it follows.
pub const FORK_REPOSITORY: &str = "Blackmanx/mistral-vibe";
/// The fork's manifest. Its `[project] version` is the version the branch ships.
pub const FORK_PYPROJECT_URL: &str =
    "https://raw.githubusercontent.com/Blackmanx/mistral-vibe/main/pyproject.toml";
/// The fork's head, so a commit that keeps the same version still counts.
pub const FORK_COMMIT_URL: &str =
    "https://api.github.com/repos/Blackmanx/mistral-vibe/commits/main";
const TIMEOUT_SECONDS: u64 = 5;
const ACCEPT_HEADER: &str = "application/vnd.pypi.simple.v1+json";

/// The gateway's answer.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Update {
    pub latest_version: String,
}

/// Why an update check failed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UpdateGatewayCause {
    TooManyRequests,
    Forbidden,
    NotFound,
    RequestFailed,
    ErrorResponse,
    InvalidResponse,
    Unknown,
}

/// Default user messages, keyed by cause.
pub fn default_gateway_message(cause: UpdateGatewayCause) -> &'static str {
    match cause {
        UpdateGatewayCause::TooManyRequests => "Rate limit exceeded while checking for updates.",
        UpdateGatewayCause::Forbidden => "Request was forbidden while checking for updates.",
        UpdateGatewayCause::NotFound => {
            "Unable to fetch the releases. Please check your permissions."
        }
        UpdateGatewayCause::RequestFailed => "Network error while checking for updates.",
        UpdateGatewayCause::ErrorResponse => {
            "Unexpected response received while checking for updates."
        }
        UpdateGatewayCause::InvalidResponse => {
            "Received an invalid response while checking for updates."
        }
        UpdateGatewayCause::Unknown => "Unable to determine whether an update is available.",
    }
}

/// A failed update check: its cause and an optional user message.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UpdateGatewayError {
    pub cause: UpdateGatewayCause,
    pub user_message: Option<String>,
}

impl UpdateGatewayError {
    pub fn new(cause: UpdateGatewayCause) -> Self {
        Self {
            cause,
            user_message: None,
        }
    }
}

/// The package manager whose answer an update check (or a cache entry)
/// belongs to. Detection follows the install: a uv tool asks uv, a brew
/// install asks brew, and anything else polls PyPI.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UpdateSource {
    /// The PyPI Simple API gateway.
    Pypi,
    /// uv's own resolution for the installed tool.
    Uv,
    /// brew's own answer for the installed formula.
    Brew,
    /// The fork's `main` branch, which has no package manager behind it.
    Fork,
}

impl UpdateSource {
    /// The `[update_cache].source` value written alongside an answer.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pypi => "pypi",
            Self::Uv => "uv",
            Self::Brew => "brew",
            Self::Fork => "fork",
        }
    }
}

/// Fetch the latest available release. `source` is
/// the manager the implementing gateway asks, stamped on every cache write so
/// a later reader can reject an answer a different install's manager gave.
pub trait UpdateGateway {
    fn fetch_update(
        &self,
    ) -> impl std::future::Future<Output = Result<Option<Update>, UpdateGatewayError>>;

    /// The manager this gateway consults; the default is the PyPI Simple API.
    fn source(&self) -> UpdateSource {
        UpdateSource::Pypi
    }
}

/// The one client builder for every Vibe-owned HTTPS request (ADR 0015), under
/// the given trust store and the caller's timeout. Redirects stay off.
pub fn build_http_client_for(
    trust: TlsTrustStore,
    timeout: Duration,
) -> Result<reqwest::Client, reqwest::Error> {
    let builder = crate::utils::system_proxy::apply(
        reqwest::Client::builder()
            .timeout(timeout)
            // Redirects are not followed.
            .redirect(reqwest::redirect::Policy::none()),
    );
    apply_tls_trust_for(builder, trust).build()
}

/// The gateway's HTTP client: the effective trust policy (ADR 0015) with the
/// gateway's own timeout.
pub fn build_http_client() -> Result<reqwest::Client, reqwest::Error> {
    build_http_client_for(tls_trust_store(), Duration::from_secs(TIMEOUT_SECONDS))
}

/// The wizard's Vibe-owned HTTP client (browser sign-in, whoami): the shared
/// ADR 0015 builder under the server-resolved trust flag from `setup/status`.
/// Never falls back to a bare library default: the trust roots are always the
/// policy's choice. A build failure (e.g. the system trust store with no CA
/// certificates loaded) is returned, not panicked on: callers treat it like
/// any request failure.
pub fn wizard_http_client(
    timeout: Duration,
    enable_system_trust_store: bool,
) -> Result<reqwest::Client, reqwest::Error> {
    let trust = if enable_system_trust_store {
        TlsTrustStore::System
    } else {
        TlsTrustStore::BundledWebPki
    };
    build_http_client_for(trust, timeout)
}

/// The update gateway over the PyPI Simple API.
pub struct PyPIUpdateGateway {
    project_name: String,
    base_url: String,
}

impl PyPIUpdateGateway {
    pub fn new(project_name: &str) -> Self {
        Self::with_base_url(project_name, DEFAULT_BASE_URL)
    }

    /// The index base URL. Production checks always
    /// target PyPI; only tests point this elsewhere.
    pub fn with_base_url(project_name: &str, base_url: &str) -> Self {
        Self {
            project_name: project_name.to_owned(),
            base_url: base_url.trim_end_matches('/').to_owned(),
        }
    }

    /// The Simple API project URL this gateway polls.
    pub fn request_url(&self) -> String {
        format!("{}/simple/{}/", self.base_url, self.project_name)
    }
}

impl UpdateGateway for PyPIUpdateGateway {
    async fn fetch_update(&self) -> Result<Option<Update>, UpdateGatewayError> {
        let client = build_http_client()
            .map_err(|_| UpdateGatewayError::new(UpdateGatewayCause::RequestFailed))?;
        let response = match client
            .get(self.request_url())
            .header("Accept", ACCEPT_HEADER)
            .send()
            .await
        {
            Ok(response) => response,
            Err(_) => return Err(UpdateGatewayError::new(UpdateGatewayCause::RequestFailed)),
        };
        if let Some(cause) = status_cause(response.status().as_u16()) {
            return Err(UpdateGatewayError::new(cause));
        }
        if response.status().is_client_error() || response.status().is_server_error() {
            return Err(UpdateGatewayError::new(UpdateGatewayCause::ErrorResponse));
        }
        match response.json::<Value>().await {
            Ok(data) => Ok(parse_response(&data)),
            Err(_) => Err(UpdateGatewayError::new(UpdateGatewayCause::InvalidResponse)),
        }
    }
}

/// The production check. The manager is decided by the running install:
/// uv's own resolution — the user's index, pinned `exclude-newer`, per-package
/// rules — governs a uv tool, brew's formula metadata governs a brew
/// install, and the rest poll the PyPI Simple API.
pub enum UpdateCheckGateway {
    UvOracle(super::uv_oracle::UvOracleGateway),
    Brew(super::brew_oracle::BrewOracleGateway),
    PyPI(PyPIUpdateGateway),
    Fork(ForkUpdateGateway),
}

/// The fork's answer: the version its `main` branch declares.
pub struct ForkUpdateGateway;

impl ForkUpdateGateway {
    pub async fn fetch_update(&self) -> Result<Option<Update>, UpdateGatewayError> {
        let client = build_http_client()
            .map_err(|_| UpdateGatewayError::new(UpdateGatewayCause::RequestFailed))?;
        let Some(version) = self.manifest_version(&client).await? else {
            return Ok(None);
        };
        // The head commit is what lets a merge that keeps the same version be
        // seen; when GitHub cannot answer it, the release version alone speaks.
        let commit = self.head_commit(&client).await.ok().flatten();
        Ok(Some(Update {
            latest_version: match commit {
                Some(commit) => format!("{version}+fork.{commit}"),
                None => version,
            },
        }))
    }

    async fn manifest_version(
        &self,
        client: &reqwest::Client,
    ) -> Result<Option<String>, UpdateGatewayError> {
        let response = match client.get(FORK_PYPROJECT_URL).send().await {
            Ok(response) => response,
            Err(_) => return Err(UpdateGatewayError::new(UpdateGatewayCause::RequestFailed)),
        };
        if let Some(cause) = status_cause(response.status().as_u16()) {
            return Err(UpdateGatewayError::new(cause));
        }
        if !response.status().is_success() {
            return Err(UpdateGatewayError::new(UpdateGatewayCause::ErrorResponse));
        }
        match response.text().await {
            Ok(body) => Ok(parse_pyproject_version(&body)),
            Err(_) => Err(UpdateGatewayError::new(UpdateGatewayCause::InvalidResponse)),
        }
    }

    async fn head_commit(
        &self,
        client: &reqwest::Client,
    ) -> Result<Option<String>, UpdateGatewayError> {
        let response = client
            .get(FORK_COMMIT_URL)
            .header("Accept", "application/vnd.github+json")
            // GitHub answers 403 to a request without a User-Agent, and the
            // check would then silently fall back to comparing versions.
            .header("User-Agent", format!("vibe/{}", crate::version::PACKAGE))
            .send()
            .await
            .map_err(|_| UpdateGatewayError::new(UpdateGatewayCause::RequestFailed))?;
        if !response.status().is_success() {
            return Err(UpdateGatewayError::new(UpdateGatewayCause::ErrorResponse));
        }
        let data = response
            .json::<Value>()
            .await
            .map_err(|_| UpdateGatewayError::new(UpdateGatewayCause::InvalidResponse))?;
        Ok(data
            .get("sha")
            .and_then(Value::as_str)
            .map(|sha| sha.chars().take(7).collect()))
    }
}

/// The `version` of a `pyproject.toml`'s `[project]` table, or `None`.
pub fn parse_pyproject_version(text: &str) -> Option<String> {
    let mut in_project = false;
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_project = line == "[project]";
            continue;
        }
        if !in_project {
            continue;
        }
        let Some(rest) = line.strip_prefix("version") else {
            continue;
        };
        let Some(rest) = rest.trim_start().strip_prefix('=') else {
            continue;
        };
        let quoted = rest.trim().strip_prefix('"')?;
        return quoted.split('"').next().map(str::to_owned);
    }
    None
}

impl UpdateCheckGateway {
    /// The check the CLI runs, against the manager that owns this install.
    /// Async because the probes shell out to `uv tool dir` and `brew --cellar`.
    pub async fn for_project(_project_name: &str) -> Self {
        // This fork is installed from its own wheel, never from PyPI nor a
        // package manager, so the package-manager oracles have no answer for
        // it: the branch itself is the update source.
        Self::Fork(ForkUpdateGateway)
    }
}

/// The manager this process's install was made with, mirroring the gateway
/// choice: a uv tool receipt names uv, an executable under brew's prefix
/// names brew, and everything else reads as PyPI.
pub async fn install_source() -> UpdateSource {
    if super::uv_oracle::is_uv_managed().await {
        UpdateSource::Uv
    } else if super::brew_oracle::is_brew_install().await {
        UpdateSource::Brew
    } else {
        UpdateSource::Pypi
    }
}

impl UpdateGateway for UpdateCheckGateway {
    async fn fetch_update(&self) -> Result<Option<Update>, UpdateGatewayError> {
        match self {
            Self::UvOracle(gateway) => gateway.fetch_update().await,
            Self::Brew(gateway) => gateway.fetch_update().await,
            Self::PyPI(gateway) => gateway.fetch_update().await,
            Self::Fork(gateway) => gateway.fetch_update().await,
        }
    }

    fn source(&self) -> UpdateSource {
        match self {
            Self::UvOracle(_) => UpdateSource::Uv,
            Self::Brew(_) => UpdateSource::Brew,
            Self::PyPI(_) => UpdateSource::Pypi,
            Self::Fork(_) => UpdateSource::Fork,
        }
    }
}

/// 404/403/429 map to their own causes.
fn status_cause(status: u16) -> Option<UpdateGatewayCause> {
    match status {
        404 => Some(UpdateGatewayCause::NotFound),
        403 => Some(UpdateGatewayCause::Forbidden),
        429 => Some(UpdateGatewayCause::TooManyRequests),
        _ => None,
    }
}

/// The highest listed version that also has a
/// non-yanked file. Unparsable versions and filenames are skipped.
pub fn parse_response(data: &Value) -> Option<Update> {
    let versions = data
        .get("versions")
        .and_then(Value::as_array)
        .map(|versions| {
            versions
                .iter()
                .filter_map(|raw| raw.as_str())
                .filter_map(parse_pep440_version)
                .collect::<Vec<Pep440Version>>()
        })
        .unwrap_or_default();
    // Stable sort, highest first.
    let mut valid_versions = versions;
    valid_versions.sort_by(|left, right| right.cmp(left));

    let non_yanked = non_yanked_versions(data);
    for version in valid_versions {
        if non_yanked.contains(&version) {
            return Some(Update {
                latest_version: version.as_str(),
            });
        }
    }
    None
}

fn non_yanked_versions(data: &Value) -> Vec<Pep440Version> {
    let files = data
        .get("files")
        .and_then(Value::as_array)
        .map(|files| {
            files
                .iter()
                // Skip non-object entries and yanked files.
                .filter(|file| file.as_object().is_some())
                .filter(|file| file.get("yanked").and_then(Value::as_bool) != Some(true))
                .filter_map(|file| file.get("filename").and_then(Value::as_str))
                .filter_map(parse_filename_version)
                .collect::<Vec<Pep440Version>>()
        })
        .unwrap_or_default();
    files
}

/// The wheel's second `-`-separated part, else the sdist's last one, else
/// unparsable. Full PEP 440, like `packaging`'s `parse_wheel_filename` /
/// `parse_sdist_filename`.
fn parse_filename_version(filename: &str) -> Option<Pep440Version> {
    if let Some(stem) = filename.strip_suffix(".whl") {
        let mut parts = stem.split('-');
        let _name = parts.next()?;
        let version = parts.next()?;
        return parse_pep440_version(version);
    }
    let stem = filename
        .strip_suffix(".tar.gz")
        .or_else(|| filename.strip_suffix(".zip"))?;
    let version = stem.rsplit('-').next()?;
    parse_pep440_version(version)
}
