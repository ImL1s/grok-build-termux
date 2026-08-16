# Runtime Tool Resolution & Native Execution Analysis (Milestone 2)

**Author**: Explorer 3 (Milestone 2: Native Bionic Build & Toolchain Alignment)  
**Date**: 2026-08-16  
**Working Directory**: `/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m2_3`  
**Target Scope**: Runtime resolution of `rg`, `fd`, `git`, `bash`, `bfs`, and `ugrep` on Android/Termux (`aarch64-linux-android` Bionic libc).

---

## 1. Observation

Direct codebase observations across `crates/codegen/xai-grok-tools`, `crates/codegen/xai-grok-shell`, `crates/codegen/xai-grok-config`, and test harness:

### 1.1 Compile-Time Asset Bundling (`build.rs`)
- In `crates/codegen/xai-grok-tools/build.rs`:
  - Lines 81–95: `bundle_fd()` downloads tarballs from GitHub for `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl`, and Darwin. For other targets, lines 88–91 fail:
    ```rust
    _ => {
        if path_override.is_none() {
            return Err(format!(
                "Unsupported target for fd bundling: {target_os}-{target_arch}. Set GROK_TOOLS_BUNDLE_FD_PATH to a local fd binary for offline or unsupported builds.",
            ).into());
        }
        (FD_VER, "override")
    }
    ```
  - Lines 258–261: Windows target is explicitly skipped (`if target_os == "windows" && path_override.is_none() { return Ok(()); }`), but Android target (`target_os == "android"`) is missing and hits line 289:
    ```rust
    _ => {
        return Err(format!(
            "Unsupported target for ripgrep bundling: {os}-{arch}. Set GROK_TOOLS_BUNDLE_RG_PATH to a local rg binary for offline or unsupported builds.",
            os = target_os,
            arch = target_arch
        ).into());
    }
    ```
- In `crates/codegen/xai-grok-shell/build.rs`:
  - Lines 51–54 and 86–92 exhibit identical behavior for ripgrep bundling.
- **Impact**: Any `cargo build --target aarch64-linux-android` fails during `build.rs` execution unless Android is explicitly gated out of auto-bundling. Furthermore, even if Linux binaries were downloaded, they would be linked against glibc (`/lib/ld-linux-aarch64.so.1`) or musl, which fail immediately on Android Bionic libc with `No such file or directory` or dynamic linking symbol panics.

### 1.2 Ripgrep Resolution & Execution
- In `crates/codegen/xai-grok-tools/src/implementations/grok_build/grep/ripgrep.rs`:
  - Lines 43–81: `rg_path()` checks `resolve_bundled_rg()`, then `RG_BIN_PATH`, then `RUNFILES_DIR`, and lastly returns `PathBuf::from("rg")`.
  - When `rg` is not bundled (`#[cfg(not(bundle_rg))]`), it relies on `"rg"` being in `$PATH`.
- In `crates/codegen/xai-grok-tools/src/implementations/grok_build/grep/mod.rs`:
  - Lines 758–760: `let rg_exec = rg_path(); let mut cmd = Command::new(rg_exec);`
  - Lines 835–846: When `cmd.spawn()` fails on missing binary, it returns raw OS error:
    ```rust
    Err(e) => {
        return Ok(GrepStep::Early(GrepSearchOutput {
            stdout: Vec::new(),
            stderr: format!("Error calling tool: {}", e).into_bytes(),
            exit_code: -1,
            match_count: 0,
            file_matches: Vec::new(),
        }));
    }
    ```
  - There is no actionable remediation hint suggesting `pkg install ripgrep` on Termux.

### 1.3 Unix Shell (`bash` / `zsh`) Resolution
- In `crates/codegen/xai-grok-config/src/shell.rs`:
  - Lines 425–464: `resolve_unix_shell_path(kind)` executes the following cascade:
    1. `$GROK_SHELL` override
    2. `$SHELL` env variable
    3. `which::which(name)`
    4. Fixed candidate paths: `["/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"]`
    5. Hardcoded default: `/bin/bash` or `/bin/zsh`
  - Lines 484–503: `is_executable(path)` checks permissions and verifies `--version`.
- In `crates/codegen/xai-grok-tools/src/computer/local/shell_state.rs`:
  - Lines 206–212: `ShellKind::binary_path(&self)` calls `xai_grok_config::shell::unix_shell_path`.
  - Line 293: `let mut cmd = tokio::process::Command::new(shell.binary_path());`
- **Impact on Termux**:
  - Android does NOT have a root `/bin` directory or `/usr/bin` (unless using proot or termux-exec).
  - Termux binaries reside in `$PREFIX/bin` (standard default `/data/data/com.termux/files/usr/bin/bash`).
  - Android system shell resides at `/system/bin/sh`.
  - If `$PATH` is not inherited or stripped in a subshell/tool execution, falling back to `/bin/bash` causes an immediate `ENOENT` failure.

### 1.4 Git Invocation
- In `crates/codegen/xai-fast-worktree` and `crates/codegen/xai-codebase-graph`:
  - Direct invocations via `std::process::Command::new("git")` and `tokio::process::Command::new("git")`.
  - Assumes `git` exists on `$PATH`. On Termux, `git` is installed via `pkg install git`.

### 1.5 Optional Search Tools (`bfs` & `ugrep`)
- In `crates/codegen/xai-grok-tools/src/computer/local/embedded_search_tools.rs`:
  - Lines 122–128:
    ```rust
    fn resolved_tools() -> &'static ResolvedTools {
        static TOOLS: OnceLock<ResolvedTools> = OnceLock::new();
        TOOLS.get_or_init(|| ResolvedTools {
            bfs: resolve_tool("bfs", "GROK_TOOLS_BFS_PATH", bundled_bfs()),
            ugrep: resolve_tool("ugrep", "GROK_TOOLS_UGREP_PATH", bundled_ugrep()),
        })
    }
    ```
  - Lines 223–241: `resolve_tool_from(...)` checks `env_path`, `bundled`, `~/.grok/vendor/<name>`, and `which::which(bin_name)`.
  - Lines 297–310: Generated shadow function:
    ```sh
    unalias {name} 2>/dev/null || true;
    {name}() {
      local __grok_bin={qpref};
      [ -x "$__grok_bin" ] || __grok_bin=$(command -v {bin_name} 2>/dev/null) || __grok_bin='';
      if [ -z "$__grok_bin" ]; then command {name} "$@"; return; fi;
      if [[ -z ${ZSH_VERSION-} ]] && (( BASH_SUBSHELL > 0 )); then
        exec -a {name} "$__grok_bin" {prepend}"$@";
      else
        (exec -a {name} "$__grok_bin" {prepend}"$@");
      fi;
    };
    __grok_shadow_{name}=1
    ```
  - **Graceful Degradation Mechanism**: If `bfs` or `ugrep` is absent or not executable, the shadow function immediately falls back to `command find "$@"` or `command grep "$@"`. This provides an existing reference pattern for graceful fallback.

### 1.6 E2E Test Suite Alignment
- In `tests/e2e/harness/termux_sim.py`:
  - Lines 269–285: `ToolResolverSeam` tests tool resolution against `$PATH` and `$PREFIX/bin`, raising `ToolResolutionError` with `"In Termux, run: pkg install {name}"` on missing tool.
  - Lines 341–380: `DoctorDiagnosticsSeam` verifies `grok doctor` reports tool installation status and remediation commands for `rg`, `fd`, `git`, `bash`.
- In `tests/e2e/tier1_features/test_feature_01_to_08.py` (Feature 8):
  - `test_f08_c01_resolves_ripgrep_from_termux_path`
  - `test_f08_c02_resolves_fd_from_termux_path`
  - `test_f08_c03_resolves_git_from_termux_path`
  - `test_f08_c04_resolves_bash_from_termux_path`
  - `test_f08_c05_missing_tool_suggests_pkg_install`
- In `tests/e2e/tier1_features/test_feature_09_to_16.py` (Feature 9):
  - `test_f09_c01_uses_bfs_when_present`
  - `test_f09_c02_falls_back_to_fd_when_bfs_missing`
  - `test_f09_c03_uses_ugrep_when_present`
  - `test_f09_c04_falls_back_to_rg_when_ugrep_missing`
  - `test_f09_c05_missing_optional_tools_do_not_halt_execution`

---

## 2. Logic Chain

```
[Observation 1.1: build.rs fails on android target & glibc binary incompatible with Bionic]
    │
    ▼
(Step 1: Gate out auto-bundling on Android target in build.rs)
    │
    ▼
[Observation 1.3: Termux lacks /bin/bash; binaries live in $PREFIX/bin and /system/bin]
    │
    ▼
(Step 2: Add dynamic $PREFIX/bin and /system/bin into unix shell & tool resolution cascades)
    │
    ▼
[Observation 1.2 & 1.4: Missing required tools (rg, fd, git, bash) fail with raw ENOENT]
    │
    ▼
(Step 3: Introduce centralized ToolResolver with platform-specific package mapping & actionable remediation hints)
    │
    ▼
[Observation 1.5: bfs & ugrep have self-resolving shadow functions falling back to system find/grep]
    │
    ▼
(Step 4: Formalize graceful degradation for optional search tools — no hard errors when absent)
    │
    ▼
(Step 5: Unified integration with grok doctor diagnostics & E2E contracts)
```

### Logical Steps:

1. **Compile-Time Build Gate**: Because Android Bionic cannot execute precompiled glibc ELF binaries, and Termux provides native Bionic packages for ripgrep and fd, `build.rs` in `xai-grok-tools` and `xai-grok-shell` must skip binary downloads when `target_os == "android"`.
2. **Path Resolution Hierarchy**: Resolution must probe in order:
   - Level 1: Explicit environment variable override (e.g. `RG_BIN_PATH`, `GROK_SHELL`, `GROK_TOOLS_BFS_PATH`).
   - Level 2: Standard `$PATH` via `which::which(name)`.
   - Level 3: Dynamic Termux binary directory (`PlatformCapabilities::current().bin_dir()` -> `$PREFIX/bin/<name>`).
   - Level 4: Android system fallback (`/system/bin/<name>`).
   - Level 5: Standard Unix fallback directories (`/usr/bin`, `/bin`, `/usr/local/bin`, `/opt/homebrew/bin`).
3. **Package Remediation Mapping**:
   - `rg` $\rightarrow$ Termux: `pkg install ripgrep` | Debian: `apt install ripgrep` | macOS: `brew install ripgrep`
   - `fd` $\rightarrow$ Termux: `pkg install fd` | Debian: `apt install fd-find` | macOS: `brew install fd`
   - `git` $\rightarrow$ Termux: `pkg install git` | Debian: `apt install git` | macOS: `brew install git`
   - `bash` $\rightarrow$ Termux: `pkg install bash` | Debian: `apt install bash` | macOS: `brew install bash`
   - `bfs` $\rightarrow$ Termux: `pkg install bfs` (optional)
   - `ugrep` $\rightarrow$ Termux: `pkg install ugrep` (optional)
4. **Graceful Degradation for Optional Tools**:
   - `bfs`: If absent, search functionality transparently falls back to `find` (POSIX) or `fd`.
   - `ugrep`: If absent, grep functionality transparently falls back to `grep` (POSIX) or `rg`.
   - Optional tools must never trigger hard runtime errors or block turn execution.

---

## 3. Caveats

1. **Custom / Multi-User Termux Prefixes**: Termux can be installed under custom paths (e.g. secondary users or forks). Dynamic `$PREFIX` discovery (from Milestone 1) ensures the resolver uses the live prefix rather than hardcoding `/data/data/com.termux/files/usr`.
2. **Debian vs Termux `fd` Package Name Discrepancy**: In Termux, the package is `fd` and binary is `fd`. In Ubuntu/Debian, the package is `fd-find` and binary is `fdfind`. The remediation mapper must account for the platform.
3. **Subprocess Environment Sanitization**: If a tool or subagent runs with a restricted or stripped environment (e.g. empty `PATH`), the resolver's Level 3 fallback (`$PREFIX/bin`) guarantees resolution succeeds without relying exclusively on inherited environment variables.

---

## 4. Conclusion & Concrete Implementation Strategy

### 4.1 Implementation Design

#### 1. `build.rs` Target Gating (in `xai-grok-tools` and `xai-grok-shell`)
Add `target_os == "android"` to the bypass condition alongside Windows:
```rust
let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
if (target_os == "windows" || target_os == "android") && path_override.is_none() {
    return Ok(());
}
```

#### 2. Unix Shell Path Cascade in `xai-grok-config/src/shell.rs`
Update `resolve_unix_shell_path` to include Termux `$PREFIX/bin`:
```rust
#[cfg(unix)]
fn resolve_unix_shell_path(kind: UnixShellKind) -> String {
    let name = kind.name();
    let matches_kind = |p: &std::path::Path| p.file_name().and_then(|n| n.to_str()) == Some(name);

    // 1) Explicit override via $GROK_SHELL
    if let Ok(s) = std::env::var("GROK_SHELL") {
        let p = std::path::PathBuf::from(&s);
        if matches_kind(&p) && is_executable(&p) {
            return s;
        }
    }

    // 2) $SHELL
    if let Ok(s) = std::env::var("SHELL") {
        let p = std::path::PathBuf::from(&s);
        if matches_kind(&p) && is_executable(&p) {
            return s;
        }
    }

    // 3) `which` walks $PATH
    if let Ok(p) = which::which(name) && is_executable(&p) {
        return p.to_string_lossy().into_owned();
    }

    // 4) Termux $PREFIX/bin and Android /system/bin
    if let Ok(pfx) = std::env::var("PREFIX") {
        let p = std::path::PathBuf::from(pfx).join("bin").join(name);
        if is_executable(&p) {
            return p.to_string_lossy().into_owned();
        }
    }
    let android_candidates = ["/data/data/com.termux/files/usr/bin", "/system/bin", "/system/xbin"];
    for dir in android_candidates {
        let p = std::path::PathBuf::from(dir).join(name);
        if is_executable(&p) {
            return p.to_string_lossy().into_owned();
        }
    }

    // 5) Standard Desktop Unix candidate dirs
    for dir in ["/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"] {
        let p = std::path::PathBuf::from(dir).join(name);
        if is_executable(&p) {
            return p.to_string_lossy().into_owned();
        }
    }

    // 6) Fallback default
    kind.hardcoded_default().to_string()
}
```

#### 3. Centralized `ToolResolver` in `crates/codegen/xai-grok-tools/src/resolver.rs`
```rust
//! Native tool resolution and actionable remediation hints.

use std::path::{Path, PathBuf};
use thiserror::Error;
use xai_grok_config::platform::PlatformCapabilities;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolRequirement {
    Required,
    Optional,
}

#[derive(Debug, Clone)]
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
        for sys_dir in ["/data/data/com.termux/files/usr/bin", "/system/bin", "/system/xbin"] {
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
}
```

#### 4. Ripgrep & Grep Integration
In `crates/codegen/xai-grok-tools/src/implementations/grok_build/grep/ripgrep.rs`:
```rust
pub fn rg_path() -> PathBuf {
    static RG_EXEC: OnceLock<PathBuf> = OnceLock::new();
    RG_EXEC.get_or_init(|| {
        ToolResolver::resolve(&TOOL_RG).unwrap_or_else(|_| PathBuf::from("rg"))
    }).clone()
}
```
And in `prepare_grep` (`grep/mod.rs`):
```rust
let rg_exec = rg_path();
let mut cmd = Command::new(&rg_exec);
...
let mut child = match cmd.spawn() {
    Ok(c) => c,
    Err(e) => {
        let hint = if e.kind() == std::io::ErrorKind::NotFound {
            format!("\n{}", ToolResolver::remediation_hint(&TOOL_RG))
        } else {
            String::new()
        };
        return Ok(GrepStep::Early(GrepSearchOutput {
            stdout: Vec::new(),
            stderr: format!("Failed to spawn ripgrep ({rg_exec:?}): {e}.{hint}").into_bytes(),
            exit_code: -1,
            match_count: 0,
            file_matches: Vec::new(),
        }));
    }
};
```

---

## 5. Verification Method

### 5.1 Automated E2E Test Suite Execution
Execute the 4-tier test runner:
```bash
python3 tests/e2e/runner.py
```
**Expected**: 366/366 tests pass in <10s (Tier 1: 160, Tier 2: 160, Tier 3: 34, Tier 4: 12).

### 5.2 Specific Feature Test Verifications
```bash
python3 -m unittest tests/e2e/tier1_features/test_feature_01_to_08.py -k test_f08
python3 -m unittest tests/e2e/tier1_features/test_feature_09_to_16.py -k test_f09
python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_01_to_08.py -k test_b08
python3 -m unittest tests/e2e/tier4_real_world/test_scenario_doctor.py
```

### 5.3 Invalidation Conditions
- Any hardcoded `/bin/bash` or `/usr/bin` in non-fallback paths.
- `build.rs` failing when `CARGO_CFG_TARGET_OS=android`.
- Missing tool errors failing to display `pkg install <pkg>` remediation.
- Missing optional tools (`bfs`, `ugrep`) panicking or raising fatal errors instead of degrading gracefully.
