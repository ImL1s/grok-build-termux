# Milestone 5 — Feature 29 (`grok doctor` & Environment Diagnostics) Investigation Report

**Agent**: `explorer_m5_2`  
**Date**: 2026-08-15  
**Target Milestone**: Milestone 5 (`M5`: Distribution, Diagnostics & Upstream Sync)  
**Target Feature**: Feature 29 (`grok doctor` for Android/Termux)  
**Reference Baseline**: `xai-org/grok-build@eb267feff13129e568df38fb6fdf0ceb65f735d6` targeting `aarch64-linux-android`

---

## 1. Observation

### 1.1 Existing Codebase & Crate Distribution

1. **`crates/codegen/xai-grok-pager/` (Diagnostics & Doctor Dispatch)**:
   - `src/doctor_cmd/mod.rs` (lines 13–66): Implements `DoctorArgs { json: bool, command: Option<DoctorCommand> }` and `run(args: DoctorArgs)`. `collect_report()` gathers standalone facts from `diagnostics::probes::collect_standalone(&terminal)`.
   - `src/doctor_cmd/json.rs` (lines 14–48): Implements JSON serialization `write(report: &DiagnosticReport, writer)` conforming to `SCHEMA_VERSION = "1"`.
   - `src/doctor_cmd/human.rs` (lines 10–184): Implements human-readable terminal formatter `format(report: &DiagnosticReport) -> String` printing `Environment`, `Clipboard`, `Voice`, `Findings`, and `Checks not completed`.
   - `src/diagnostics/model.rs` (lines 35–45, 85–100): Defines `DiagnosticReport`, `DiagnosticFacts`, `DiagnosticFinding`, `DiagnosticId`, `FindingDisposition`, and `ProbeNote`.
   - `src/diagnostics/doctor_format.rs` (lines 9–140): Implements in-TUI `/doctor` slash command formatter.

2. **`crates/codegen/xai-grok-config/` (Platform & Storage Boundaries)**:
   - `src/platform.rs` (lines 8–21, 34–56, 163–276): Defines `PlatformKind` (`AndroidTermux`, `UnsupportedAndroid`, `DesktopLinux`, `MacOS`, `Windows`), `SandboxKind` (`KernelEnforced`, `PolicyOnly`, `Disabled`), and `PlatformCapabilities`.
   - `src/platform.rs` (lines 304–335): Implements `prefix_dir()` (returning `$PREFIX` on Android or `/usr` on desktop Linux), `bin_dir()`, `system_config_dir()` (`$PREFIX/etc/grok` on Termux, `/etc/grok` on Linux/macOS).
   - `src/platform.rs` (lines 468–587): Implements `validate_storage_safety(path: &Path)` rejecting Android shared storage (`/sdcard`, `/storage/emulated/0`, `/mnt/sdcard`) across lexical normalization, symlink resolution, and canonicalization.

3. **`crates/codegen/xai-grok-tools/` (Native Tool Resolution)**:
   - `src/resolver.rs` (lines 18–80): Defines `ToolSpec`, `ToolRequirement` (`Required`, `Optional`), `TOOL_RG`, `TOOL_FD`, `TOOL_GIT`, `TOOL_BASH`, `TOOL_BFS`, `TOOL_UGREP`.
   - `src/resolver.rs` (lines 95–189): Implements `ToolResolver::resolve(spec)` traversing: (1) environment override, (2) `$PATH`, (3) `$PREFIX/bin`, (4) Android system fallback directories (`/data/data/com.termux/files/usr/bin`, `/system/bin`), and (5) Unix fallbacks. Implements `remediation_hint(spec)` generating `In Termux, run: pkg install <pkg>`.

4. **`crates/codegen/xai-grok-shared/` & `xai-system-power/` (Clipboard & Power)**:
   - `crates/codegen/xai-grok-shared/src/clipboard.rs` (lines 2810–2885): Implements `termux-clipboard-get` and `termux-clipboard-set` with graceful fallback to ANSI OSC 52 escape sequences.
   - `crates/codegen/xai-system-power/src/android.rs` (lines 20–57): Implements `hold_awake()` acquiring wake lock via `termux-wake-lock` and releasing on drop via `termux-wake-unlock`.

5. **`scripts/validate_elf.py` (Bionic & 16 KiB Page Alignment Validation)**:
   - Lines 85–108: Validates Bionic dynamic linkers (`/system/bin/linker64`, `/system/bin/linker`) and rejects desktop glibc linkers and `libc.so.6`.
   - Lines 371–394: Validates that all `PT_LOAD` segments satisfy `p_align >= 16384` (16 KiB) and congruence `p_vaddr % p_align == p_offset % p_align`.

6. **`tests/e2e/` (4-Tier E2E Test Suite & Doctor Seam Expectations)**:
   - `tests/e2e/harness/termux_sim.py` (lines 359–407): Implements `DoctorDiagnosticsSeam::run_diagnostics()` checking `platform`, `prefix`, `prefix_valid`, `home`, `storage_safe`, `sandbox_kind`, `tools`, `issues`, and `remediations`.
   - `tests/e2e/tier4_real_world/test_scenario_doctor.py` (lines 28–86): Tests both full healthy `grok doctor` run and missing package remediation scenario.
   - `tests/e2e/tier1_features/test_feature_25_to_32.py` (lines 245–304): Tests Feature 29 execution, missing tools, remediation instructions, storage violation detection, and JSON output mode.
   - `tests/e2e/tier2_boundaries/test_boundaries_25_to_32.py` (lines 208–254): Tests Feature 29 boundary cases (all tools missing, desktop mode, JSON schema keys, non-empty remediation strings).

---

## 2. Logic Chain

### 2.1 Diagnostic Checks Tailored for Android/Termux

```
                        ┌────────────────────────────────────────────────────────┐
                        │              `grok doctor` Entry Point                 │
                        └───────────────────────────┬────────────────────────────┘
                                                    │
             ┌──────────────────────────────────────┴──────────────────────────────────────┐
             ▼                                                                             ▼
┌─────────────────────────┐                                                   ┌─────────────────────────┐
│   Platform Environment  │                                                   │     Execution Health    │
├─────────────────────────┤                                                   ├─────────────────────────┤
│ 1. Termux $PREFIX Check │                                                   │ 4. CLI Tools Resolution │
│ 2. Bionic Linker Check  │                                                   │ 7. Bionic DNS & TLS     │
│ 3. 16 KiB Page Alignment│                                                   │ 8. Termux:API & Power   │
│ 5. Truthful Sandbox     │                                                   └─────────────────────────┘
│ 6. Storage Safety Guard │
└─────────────────────────┘
```

#### Check 1: Termux Environment & `$PREFIX` Presence/Validity
- **Observation**: Android apps run in isolated UID sandboxes where standard Unix `/usr`, `/etc`, and `/bin` do not exist. Termux mounts its userland in `/data/data/com.termux/files/usr`.
- **Inference**: On Android (`PlatformCapabilities::current().is_android()`), `grok` must check `$PREFIX`:
  1. `PREFIX` environment variable must be set and non-empty.
  2. The target path must exist on disk and be a directory (`is_dir()`).
  3. Crucial subdirectories must exist: `$PREFIX/bin`, `$PREFIX/etc`, `$PREFIX/lib`, and `$PREFIX/tmp` (or `$TMPDIR`).
  4. `$TERMUX_VERSION` and package manager (`pkg`, `apt`) availability should be probed.
  5. If `$PREFIX` is unset or invalid on Android, report `FindingDisposition::Issue` with remediation: `Launch Grok inside Termux, or set PREFIX to your Termux usr directory.`

#### Check 2: Architecture & Bionic Dynamic Linker Check
- **Observation**: Binaries running on Android must use the Android Bionic dynamic linker (`/system/bin/linker64` for 64-bit `aarch64`/`x86_64`, `/system/bin/linker` for 32-bit `arm`/`i686`). Glibc dynamic loaders (`/lib/ld-linux-*.so`) are completely incompatible.
- **Inference**:
  1. Detect CPU architecture (`aarch64`, `x86_64`, etc.).
  2. Verify `/system/bin/linker64` (or `/system/bin/linker`) exists and is executable.
  3. Inspect the running binary's ELF interpreter header (`PT_INTERP` from `/proc/self/exe` or embedded metadata).
  4. Ensure no glibc dependencies (`libc.so.6`, `libpthread.so.0`) are mapped in `/proc/self/maps`.
  5. Report facts: `arch: "aarch64"`, `linker: "/system/bin/linker64"`, `libc: "Bionic"`.

#### Check 3: 16 KiB ELF Page Size Compatibility Check (Android 15+ Readiness)
- **Observation**: Android 15+ devices enforce or support 16 KiB physical memory pages (`PAGE_SIZE = 16384`). ELF binaries built with 4 KiB segment alignment fail to load or crash on memory mapping.
- **Inference**:
  1. Probe runtime page size via `unsafe { libc::sysconf(libc::_SC_PAGESIZE) }` (or `getpagesize()`).
  2. Parse `/proc/self/exe` ELF program headers: verify all `PT_LOAD` segments have `p_align >= 16384` and `p_vaddr % p_align == p_offset % p_align`.
  3. Findings:
     - If runtime page size is 16 KiB and binary is 16 KiB aligned: `16 KiB native (Android 15+ ready)`.
     - If runtime page size is 4 KiB and binary is 16 KiB aligned: `4 KiB runtime (16 KiB forward-compatible)`.
     - If binary has `p_align < 16384`: report `FindingDisposition::Issue`: `Binary has 4 KiB ELF page alignment. It will fail on Android 15+ devices configured with 16 KiB pages.` Remediation: `Rebuild with -Wl,-z,max-page-size=16384.`

#### Check 4: Essential CLI Packages Check
- **Observation**: Upstream Grok downloads desktop x86_64/arm64 Linux binaries for `rg` and `fd`. In Termux, native CLI tools must be resolved from Termux packages on `$PATH`.
- **Inference**:
  1. Probe required tools: `git`, `rg` (ripgrep), `fd` (fd-find), `bash`.
  2. Probe optional search accelerator tools: `bfs`, `ugrep`.
  3. Use `xai_grok_tools::resolver::ToolResolver::resolve(&spec)`.
  4. For each installed tool, execute `<tool> --version` with a 500ms timeout to verify executability and extract version string.
  5. For missing required tools: emit `FindingDisposition::Issue` with remediation `In Termux, run: pkg install <pkg>`.
  6. For missing optional tools: emit `FindingDisposition::Recommendation` (or informational status).

#### Check 5: Truthful Sandbox Reporting (`policy-only`)
- **Observation**: Linux desktop Grok uses Landlock/seccomp kernel sandboxing; macOS uses Seatbelt. Android SELinux and unprivileged user policies block Landlock and namespace unsharing.
- **Inference**:
  1. Query `PlatformCapabilities::current().sandbox_kind()`.
  2. On Android/Termux, report `SandboxKind::PolicyOnly` (`"policy-only"`).
  3. Diagnostic description: `policy-only (in-process path allowlist & hook barriers; kernel isolation unavailable under Android SELinux)`.
  4. Never report `kernel-enforced` or mask degraded capability.

#### Check 6: Storage Safety Status (`GROK_HOME` Quarantine Guard)
- **Observation**: Android shared storage (`/sdcard`, `/storage/emulated/0`) lacks POSIX DAC permissions (`0700` is impossible; files are world-readable across all apps with storage access).
- **Inference**:
  1. Probe `PlatformCapabilities::current().home_dir()`.
  2. Check `$HOME/.grok` and `$GROK_HOME`.
  3. Invoke `validate_storage_safety(path)`.
  4. Verify private storage directory permissions (`0700` for `~/.grok`, `0600` for `credentials.json`).
  5. If `GROK_HOME` is situated on `/sdcard` or a symlink resolves to `/sdcard`: emit `FindingDisposition::Issue`: `Storage safety violation: GROK_HOME cannot reside on Android shared storage (<path>). Android shared storage lacks POSIX permissions.` Remediation: `Unset GROK_HOME or point it to private app storage ($HOME/.grok).`

#### Check 7: DNS Resolution & Network Reachability via Bionic `getaddrinfo`
- **Observation**: Android has no `/etc/resolv.conf`. Pure Rust DNS resolvers that parse `/etc/resolv.conf` fail on Android. Android DNS must go through Bionic libc's `getaddrinfo()` (communicating with `netd` over `/dev/socket/dnsproxyd`).
- **Inference**:
  1. Test DNS resolution for `api.x.ai:443`, `auth.x.ai:443`, `github.com:443` using `std::net::ToSocketAddrs` (which calls Bionic `getaddrinfo`).
  2. Measure lookup latency in milliseconds.
  3. Validate TLS certificate chain verification (using `rustls` with webpki-roots or native Android root certs).
  4. If resolution fails: emit `FindingDisposition::Issue`: `DNS resolution failed: <error>. Check Termux internet connection.`

#### Check 8: Termux:API Presence (Clipboard & Wake Lock)
- **Observation**: Termux clipboard and wake lock require the `termux-api` package and the `com.termux.api` Android companion app. If absent, fallback mechanisms (OSC 52 clipboard) must be used.
- **Inference**:
  1. Check CLI presence: `termux-clipboard-get`, `termux-clipboard-set`, `termux-wake-lock`, `termux-wake-unlock`, `termux-open-url`.
  2. Test IPC responsiveness by executing `termux-clipboard-get` with a 300ms timeout.
  3. Classify state:
     - `Active & Responsive`: CLI tools present and companion app responding.
     - `CLI Installed, App Unresponsive`: CLI tools present, but IPC timed out (companion app missing or background restricted).
     - `Not Installed`: CLI tools missing; fallback to ANSI OSC 52 clipboard.
  4. If missing: emit `FindingDisposition::Recommendation`: `Termux:API is not installed. System clipboard and background wake lock are limited.` Remediation: `In Termux, run: pkg install termux-api and install Termux:API from F-Droid.`

---

### 2.2 Output Format Architecture

#### 1. JSON Output Architecture (`grok doctor --json`)
The JSON structure must provide complete backwards compatibility with upstream schema while embedding the new platform diagnostics:

```json
{
  "schemaVersion": "1",
  "platform": "Android/Termux",
  "prefix": "/data/data/com.termux/files/usr",
  "prefix_valid": true,
  "home": "/data/data/com.termux/files/home/.grok",
  "storage_safe": true,
  "sandbox_kind": "policy-only",
  "environment": {
    "arch": "aarch64",
    "bionicLinker": "/system/bin/linker64",
    "pageSize": 16384,
    "pageSize16kCompatible": true,
    "termuxVersion": "0.118.1"
  },
  "tools": {
    "rg": { "installed": true, "path": "/data/data/com.termux/files/usr/bin/rg", "version": "ripgrep 14.1.0" },
    "fd": { "installed": true, "path": "/data/data/com.termux/files/usr/bin/fd", "version": "fd 9.0.0" },
    "git": { "installed": true, "path": "/data/data/com.termux/files/usr/bin/git", "version": "git version 2.45.0" },
    "bash": { "installed": true, "path": "/data/data/com.termux/files/usr/bin/bash", "version": "GNU bash 5.2.26" },
    "bfs": { "installed": false, "path": null, "optional": true },
    "ugrep": { "installed": false, "path": null, "optional": true }
  },
  "network": {
    "dnsResolution": "bionic_getaddrinfo",
    "dnsStatus": "ok",
    "latencyMs": 24,
    "apiReachability": "reachable"
  },
  "termuxApi": {
    "cliInstalled": true,
    "appResponsive": true,
    "clipboardRoute": "termux-api",
    "osc52Fallback": true,
    "wakeLockAvailable": true
  },
  "issues": [],
  "remediations": [],
  "counts": {
    "issues": 0,
    "recommendations": 0,
    "probeNotes": 0
  }
}
```

#### 2. Human-Readable CLI/TUI Output Format (`grok doctor`)

```text
Grok Doctor (Android/Termux aarch64)

Environment
  · platform                     Android/Termux (Termux 0.118.1)
  · prefix                       /data/data/com.termux/files/usr (valid)
  · storage                      /data/data/com.termux/files/home/.grok (private, safe)
  · bionic linker                /system/bin/linker64 (Bionic libc)
  · memory page size             16 KiB (Android 15+ compatible)
  · sandbox                      policy-only (in-process path enforcement)
  · terminal                     xterm-256color
  · color                        truecolor
  · themes                       all

CLI Tools
  · git                          /data/data/com.termux/files/usr/bin/git (2.45.0)
  · ripgrep (rg)                 /data/data/com.termux/files/usr/bin/rg (14.1.0)
  · fd                           /data/data/com.termux/files/usr/bin/fd (9.0.0)
  · bash                         /data/data/com.termux/files/usr/bin/bash (5.2.26)
  ? bfs (optional)               not found (run: pkg install bfs)
  ? ugrep (optional)             not found (run: pkg install ugrep)

Network & Connectivity
  · DNS resolution               Bionic getaddrinfo (ok, 24ms)
  · xAI API reachability         reachable (api.x.ai)
  · TLS certificates             valid (webpki-roots)

Termux:API & Power
  · termux-api package           installed (/data/data/com.termux/files/usr/bin/termux-api)
  · clipboard backend            termux-clipboard (active)
  · fallback clipboard           OSC 52 (supported)
  · wake lock                    termux-wake-lock (available)

No issues found.
```

---

## 3. Caveats

1. **Subprocess Timeout Discipline**:
   - `termux-api` commands communicate with the Android background service via broadcast intents. If the `Termux:API` app is battery-optimized or killed by Android OS, subprocesses like `termux-clipboard-get` can hang indefinitely.
   - **Mitigation**: All subprocess probes in `grok doctor` must execute with strict timeouts (e.g. 300ms for Termux:API, 500ms for CLI version probes) using non-blocking child polling or timeout wrappers.

2. **Passive vs Active Network Probing**:
   - `grok doctor` may be run in offline environments (airplane mode, isolated development).
   - **Mitigation**: DNS and network probes must be bounded (timeout: 1000ms) and must categorize offline errors gracefully as `network.offline` rather than panicking or failing other independent local checks.

3. **PRoot / Chroot Environments**:
   - In PRoot or chroot environments under Termux, `$PREFIX` might point to a synthetic Linux rootfs (`/data/data/com.termux/files/usr/var/lib/proot-distro/...`).
   - **Mitigation**: Doctor should inspect whether standard Termux `$PREFIX` exists vs PRoot paths, and report accordingly.

4. **Android 15 16 KiB Page Size Emulation vs Real Hardware**:
   - Some emulators simulate 16 KiB pages via software, while hardware runs 16 KiB native kernels.
   - **Mitigation**: Doctor reads both the runtime page size from Bionic kernel API (`sysconf(_SC_PAGESIZE)`) and inspects the binary's ELF load segment headers (`p_align`).

---

## 4. Conclusion & Implementation Recommendations

### 4.1 Crate Distribution & Implementation Blueprint

```
crates/codegen/
├── xai-grok-config/
│   └── src/platform.rs             # Exposes PlatformDiagnosticsFacts & probe_platform_health()
├── xai-grok-tools/
│   └── src/resolver.rs             # Exposes ToolResolver::diagnose_all_tools()
└── xai-grok-pager/
    ├── src/diagnostics/
    │   ├── model.rs                # Extends DiagnosticFacts with Platform & Tool probe facts
    │   ├── probes/
    │   │   ├── mod.rs              # Probes platform, ELF, Bionic DNS, Termux:API
    │   │   └── android.rs          # Dedicated Android/Termux probe implementations
    │   └── doctor_format.rs        # In-TUI doctor formatting with Android sections
    └── src/doctor_cmd/
        ├── mod.rs                  # CLI entry point collecting all 8 diagnostic checks
        ├── json.rs                 # Complete JSON schema serialization
        └── human.rs                # TUI/CLI table formatter
```

### 4.2 Proposed Rust Data Structures & Implementation Snippets

#### 1. Platform Diagnostic Facts (`xai-grok-config::platform`)

```rust
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct PlatformDiagnosticsFacts {
    pub platform_name: &'static str,
    pub is_android_termux: bool,
    pub prefix_path: Option<PathBuf>,
    pub prefix_valid: bool,
    pub home_path: Option<PathBuf>,
    pub storage_safe: bool,
    pub sandbox_kind: SandboxKind,
    pub arch: &'static str,
    pub page_size: usize,
    pub is_16k_page_compatible: bool,
    pub bionic_linker: Option<PathBuf>,
    pub termux_version: Option<String>,
}

impl PlatformCapabilities {
    pub fn diagnose_platform(&self) -> PlatformDiagnosticsFacts {
        let is_termux = self.is_android_termux();
        let prefix = self.prefix_dir().ok().map(|p| p.to_path_buf());
        let prefix_valid = prefix.as_ref().map(|p| p.is_dir()).unwrap_or(false);
        let home = self.home_dir().ok();
        let storage_safe = home.as_ref().map(|p| validate_storage_safety(p).is_ok()).unwrap_or(false);
        
        let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) as usize };
        let is_16k_page_compatible = page_size >= 16384 || self.verify_self_elf_alignment();
        
        let bionic_linker = if self.is_android() {
            if Path::new("/system/bin/linker64").exists() {
                Some(PathBuf::from("/system/bin/linker64"))
            } else if Path::new("/system/bin/linker").exists() {
                Some(PathBuf::from("/system/bin/linker"))
            } else {
                None
            }
        } else {
            None
        };

        PlatformDiagnosticsFacts {
            platform_name: if is_termux { "Android/Termux" } else { "Desktop Linux/macOS" },
            is_android_termux: is_termux,
            prefix_path: prefix,
            prefix_valid,
            home_path: home,
            storage_safe,
            sandbox_kind: self.sandbox_kind(),
            arch: std::env::consts::ARCH,
            page_size,
            is_16k_page_compatible,
            bionic_linker,
            termux_version: std::env::var("TERMUX_VERSION").ok(),
        }
    }

    fn verify_self_elf_alignment(&self) -> bool {
        // Inspect /proc/self/exe program headers for p_align >= 0x4000
        if let Ok(exe_bytes) = std::fs::read("/proc/self/exe") {
            if exe_bytes.len() > 64 && &exe_bytes[0..4] == b"\x7fELF" {
                // Parse ELF 64-bit header
                let is_64 = exe_bytes[4] == 2;
                if is_64 && exe_bytes.len() >= 64 {
                    let phoff = u64::from_le_bytes(exe_bytes[32..40].try_into().unwrap_or_default()) as usize;
                    let phentsize = u16::from_le_bytes(exe_bytes[54..56].try_into().unwrap_or_default()) as usize;
                    let phnum = u16::from_le_bytes(exe_bytes[56..58].try_into().unwrap_or_default()) as usize;
                    for i in 0..phnum {
                        let offset = phoff + i * phentsize;
                        if offset + phentsize <= exe_bytes.len() {
                            let p_type = u32::from_le_bytes(exe_bytes[offset..offset+4].try_into().unwrap_or_default());
                            if p_type == 1 /* PT_LOAD */ {
                                let p_align = u64::from_le_bytes(exe_bytes[offset+48..offset+56].try_into().unwrap_or_default());
                                if p_align < 16384 {
                                    return false;
                                }
                            }
                        }
                    }
                    return true;
                }
            }
        }
        true
    }
}
```

#### 2. Tool Resolution Diagnostics (`xai-grok-tools::resolver`)

```rust
#[derive(Debug, Clone, serde::Serialize)]
pub struct ToolDiagnosticStatus {
    pub name: &'static str,
    pub installed: bool,
    pub path: Option<PathBuf>,
    pub version: Option<String>,
    pub optional: bool,
    pub remediation: String,
}

impl ToolResolver {
    pub fn diagnose_all_tools() -> Vec<ToolDiagnosticStatus> {
        let specs = [&TOOL_RG, &TOOL_FD, &TOOL_GIT, &TOOL_BASH, &TOOL_BFS, &TOOL_UGREP];
        specs.into_iter().map(|spec| {
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
                }
            }
        }).collect()
    }
}

fn probe_tool_version(path: &Path) -> Option<String> {
    use std::process::Command;
    let out = Command::new(path).arg("--version").output().ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    stdout.lines().next().map(|l| l.trim().to_string())
}
```

#### 3. Complete Diagnostic Collector (`xai-grok-pager::doctor_cmd`)

```rust
pub fn collect_android_termux_report() -> DiagnosticReport {
    let caps = PlatformCapabilities::current();
    let platform_facts = caps.diagnose_platform();
    let tool_statuses = ToolResolver::diagnose_all_tools();
    
    let mut findings = Vec::new();
    
    // Check 1: Prefix
    if caps.is_android() && !platform_facts.prefix_valid {
        findings.push(DiagnosticFinding {
            id: DiagnosticId::new("platform", "invalid-prefix"),
            disposition: FindingDisposition::Issue,
            message: "Termux $PREFIX is unset or missing required directories.".to_string(),
            remediation: Some(ManualRemediation {
                fix: "Launch Grok inside Termux, or set PREFIX=/data/data/com.termux/files/usr".to_string(),
                config_path: None,
            }),
            automatic_remediation: None,
            note: None,
        });
    }

    // Check 4: Missing Required Tools
    for tool in &tool_statuses {
        if !tool.installed && !tool.optional {
            findings.push(DiagnosticFinding {
                id: DiagnosticId::new("tools", tool.name),
                disposition: FindingDisposition::Issue,
                message: format!("Missing required tool: {}", tool.name),
                remediation: Some(ManualRemediation {
                    fix: tool.remediation.clone(),
                    config_path: None,
                }),
                automatic_remediation: None,
                note: None,
            });
        }
    }

    // Check 6: Storage Quarantine
    if !platform_facts.storage_safe {
        findings.push(DiagnosticFinding {
            id: DiagnosticId::new("storage", "quarantine-violation"),
            disposition: FindingDisposition::Issue,
            message: "GROK_HOME cannot reside on Android shared storage (/sdcard).".to_string(),
            remediation: Some(ManualRemediation {
                fix: "Unset GROK_HOME or point it to $HOME/.grok on private storage.".to_string(),
                config_path: None,
            }),
            automatic_remediation: None,
            note: Some("Android shared storage lacks POSIX permissions (0700) and is world-readable.".to_string()),
        });
    }

    // Build facts and return DiagnosticReport
    ...
}
```

---

## 5. Verification Method

To independently verify the `grok doctor` implementation for Android/Termux:

1. **Full 4-Tier E2E Test Suite**:
   ```bash
   python3 tests/e2e/runner.py
   ```
   *Expected outcome*: 366/366 tests pass across all 4 tiers (100% pass rate).

2. **Scenario 1 Real-World Doctor Verification**:
   ```bash
   python3 -m unittest tests/e2e/tier4_real_world/test_scenario_doctor.py
   ```
   *Expected outcome*: Both healthy run and missing tool remediation scenarios pass.

3. **Feature 29 Unit & Boundary Tests**:
   ```bash
   python3 -m unittest tests/e2e/tier1_features/test_feature_25_to_32.py
   python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_25_to_32.py
   ```

4. **Pairwise Cross-Feature Tests**:
   ```bash
   python3 -m unittest tests/e2e/tier3_cross_feature/test_cross_feature_pairwise.py
   ```
   *Expected outcome*: P14, P28, P32, and P34 test cases pass.

5. **ELF Binary & 16 KiB Page Size Alignment Validator**:
   ```bash
   python3 scripts/validate_elf.py --self-test
   ```
   *Expected outcome*: All self-tests pass for valid 16 KiB Bionic binaries and reject 4 KiB/glibc variants.

6. **Rust Cargo Tests (Affected Crates)**:
   ```bash
   cargo test -p xai-grok-config
   cargo test -p xai-grok-tools
   cargo test -p xai-grok-pager
   ```

---
*Report completed by `explorer_m5_2` for Milestone 5 Feature 29.*
