//! Native tool resolution and actionable remediation hints.
//!
//! Provides a unified interface for resolving native CLI tools (`rg`, `fd`, `git`, `bash`, `bfs`, `ugrep`)
//! from `$PATH`, Termux `$PREFIX/bin`, and platform-specific fallback locations with actionable
//! package manager installation hints when missing.

use std::path::{Path, PathBuf};
use thiserror::Error;
use xai_grok_config::platform::PlatformCapabilities;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolRequirement {
    Required,
    Optional,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolSpec {
    pub binary_name: &'static str,
    pub termux_package: &'static str,
    pub debian_package: &'static str,
    pub brew_package: &'static str,
    pub requirement: ToolRequirement,
    pub env_override: Option<&'static str>,
}

pub const TOOL_RG: ToolSpec = ToolSpec {
    binary_name: "rg",
    termux_package: "ripgrep",
    debian_package: "ripgrep",
    brew_package: "ripgrep",
    requirement: ToolRequirement::Required,
    env_override: Some("RG_BIN_PATH"),
};

pub const TOOL_FD: ToolSpec = ToolSpec {
    binary_name: "fd",
    termux_package: "fd",
    debian_package: "fd-find",
    brew_package: "fd",
    requirement: ToolRequirement::Required,
    env_override: Some("FD_BIN_PATH"),
};

pub const TOOL_GIT: ToolSpec = ToolSpec {
    binary_name: "git",
    termux_package: "git",
    debian_package: "git",
    brew_package: "git",
    requirement: ToolRequirement::Required,
    env_override: None,
};

pub const TOOL_BASH: ToolSpec = ToolSpec {
    binary_name: "bash",
    termux_package: "bash",
    debian_package: "bash",
    brew_package: "bash",
    requirement: ToolRequirement::Required,
    env_override: Some("GROK_SHELL"),
};

pub const TOOL_BFS: ToolSpec = ToolSpec {
    binary_name: "bfs",
    termux_package: "bfs",
    debian_package: "bfs",
    brew_package: "bfs",
    requirement: ToolRequirement::Optional,
    env_override: Some("GROK_TOOLS_BFS_PATH"),
};

pub const TOOL_UGREP: ToolSpec = ToolSpec {
    binary_name: "ugrep",
    termux_package: "ugrep",
    debian_package: "ugrep",
    brew_package: "ugrep",
    requirement: ToolRequirement::Optional,
    env_override: Some("GROK_TOOLS_UGREP_PATH"),
};

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ToolResolutionError {
    #[error("Required tool '{name}' not found in PATH or standard locations. {remediation}")]
    MissingRequiredTool {
        name: String,
        remediation: String,
    },
    #[error("Tool '{name}' found at {path:?} but is not executable")]
    NotExecutable {
        name: String,
        path: PathBuf,
    },
}

pub struct ToolResolver;

impl ToolResolver {
    /// Resolves a tool path according to the native search cascade.
    pub fn resolve(spec: &ToolSpec) -> Result<PathBuf, ToolResolutionError> {
        // 1. Env override
        if let Some(env_key) = spec.env_override {
            if let Ok(val) = std::env::var(env_key) {
                let p = PathBuf::from(val);
                if p.is_file() {
                    return Ok(p);
                }
            }
        }

        // 2. which::which on $PATH
        if let Ok(p) = which::which(spec.binary_name) {
            if p.is_file() {
                return Ok(p);
            }
        }

        // 3. Termux bin dir ($PREFIX/bin)
        let caps = PlatformCapabilities::current();
        if let Ok(bin_dir) = caps.bin_dir() {
            let p = bin_dir.join(spec.binary_name);
            if p.is_file() {
                return Ok(p);
            }
        }

        // 4. Android system bin fallbacks
        for sys_dir in [
            "/data/data/com.termux/files/usr/bin",
            "/system/bin",
            "/system/xbin",
        ] {
            let p = Path::new(sys_dir).join(spec.binary_name);
            if p.is_file() {
                return Ok(p);
            }
        }

        // 5. Desktop Unix fallback dirs
        for dir in ["/usr/bin", "/bin", "/usr/local/bin", "/opt/homebrew/bin"] {
            let p = Path::new(dir).join(spec.binary_name);
            if p.is_file() {
                return Ok(p);
            }
        }

        let remediation = Self::remediation_hint(spec);
        Err(ToolResolutionError::MissingRequiredTool {
            name: spec.binary_name.to_string(),
            remediation,
        })
    }

    /// Resolves a tool by binary name (using known specs or falling back to default).
    pub fn resolve_tool(name: &str) -> Result<PathBuf, ToolResolutionError> {
        let spec = match name {
            "rg" | "ripgrep" => TOOL_RG,
            "fd" => TOOL_FD,
            "git" => TOOL_GIT,
            "bash" => TOOL_BASH,
            "bfs" => TOOL_BFS,
            "ugrep" => TOOL_UGREP,
            _ => ToolSpec {
                binary_name: Box::leak(name.to_string().into_boxed_str()),
                termux_package: Box::leak(name.to_string().into_boxed_str()),
                debian_package: Box::leak(name.to_string().into_boxed_str()),
                brew_package: Box::leak(name.to_string().into_boxed_str()),
                requirement: ToolRequirement::Required,
                env_override: None,
            },
        };
        Self::resolve(&spec)
    }

    /// Resolves an optional tool (returning None on absence without error).
    pub fn resolve_optional(spec: &ToolSpec) -> Option<PathBuf> {
        Self::resolve(spec).ok()
    }

    /// Generates actionable package manager install commands.
    pub fn remediation_hint(spec: &ToolSpec) -> String {
        let caps = PlatformCapabilities::current();
        if caps.is_android() {
            format!("In Termux, run: pkg install {}", spec.termux_package)
        } else if cfg!(target_os = "macos") {
            format!("On macOS, run: brew install {}", spec.brew_package)
        } else {
            format!("On Linux, run: apt install {}", spec.debian_package)
        }
    }

    /// Generates remediation hint by tool name.
    pub fn remediation_hint_for_name(name: &str) -> String {
        match name {
            "rg" | "ripgrep" => Self::remediation_hint(&TOOL_RG),
            "fd" => Self::remediation_hint(&TOOL_FD),
            "git" => Self::remediation_hint(&TOOL_GIT),
            "bash" => Self::remediation_hint(&TOOL_BASH),
            "bfs" => Self::remediation_hint(&TOOL_BFS),
            "ugrep" => Self::remediation_hint(&TOOL_UGREP),
            other => {
                let caps = PlatformCapabilities::current();
                if caps.is_android() {
                    format!("In Termux, run: pkg install {other}")
                } else if cfg!(target_os = "macos") {
                    format!("On macOS, run: brew install {other}")
                } else {
                    format!("On Linux, run: apt install {other}")
                }
            }
        }
    }

    /// Diagnoses all essential and optional CLI tools.
    pub fn diagnose_all_tools() -> Vec<ToolDiagnosticStatus> {
        let specs = [&TOOL_RG, &TOOL_FD, &TOOL_GIT, &TOOL_BASH, &TOOL_BFS, &TOOL_UGREP];
        specs
            .into_iter()
            .map(|spec| {
                let optional = spec.requirement == ToolRequirement::Optional;
                let remediation = Self::remediation_hint(spec);
                match Self::resolve(spec) {
                    Ok(path) => {
                        let version = probe_tool_version(&path);
                        ToolDiagnosticStatus {
                            name: spec.binary_name,
                            installed: true,
                            path: Some(path),
                            version,
                            optional,
                            remediation,
                        }
                    }
                    Err(_) => ToolDiagnosticStatus {
                        name: spec.binary_name,
                        installed: false,
                        path: None,
                        version: None,
                        optional,
                        remediation,
                    },
                }
            })
            .collect()
    }
}

/// Diagnostic status for a CLI tool.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ToolDiagnosticStatus {
    pub name: &'static str,
    pub installed: bool,
    pub path: Option<PathBuf>,
    pub version: Option<String>,
    pub optional: bool,
    pub remediation: String,
}

/// Probes the version of a tool by invoking `<path> --version`.
pub fn probe_tool_version(path: &Path) -> Option<String> {
    use std::process::Command;
    let out = Command::new(path).arg("--version").output().ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    stdout.lines().next().map(|l| l.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_known_tool_specs() {
        assert_eq!(TOOL_RG.binary_name, "rg");
        assert_eq!(TOOL_RG.termux_package, "ripgrep");
        assert_eq!(TOOL_FD.binary_name, "fd");
        assert_eq!(TOOL_FD.termux_package, "fd");
        assert_eq!(TOOL_GIT.binary_name, "git");
        assert_eq!(TOOL_GIT.termux_package, "git");
        assert_eq!(TOOL_BASH.binary_name, "bash");
        assert_eq!(TOOL_BASH.termux_package, "bash");
        assert_eq!(TOOL_BFS.requirement, ToolRequirement::Optional);
        assert_eq!(TOOL_UGREP.requirement, ToolRequirement::Optional);
    }

    #[test]
    fn test_resolve_tool_missing_returns_remediation() {
        let err = ToolResolver::resolve_tool("nonexistent_tool_xyz123").unwrap_err();
        match err {
            ToolResolutionError::MissingRequiredTool { name, remediation } => {
                assert_eq!(name, "nonexistent_tool_xyz123");
                assert!(remediation.contains("nonexistent_tool_xyz123"));
            }
            _ => panic!("Expected MissingRequiredTool error"),
        }
    }

    #[test]
    fn test_resolve_optional_returns_none_when_missing() {
        let fake_spec = ToolSpec {
            binary_name: "nonexistent_opt_tool_xyz",
            termux_package: "nonexistent_opt_tool_xyz",
            debian_package: "nonexistent_opt_tool_xyz",
            brew_package: "nonexistent_opt_tool_xyz",
            requirement: ToolRequirement::Optional,
            env_override: None,
        };
        assert_eq!(ToolResolver::resolve_optional(&fake_spec), None);
    }
}
