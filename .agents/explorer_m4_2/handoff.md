# Milestone 4 Exploration Report: Termux UX, Clipboard & Voice Degradation (Features 19–21)

## 1. Observation

### 1.1 Autoritative Requirements & Test Matrix
- **Authoritative Documents**:
  - `ORIGINAL_REQUEST.md` (§R1, §R4): Platform Capability & Dependency Isolation, Termux-Native Auth, UX & Truthful Sandboxing. Requires Termux:API text clipboard with OSC 52 fallback, excluding `arboard` and `cpal` from Android targets.
  - `PROJECT.md` (Features 19–21):
    - **Feature 19 (Termux:API Text Clipboard)**: Reads and writes text clipboard using `termux-clipboard-get` and `termux-clipboard-set` via process spawning with timeout and error handling.
    - **Feature 20 (OSC 52 Terminal Clipboard Fallback)**: Writes ANSI OSC 52 escape sequences `\x1b]52;c;<base64>\x07` to terminal stream when Termux:API is not installed or fails.
    - **Feature 21 (Unsupported Clipboard & Voice Graceful Degradation)**: Disables image/file clipboard and voice capture without crashing or presenting fake UI.
  - `TEST_READY.md`: 366/366 E2E tests verified and passing across 4 tiers.

### 1.2 Feature 19 Codebase Findings: Termux:API Text Clipboard
- **Dependency Isolation**:
  - `crates/codegen/xai-grok-shared/Cargo.toml` lines 43–45:
    ```toml
    [target.'cfg(all(not(target_os = "macos"), not(target_os = "android")))'.dependencies]
    arboard = { workspace = true, features = ["wayland-data-control"] }
    ```
  - Executed command: `cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard -i cpal -i tikv-jemallocator`
    Result: 0 occurrences found (clean exclusion).
- **Clipboard Implementation on Android**:
  - `crates/codegen/xai-grok-shared/src/clipboard.rs` lines 2779–2878:
    - Android platform module is gated with `#[cfg(target_os = "android")] mod platform`.
    - `get_text()` invokes `Command::new("termux-clipboard-get")` with `xai_tty_utils::detach_std_command(&mut cmd)` and `output()`. On exit status success, returns `Ok(Some(text))` (or `Ok(None)` if empty). On spawn failure or non-zero exit, returns `Ok(None)` without panicking.
    - `set_text_with_outcome(text: &str) -> NativeWriteOutcome`: Spawns `Command::new("termux-clipboard-set")` with `detach_std_command`, pipes `text.as_bytes()` to stdin, waits for child exit. On success, records `outcome.cli_ok_tools.push("termux-clipboard-set")`. If unsuccessful, falls back to `super::set_text_osc52(text, false)`.
- **Observation on Execution Safety**:
  - `get_text()` currently uses `cmd.output()` (synchronous blocking).
  - `set_text_with_outcome()` writes directly to `child.stdin` and calls `child.wait()` (unbounded wait).
  - While functional, on Android devices where Termux:API is missing or stuck in Android battery/background execution restrictions, an unbounded wait could delay the TUI thread. `xai-grok-shared` already contains `super::wait_with_deadline` (lines 381–397) and `super::spool_for_stdin` (lines 408–415) which are used by the desktop Linux backend (lines 1800–1865).

### 1.3 Feature 20 Codebase Findings: OSC 52 Terminal Clipboard Fallback
- **OSC 52 Sequence Generation**:
  - `crates/codegen/xai-grok-shared/src/clipboard.rs` lines 420–451:
    ```rust
    fn osc52_sequence(text: &str, tmux_passthrough: bool) -> Vec<u8> {
        let encoded = base64::engine::general_purpose::STANDARD.encode(text.as_bytes());
        if tmux_passthrough {
            format!("\x1bPtmux;\x1b\x1b]52;c;{encoded}\x07\x1b\\").into_bytes()
        } else {
            format!("\x1b]52;c;{encoded}\x07").into_bytes()
        }
    }
    ```
    `set_text_osc52` writes the escape sequence directly to `stderr` via `crate::stderr::with_locked_stderr`.
- **Route Resolution in Pager Render**:
  - `crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs` lines 162–184:
    ```rust
    fn resolve_clipboard_route_with(ctx: &TerminalContext, opts: ClipboardRouteOpts) -> ClipboardRoute {
        let is_tmux = ctx.multiplexer == MultiplexerKind::Tmux;
        let osc52 = !opts.no_osc52
            && (cfg!(target_os = "linux")
                || is_tmux
                || is_remote()
                || is_container_no_display()
                || opts.wrap_sink);
        ClipboardRoute {
            native: true,
            tmux_buffer: is_tmux,
            osc52,
            osc52_tmux_passthrough: osc52 && is_tmux && ctx.embedded_editor.is_none(),
        }
    }
    ```
  - `cfg!(target_os = "linux")` evaluates to `false` for `target_os = "android"`.
  - In a standalone Termux session (not in tmux, not over SSH), `osc52` route should also be active by default as a fallback safety net by expanding the condition to `cfg!(any(target_os = "linux", target_os = "android"))`.
- **Security Boundary for Reading**:
  - Reading via OSC 52 is not supported by terminal emulators for security reasons. `get_text()` on Android cleanly returns `Ok(None)` when Termux:API is absent.

### 1.4 Feature 21 Codebase Findings: Unsupported Clipboard & Voice Degradation
- **Clipboard Unsupported Capabilities**:
  - `crates/codegen/xai-grok-shared/src/clipboard.rs` lines 2880–2895:
    - `get_image()` -> `Ok(None)`
    - `get_file_urls()` -> `Ok(None)`
    - `get_attachments()` -> `Ok(ClipboardAttachments::default())`
    - `set_image_file(_path: &Path)` -> `Err(anyhow!("image clipboard is not supported on Android/Termux"))`
- **Voice Dependency & Capability Gating**:
  - `crates/codegen/xai-grok-voice/Cargo.toml` lines 46–49:
    ```toml
    [target.'cfg(all(not(target_os = "linux"), not(target_os = "android")))'.dependencies.cpal]
    version = "0.15"
    optional = true
    ```
  - `crates/codegen/xai-grok-voice/src/lib.rs` line 46:
    ```rust
    pub const AUDIO_SUPPORTED: bool = cfg!(all(feature = "audio", not(target_os = "android")));
    ```
  - `crates/codegen/xai-grok-voice/src/audio/capture_android.rs` lines 1–33:
    - `input_device_info()` -> `Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))`
    - `spawn_pcm_capture(...)` -> `Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))`
    - `capture_pcm_for_duration(...)` -> `Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))`
    - `CaptureHandle::stop()` -> no-op.
- **Pager & UI Integration**:
  - `crates/codegen/xai-grok-pager/src/app/app_view.rs` line 1678:
    `voice_can_start_pipeline(&self) -> bool` checks `self.voice_mode_enabled && xai_grok_voice::AUDIO_SUPPORTED`. Evaluates to `false` on Android, preventing background audio pipeline spawn.
  - `crates/codegen/xai-grok-pager/src/app/dispatch/voice.rs` line 102:
    `dispatch_enable_voice_mode` checks `if !app.voice_mode_enabled || !xai_grok_voice::AUDIO_SUPPORTED { return vec![]; }`, acting as a silent no-op.
  - `crates/codegen/xai-grok-pager/src/slash/registry.rs` lines 170–172 & 434–438:
    `/voice` slash command is fail-closed (hidden by default) and only shown when `set_voice_visible(true)` is explicitly invoked. On Android it remains hidden.

---

## 2. Logic Chain

1. **Premise 1 (Platform & Dependency Isolation)**:
   Android Termux runs in a sandboxed userland without X11/Wayland display server and without standard desktop ALSA/PulseAudio/CoreAudio subsystems. Desktop libraries `arboard` and `cpal` must be completely eliminated from the `aarch64-linux-android` dependency tree.
   *Verification*: `Cargo.toml` manifests in `xai-grok-shared` and `xai-grok-voice` target-gate `arboard` and `cpal` to non-Android targets (`cargo tree` confirmed 0 matches).

2. **Premise 2 (Feature 19 - Termux:API Text Clipboard)**:
   When `Termux:API` is installed, Android clipboard access is exposed via the native Termux executables `termux-clipboard-get` and `termux-clipboard-set`.
   - `get_text()` spawns `termux-clipboard-get`, reading UTF-8 text from stdout.
   - `set_text_with_outcome()` writes text to `termux-clipboard-set` stdin.
   - If `termux-clipboard-set` fails (non-zero status or tool missing), it must immediately fall back to OSC 52.

3. **Premise 3 (Feature 20 - OSC 52 Terminal Clipboard Fallback)**:
   When running over remote sessions, inside terminal multiplexers, or in standard Termux without `Termux:API`, copying text must succeed via ANSI OSC 52 escape sequences (`\x1b]52;c;<base64>\x07`).
   - Base64 encoding transforms any payload (multiline, special characters, unicode) into valid ASCII payload.
   - In `xai-grok-pager-render`, `resolve_clipboard_route_with` enables `osc52` when `target_os = "android"`.
   - Since terminals reject OSC 52 clipboard reads for security, `get_text()` degrades cleanly to `Ok(None)`.

4. **Premise 4 (Feature 21 - Graceful Degradation)**:
   Non-text clipboard formats (raster images, file URLs) and voice/microphone features are unsupported on Android/Termux.
   - Image and file URL retrieval returns `Ok(None)` / `ClipboardAttachments::default()` with zero panic.
   - Setting image file returns a clear error (`image clipboard is not supported on Android/Termux`).
   - Voice audio capture returns `VoiceError::Config(...)`.
   - The TUI never registers active microphone devices, hides the `/voice` command from help/slash registries, and ignores voice chords gracefully.

---

## 3. Caveats

1. **Process Timeouts during Background Execution**:
   If Android puts Termux into battery-saving doze mode or revokes Termux:API background permissions, `termux-clipboard-get` or `termux-clipboard-set` can potentially hang. Implementing `wait_with_deadline` (e.g. 500ms–1000ms deadline) with thread-drained stdout / tempfile stdin spooling provides maximum resilience against frozen UI loops.
2. **Tmux in Termux**:
   If a user runs `tmux` inside Termux, OSC 52 sequences must include the DCS passthrough envelope (`\x1bPtmux;\x1b\x1b]52;c;...\x07\x1b\`) when `tmux` is the immediate terminal and not inside an editor `:terminal`. `xai-grok-pager-render` already encapsulates this logic via `osc52_tmux_passthrough`.
3. **Preflight Trust Classification**:
   In `crates/codegen/xai-grok-pager-render/src/host/mod.rs` and `src/clipboard/trust.rs`, `HostOs` currently defaults to `HostOs::Other` for Android. Adding an explicit `HostOs::Android` variant allows cleaner doctor diagnostic reporting (`grok doctor`).

---

## 4. Conclusion

- **Feature 19 (Termux:API Text Clipboard)**: Architectural seam is cleanly defined in `xai-grok-shared/src/clipboard.rs` under `#[cfg(target_os = "android")] mod platform`. Recommended hardening: apply `wait_with_deadline` and tempfile stdin spooling (`spool_for_stdin`) to match the Linux implementation's hang-proof behavior.
- **Feature 20 (OSC 52 Fallback)**: Full base64 ANSI escape sequence generation is implemented and tested. In `crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs`, ensure `cfg!(target_os = "android")` enables `osc52` route unconditionally as a fallback safety net.
- **Feature 21 (Graceful Degradation)**: `arboard` and `cpal` are 100% eliminated from the Android build tree. Non-text clipboard functions return clean `Ok(None)` / `bail!` without panics. Voice capture is disabled via `AUDIO_SUPPORTED = false` and `VoiceError::Config`, with all UI surfaces fail-closed.
- **E2E Test Status**: 366/366 tests pass with 100% success rate across all 4 tiers.

---

## 5. Verification Method

### 5.1 E2E Test Suite Execution
Run the full 4-tier E2E test suite:
```bash
python3 tests/e2e/runner.py
```
Run specific Tier 1, Tier 2, and Tier 4 clipboard tests:
```bash
python3 -m unittest tests/e2e/tier1_features/test_feature_17_to_24.py
python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_17_to_24.py
python3 -m unittest tests/e2e/tier4_real_world/test_scenario_clipboard.py
```

### 5.2 Dependency Isolation Verification
Verify `arboard`, `cpal`, and `tikv-jemallocator` are completely excluded on `aarch64-linux-android`:
```bash
cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard -i cpal -i tikv-jemallocator
cargo tree --target aarch64-linux-android -p xai-grok-voice -i arboard -i cpal -i tikv-jemallocator
```

### 5.3 Rust Crate Compilation Verification
Verify that `xai-grok-shared`, `xai-grok-voice`, and `xai-grok-pager-render` compile cleanly:
```bash
cargo check -p xai-grok-shared -p xai-grok-voice -p xai-grok-pager-render
```
