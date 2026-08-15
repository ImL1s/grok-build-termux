//! Platform capability detection and dynamic environment resolution for Grok.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use thiserror::Error;

/// Platform / OS classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlatformKind {
    /// Android under a valid Termux environment ($PREFIX present and valid).
    AndroidTermux,
    /// Android host without a supported Termux prefix (e.g. raw adb shell or standard app).
    UnsupportedAndroid,
    /// Desktop Linux (glibc / musl).
    DesktopLinux,
    /// macOS (Darwin).
    MacOS,
    /// Windows.
    Windows,
}

/// Compatibility alias for [`PlatformKind`].
pub type OsKind = PlatformKind;

#[allow(non_upper_case_globals)]
impl PlatformKind {
    pub const Linux: PlatformKind = PlatformKind::DesktopLinux;
    pub const MacOs: PlatformKind = PlatformKind::MacOS;
    pub const AndroidUnsupported: PlatformKind = PlatformKind::UnsupportedAndroid;
}

/// Truthful sandbox classification.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SandboxKind {
    /// Kernel-enforced sandbox via OS primitives (Landlock on Linux, Seatbelt on macOS).
    KernelEnforced,
    /// In-process policy enforcement only (Android/Termux).
    PolicyOnly,
    /// Sandbox is completely disabled.
    Disabled,
}

impl SandboxKind {
    pub const KERNEL_ENFORCED: &'static str = "kernel-enforced";
    pub const POLICY_ONLY: &'static str = "policy-only";
    pub const DISABLED: &'static str = "disabled";

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::KernelEnforced => Self::KERNEL_ENFORCED,
            Self::PolicyOnly => Self::POLICY_ONLY,
            Self::Disabled => Self::DISABLED,
        }
    }
}

/// Errors related to platform resolution.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum PlatformError {
    #[error("Environment variable PREFIX is not set. Grok Build requires a valid Termux environment on Android.")]
    MissingPrefix,
    #[error("Invalid $PREFIX on Android: {path:?} ({reason})")]
    InvalidPrefix { path: PathBuf, reason: String },
    #[error("HOME environment variable is not set")]
    MissingHome,
    #[error("Storage safety violation: {0}")]
    StorageSafety(#[from] StorageSafetyError),
    #[error("Socket path exceeds 108 bytes: {0}")]
    SocketPathTooLong(String),
}

/// Errors related to storage safety boundaries.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum StorageSafetyError {
    #[error(
        "GROK_HOME cannot reside on Android shared storage ({path:?}). \
        Owner-only permissions (0700) are required for credentials. Reason: {reason}"
    )]
    SharedStorageQuarantine {
        path: PathBuf,
        reason: &'static str,
    },
}

/// Injectable environment lookup interface for testability.
pub trait EnvLookup: Send + Sync {
    fn get_var(&self, key: &str) -> Option<String>;
    fn os_override(&self) -> Option<PlatformKind> {
        None
    }
}

/// Process environment implementation of [`EnvLookup`].
pub struct SystemEnv;

impl EnvLookup for SystemEnv {
    fn get_var(&self, key: &str) -> Option<String> {
        std::env::var(key).ok()
    }
}

/// Builder for [`MockEnv`].
#[derive(Default)]
pub struct MockEnvBuilder {
    vars: HashMap<String, String>,
    os: Option<PlatformKind>,
}

impl MockEnvBuilder {
    pub fn var(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.vars.insert(key.into(), value.into());
        self
    }

    pub fn os(mut self, os: PlatformKind) -> Self {
        self.os = Some(os);
        self
    }

    pub fn os_kind(self, os: PlatformKind) -> Self {
        self.os(os)
    }

    pub fn build(self) -> MockEnv {
        MockEnv {
            vars: self.vars,
            os_override: self.os,
        }
    }
}

/// Mock environment implementation for unit tests.
pub struct MockEnv {
    vars: HashMap<String, String>,
    os_override: Option<PlatformKind>,
}

impl MockEnv {
    pub fn new(vars: HashMap<String, String>) -> Self {
        Self {
            vars,
            os_override: None,
        }
    }

    pub fn builder() -> MockEnvBuilder {
        MockEnvBuilder::default()
    }
}

impl EnvLookup for MockEnv {
    fn get_var(&self, key: &str) -> Option<String> {
        self.vars.get(key).cloned()
    }

    fn os_override(&self) -> Option<PlatformKind> {
        self.os_override
    }
}

/// Centralized platform capability structure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlatformCapabilities {
    kind: PlatformKind,
    prefix: Option<PathBuf>,
    home: Option<PathBuf>,
    grok_home_env: Option<PathBuf>,
    tmp: PathBuf,
    has_display: bool,
    has_audio: bool,
    sandbox: SandboxKind,
}

static PLATFORM_CAPS: OnceLock<PlatformCapabilities> = OnceLock::new();

impl PlatformCapabilities {
    /// Global singleton instance probed from the process environment.
    pub fn current() -> &'static PlatformCapabilities {
        PLATFORM_CAPS.get_or_init(|| Self::probe(&SystemEnv))
    }

    /// Construct capabilities from an injectable [`EnvLookup`] provider.
    pub fn probe(env: &dyn EnvLookup) -> Self {
        let prefix_raw = env.get_var("PREFIX");
        let prefix_clean = prefix_raw.as_deref().map(str::trim).filter(|s| !s.is_empty());
        let prefix = prefix_clean.map(PathBuf::from);

        let kind = if let Some(os) = env.os_override() {
            match os {
                PlatformKind::AndroidTermux => {
                    if prefix.is_some() {
                        PlatformKind::AndroidTermux
                    } else {
                        PlatformKind::UnsupportedAndroid
                    }
                }
                PlatformKind::UnsupportedAndroid => PlatformKind::UnsupportedAndroid,
                PlatformKind::DesktopLinux => PlatformKind::DesktopLinux,
                PlatformKind::MacOS => PlatformKind::MacOS,
                PlatformKind::Windows => PlatformKind::Windows,
            }
        } else {
            let is_target_android = cfg!(target_os = "android");
            let is_target_macos = cfg!(target_os = "macos");
            let is_target_windows = cfg!(target_os = "windows");
            let is_target_linux = cfg!(target_os = "linux");

            if is_target_android {
                if prefix.is_some() || env.get_var("TERMUX_VERSION").is_some() {
                    PlatformKind::AndroidTermux
                } else {
                    PlatformKind::UnsupportedAndroid
                }
            } else if is_target_macos {
                PlatformKind::MacOS
            } else if is_target_windows {
                PlatformKind::Windows
            } else if is_target_linux {
                PlatformKind::DesktopLinux
            } else {
                PlatformKind::DesktopLinux
            }
        };

        let home = env
            .get_var("HOME")
            .or_else(|| env.get_var("USERPROFILE"))
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from);

        let grok_home_env = env
            .get_var("GROK_HOME")
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from);

        let tmp = env
            .get_var("TMPDIR")
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                if let Some(ref p) = prefix {
                    p.join("tmp")
                } else {
                    PathBuf::from("/tmp")
                }
            });

        let has_display = if kind == PlatformKind::AndroidTermux {
            env.get_var("DISPLAY").is_some() || env.get_var("WAYLAND_DISPLAY").is_some()
        } else if kind == PlatformKind::MacOS || kind == PlatformKind::Windows {
            true
        } else {
            env.get_var("DISPLAY").is_some()
                || env.get_var("WAYLAND_DISPLAY").is_some()
                || env.get_var("BROWSER").is_some()
        };

        let has_audio = match kind {
            PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid => false,
            PlatformKind::MacOS | PlatformKind::Windows | PlatformKind::DesktopLinux => true,
        };

        let sandbox = match kind {
            PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid => SandboxKind::PolicyOnly,
            PlatformKind::DesktopLinux | PlatformKind::MacOS => SandboxKind::KernelEnforced,
            PlatformKind::Windows => SandboxKind::Disabled,
        };

        Self {
            kind,
            prefix,
            home,
            grok_home_env,
            tmp,
            has_display,
            has_audio,
            sandbox,
        }
    }

    /// Convenience wrapper for [`Self::probe`].
    pub fn from_context(env: &dyn EnvLookup) -> Self {
        Self::probe(env)
    }

    /// Convenience wrapper for [`Self::probe`].
    pub fn from_env(env: &dyn EnvLookup) -> Self {
        Self::probe(env)
    }

    pub fn kind(&self) -> PlatformKind {
        self.kind
    }

    pub fn is_android_termux(&self) -> bool {
        self.kind == PlatformKind::AndroidTermux
    }

    pub fn is_android(&self) -> bool {
        matches!(
            self.kind,
            PlatformKind::AndroidTermux | PlatformKind::UnsupportedAndroid
        )
    }

    pub fn prefix_dir(&self) -> Result<&Path, PlatformError> {
        if self.is_android() {
            self.prefix
                .as_deref()
                .ok_or(PlatformError::MissingPrefix)
        } else {
            Ok(Path::new("/usr"))
        }
    }

    pub fn bin_dir(&self) -> Result<PathBuf, PlatformError> {
        if self.is_android() {
            let pfx = self.prefix_dir()?;
            Ok(pfx.join("bin"))
        } else {
            Ok(PathBuf::from("/usr/bin"))
        }
    }

    /// System configuration directory:
    /// - Termux: `$PREFIX/etc/grok`
    /// - Unsupported Android: `None`
    /// - Desktop Unix (Linux / macOS): `/etc/grok`
    /// - Windows: `None`
    pub fn system_config_dir(&self) -> Option<PathBuf> {
        match self.kind {
            PlatformKind::AndroidTermux => self.prefix.as_ref().map(|p| p.join("etc").join("grok")),
            PlatformKind::UnsupportedAndroid => None,
            PlatformKind::DesktopLinux | PlatformKind::MacOS => Some(PathBuf::from("/etc/grok")),
            PlatformKind::Windows => None,
        }
    }

    pub fn home_dir(&self) -> Result<PathBuf, PlatformError> {
        if let Some(ref gh) = self.grok_home_env {
            validate_storage_safety(gh)?;
            return Ok(gh.clone());
        }
        let user_home = self.home.as_ref().ok_or(PlatformError::MissingHome)?;
        let gh = user_home.join(".grok");
        validate_storage_safety(&gh)?;
        Ok(gh)
    }

    pub fn temp_dir(&self) -> PathBuf {
        self.tmp.clone()
    }

    pub fn create_socket_path(&self, session_id: &str) -> Result<PathBuf, PlatformError> {
        let tmp = self.temp_dir();
        let hash = blake3::hash(session_id.as_bytes());
        let short_hash = &hash.to_hex()[..8];
        let sock_name = format!("grok-{short_hash}.sock");
        let sock_path = tmp.join(&sock_name);

        let path_str = sock_path.to_string_lossy();
        if path_str.as_bytes().len() >= 108 {
            return Err(PlatformError::SocketPathTooLong(path_str.into_owned()));
        }
        Ok(sock_path)
    }

    pub fn sandbox_kind(&self) -> SandboxKind {
        self.sandbox
    }

    pub fn display_server_present(&self) -> bool {
        self.has_display
    }

    pub fn has_display_server(&self) -> bool {
        self.has_display
    }

    pub fn audio_capture_available(&self) -> bool {
        self.has_audio
    }

    pub fn has_audio_capture(&self) -> bool {
        self.has_audio
    }
}

/// Known Android shared storage path prefixes and subsegments that lack POSIX DAC permissions.
const ANDROID_SHARED_STORAGE_PREFIXES: &[&str] = &[
    "/sdcard",
    "/storage/emulated",
    "/storage/self",
    "/mnt/sdcard",
    "/mnt/media_rw",
    "/storage",
];

/// Validates that a path is safe for storing private keys, credentials, or state.
///
/// Strictly refuses Android shared storage paths to prevent world-readable leaks.
pub fn validate_storage_safety(path: &Path) -> Result<(), StorageSafetyError> {
    let path_str = path.to_string_lossy();
    let norm = path_str.replace('\\', "/");

    for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
        if norm == *prefix
            || norm.starts_with(&format!("{prefix}/"))
            || norm.starts_with(prefix)
            || norm.contains("/sdcard")
            || norm.contains("/storage/emulated/0")
        {
            return Err(StorageSafetyError::SharedStorageQuarantine {
                path: path.to_path_buf(),
                reason: "Android shared storage does not enforce POSIX user/group permissions and is accessible across apps.",
            });
        }
    }

    // If the path exists on disk, also check its canonicalized target in case of symlinks
    if let Ok(canon) = std::fs::canonicalize(path) {
        let canon_str = canon.to_string_lossy().replace('\\', "/");
        for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
            if canon_str == *prefix
                || canon_str.starts_with(&format!("{prefix}/"))
                || canon_str.starts_with(prefix)
                || canon_str.contains("/sdcard")
                || canon_str.contains("/storage/emulated/0")
            {
                return Err(StorageSafetyError::SharedStorageQuarantine {
                    path: path.to_path_buf(),
                    reason: "Canonical target resolves to Android shared storage which lacks POSIX permissions.",
                });
            }
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::{Path, PathBuf};

    #[test]
    fn test_stock_termux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "/data/data/com.termux/files/usr")
            .var("HOME", "/data/data/com.termux/files/home")
            .var("TMPDIR", "/data/data/com.termux/files/usr/tmp")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.is_android_termux());
        assert!(caps.is_android());
        assert_eq!(
            caps.prefix_dir().unwrap(),
            Path::new("/data/data/com.termux/files/usr")
        );
        assert_eq!(
            caps.system_config_dir(),
            Some(PathBuf::from("/data/data/com.termux/files/usr/etc/grok"))
        );
        assert_eq!(
            caps.bin_dir().unwrap(),
            PathBuf::from("/data/data/com.termux/files/usr/bin")
        );
        assert_eq!(
            caps.temp_dir(),
            PathBuf::from("/data/data/com.termux/files/usr/tmp")
        );
        assert_eq!(
            caps.home_dir().unwrap(),
            PathBuf::from("/data/data/com.termux/files/home/.grok")
        );
        assert_eq!(caps.sandbox_kind(), SandboxKind::PolicyOnly);
        assert_eq!(caps.sandbox_kind().as_str(), "policy-only");
        assert!(!caps.display_server_present());
        assert!(!caps.audio_capture_available());
    }

    #[test]
    fn test_custom_prefix_termux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "/data/data/custom.terminal.app/files/usr")
            .var("HOME", "/data/data/custom.terminal.app/files/home")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.is_android_termux());
        assert_eq!(
            caps.prefix_dir().unwrap(),
            Path::new("/data/data/custom.terminal.app/files/usr")
        );
        assert_eq!(
            caps.system_config_dir(),
            Some(PathBuf::from(
                "/data/data/custom.terminal.app/files/usr/etc/grok"
            ))
        );
        assert_eq!(
            caps.bin_dir().unwrap(),
            PathBuf::from("/data/data/custom.terminal.app/files/usr/bin")
        );
    }

    #[test]
    fn test_missing_prefix_on_android_fails_closed() {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            // No PREFIX set
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(caps.prefix_dir().is_err());
        assert_eq!(caps.prefix_dir().unwrap_err(), PlatformError::MissingPrefix);
        assert_eq!(caps.system_config_dir(), None);
        assert_ne!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
        assert_eq!(caps.kind(), PlatformKind::UnsupportedAndroid);
    }

    #[test]
    fn test_empty_or_whitespace_prefix_fails_closed() {
        let env1 = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "")
            .build();
        let caps1 = PlatformCapabilities::from_context(&env1);
        assert!(caps1.prefix_dir().is_err());
        assert_eq!(caps1.system_config_dir(), None);

        let env2 = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "   ")
            .build();
        let caps2 = PlatformCapabilities::from_context(&env2);
        assert!(caps2.prefix_dir().is_err());
        assert_eq!(caps2.system_config_dir(), None);
    }

    #[test]
    fn test_desktop_linux_platform_capabilities() {
        let env = MockEnv::builder()
            .os(PlatformKind::DesktopLinux)
            .var("HOME", "/home/alice")
            .var("DISPLAY", ":0")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(!caps.is_android_termux());
        assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
        assert_eq!(caps.temp_dir(), PathBuf::from("/tmp"));
        assert_eq!(caps.sandbox_kind(), SandboxKind::KernelEnforced);
        assert!(caps.display_server_present());
        assert!(caps.audio_capture_available());
    }

    #[test]
    fn test_macos_platform_capabilities() {
        let env = MockEnv::builder()
            .os(PlatformKind::MacOS)
            .var("HOME", "/Users/alice")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(!caps.is_android_termux());
        assert_eq!(caps.system_config_dir(), Some(PathBuf::from("/etc/grok")));
        assert!(caps.display_server_present());
        assert!(caps.audio_capture_available());
        assert_eq!(caps.sandbox_kind(), SandboxKind::KernelEnforced);
    }

    #[test]
    fn test_windows_platform_capabilities() {
        let env = MockEnv::builder()
            .os(PlatformKind::Windows)
            .var("USERPROFILE", "C:\\Users\\Alice")
            .build();
        let caps = PlatformCapabilities::from_context(&env);

        assert!(!caps.is_android_termux());
        assert_eq!(caps.system_config_dir(), None);
        assert_eq!(caps.sandbox_kind(), SandboxKind::Disabled);
        assert!(caps.display_server_present());
        assert!(caps.audio_capture_available());
    }

    #[test]
    fn test_display_detection_combinations() {
        // DISPLAY present
        let env1 = MockEnv::builder()
            .os(PlatformKind::DesktopLinux)
            .var("DISPLAY", ":1")
            .build();
        assert!(PlatformCapabilities::from_context(&env1).display_server_present());

        // WAYLAND_DISPLAY present
        let env2 = MockEnv::builder()
            .os(PlatformKind::DesktopLinux)
            .var("WAYLAND_DISPLAY", "wayland-1")
            .build();
        assert!(PlatformCapabilities::from_context(&env2).display_server_present());

        // Neither present on Linux
        let env3 = MockEnv::builder()
            .os(PlatformKind::DesktopLinux)
            .build();
        assert!(!PlatformCapabilities::from_context(&env3).display_server_present());

        // DISPLAY on Termux
        let env4 = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "/data/data/com.termux/files/usr")
            .var("DISPLAY", ":0")
            .build();
        assert!(PlatformCapabilities::from_context(&env4).display_server_present());

        // No DISPLAY on Termux
        let env5 = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "/data/data/com.termux/files/usr")
            .build();
        assert!(!PlatformCapabilities::from_context(&env5).display_server_present());
    }

    #[test]
    fn test_storage_safety_quarantine_rejections() {
        assert!(validate_storage_safety(Path::new("/sdcard")).is_err());
        assert!(validate_storage_safety(Path::new("/sdcard/.grok")).is_err());
        assert!(validate_storage_safety(Path::new("/storage/emulated/0/.grok")).is_err());
        assert!(validate_storage_safety(Path::new("/mnt/sdcard/grok")).is_err());
        assert!(validate_storage_safety(Path::new("/storage/self/primary/.grok")).is_err());
        assert!(validate_storage_safety(Path::new("/mnt/media_rw/sdcard0")).is_err());
        assert!(validate_storage_safety(Path::new("/data/data/com.termux/files/home/.grok")).is_ok());
        assert!(validate_storage_safety(Path::new("/home/user/.grok")).is_ok());
        assert!(validate_storage_safety(Path::new("/Users/user/.grok")).is_ok());
    }

    #[test]
    fn test_socket_path_length_constraint() {
        let env = MockEnv::builder()
            .os(PlatformKind::AndroidTermux)
            .var("PREFIX", "/data/data/com.termux/files/usr")
            .var("TMPDIR", "/data/data/com.termux/files/usr/tmp")
            .build();
        let caps = PlatformCapabilities::from_context(&env);
        let sock = caps.create_socket_path("session-123456-abcdef").unwrap();
        assert!(sock.to_string_lossy().len() < 108);
        assert!(sock.to_string_lossy().contains("grok-"));
    }

    #[test]
    fn test_current_singleton() {
        let caps = PlatformCapabilities::current();
        let _ = caps.kind();
        let _ = caps.system_config_dir();
        let _ = caps.temp_dir();
    }
}
