## 2026-08-16T02:00:40Z

You are worker_m4_1 implementing Milestone 4: Termux Auth, UX & Truthful Sandboxing (Features 15–26) for the native Android/Termux port of Grok Build.
Your working directory is: /Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m4_1

Read the following files before starting work:
- /Users/iml1s/Documents/mine/grok-build-termux/ORIGINAL_REQUEST.md
- /Users/iml1s/Documents/mine/grok-build-termux/PROJECT.md
- /Users/iml1s/Documents/mine/grok-build-termux/TEST_INFRA.md
- /Users/iml1s/Documents/mine/grok-build-termux/TEST_READY.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m4_1/handoff.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m4_2/handoff.md
- /Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m4_3/handoff.md

Your exclusive write ownership covers:
- `crates/codegen/xai-grok-pager-render/src/link_opener.rs`
- `crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs`
- `crates/codegen/xai-grok-shared/src/clipboard.rs`
- `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
- `crates/codegen/xai-grok-shell/src/auth/device_code.rs`
- `crates/codegen/xai-grok-sandbox/`
- `crates/codegen/xai-grok-voice/`
- `crates/codegen/xai-system-power/`
- `crates/codegen/xai-grok-config/`

Your Tasks:
1. Feature 15 (OAuth Browser Handoff): In `xai-grok-pager-render/src/link_opener.rs`, ensure `browser_open_likely_available_from_env` detects Termux/Android environments (`cfg!(target_os = "android")`, `PlatformCapabilities::current().is_android_termux()`, or `$PREFIX`), and `open_url` uses `termux-open-url` on Android/Termux. Ensure auth login (`xai-grok-shell/src/auth/oidc/login.rs` and `device_code.rs`) falls back to `termux-open-url` or `LinkOpener` if `webbrowser::open` fails.
2. Features 16 & 17 (Loopback Callback & Manual Paste): Verify loopback callback on `127.0.0.1:<port>`, `parse_pasted_input` for bare code and full redirect URLs, and `race_callback_and_stdin`.
3. Feature 18 (Bionic DNS & TLS): Ensure standard Tokio `GaiResolver` (`libc::getaddrinfo`) and `rustls-tls` with `webpki-roots` are properly configured.
4. Feature 19 (Termux:API Text Clipboard): Harden Android clipboard implementation in `xai-grok-shared/src/clipboard.rs` with `wait_with_deadline` and stdin spooling to prevent hangs if Termux:API is stalled.
5. Feature 20 (OSC 52 Terminal Clipboard Fallback): In `xai-grok-pager-render/src/clipboard/mod.rs`, ensure `osc52` route is enabled for `target_os = "android"`. Ensure base64 ANSI escape sequences `\x1b]52;c;<base64>\x07` are generated and OSC 52 read returns `Ok(None)`.
6. Feature 21 (Unsupported Clipboard & Voice Graceful Degradation): Verify `arboard` and `cpal` are 100% excluded on Android, image/file clipboard functions return clean `Ok(None)` / error without panics, and voice capture returns `VoiceError::Config` with UI surfaces fail-closed.
7. Features 22–26 (Sandboxing, Policy Enforcement, Concurrency, Wake Lock, Durable Sessions): Verify and ensure `SandboxKind::PolicyOnly` is reported on Android/Termux, in-process path enforcement guards sensitive directories, concurrency defaults are clamped on mobile, wake lock integrates with `termux-wake-lock`, and atomic session persistence is active.
8. Build & Test Verification:
   - Run `cargo check -p xai-grok-pager-render -p xai-grok-shared -p xai-grok-shell -p xai-grok-sandbox -p xai-grok-voice`
   - Run `cargo test -p xai-grok-config -p xai-grok-shared -p xai-grok-extra-ca`
   - Run `python3 tests/e2e/runner.py` (ensure 366/366 pass 100%)
9. Write a comprehensive 5-component handoff report to:
   `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m4_1/handoff.md`
   Update `/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m4_1/progress.md`
   Send a completion message back when done.
