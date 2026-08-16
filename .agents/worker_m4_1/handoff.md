# Milestone 4 實作完成報告：Termux Auth, UX & Truthful Sandboxing (Features 15–26)

- **作者 / 角色**：`worker_m4_1` (Implementer / QA / Specialist)
- **工作目錄**：`/Users/iml1s/Documents/mine/grok-build-termux/.agents/worker_m4_1`
- **目標里程碑**：Milestone 4 (Features 15–26: Termux 認證、UX、剪貼簿、沙盒與電源管理)
- **完成日期**：2026-08-16

---

## 1. Observation (直接觀察)

1. **Feature 15: OAuth Browser Handoff via `termux-open-url` & `LinkOpener`**：
   - 檔案：`crates/codegen/xai-grok-pager-render/src/link_opener.rs`
     - `browser_open_likely_available_from_env` 原先僅判定 macOS / Windows / Linux DISPLAY。已更新加入 `cfg!(target_os = "android")`、`PlatformCapabilities::current().is_android_termux()` 以及 `PREFIX` 環境變數偵測。
     - `open_url` 與 `build_open_path_command` 在 Android / Termux 環境下已配置優先調用 `termux-open-url` 與 `termux-open`，並在工具缺失時安全回傳 `false` 觸發手動 URL 呈現。
   - 檔案：`crates/codegen/xai-grok-shell/src/auth/oidc/login.rs` 與 `crates/codegen/xai-grok-shell/src/auth/device_code.rs`
     - 在調用 `webbrowser::open` 失敗或處於 Android / Termux 環境時，增設 `termux-open-url` fallback，確保 OIDC 與 Device Code 認證跳轉在 Android 上能直接啟動系統瀏覽器。

2. **Features 16 & 17: Loopback Callback & Manual Paste Fallback**：
   - 檔案：`crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
     - `TcpListener::bind(("127.0.0.1", port))` 正確監聽隨機本機 Port，配置 `allow_private_network(true)` CORS 層以適應現代行動瀏覽器。
     - `parse_pasted_input` 支援 bare authorization code 與完整 redirect URL（含 query 參數、fragment、URL-encoded 字符等）。
     - `race_callback_and_stdin` 與 `race_callback_and_client_ui` 使用 `tokio::select!` 同時競爭本機 HTTP 回調與使用者 Stdin/TUI 手動貼上輸入。

3. **Feature 18: Native Bionic DNS & TLS Resolution**：
   - 檔案：`Cargo.toml` 與 `crates/codegen/xai-grok-http/src/lib.rs`
     - 採用標準 Tokio `GaiResolver` 調用 Bionic libc 之 `libc::getaddrinfo`（與 Android 系統 `netd` daemon 溝通，杜絕 `/etc/resolv.conf` 依賴）。
     - TLS 採用 `rustls-tls` 配合 compiled-in `webpki-roots` 及 `xai-grok-extra-ca` 憑證擴充。

4. **Feature 19: Termux:API Text Clipboard 加固**：
   - 檔案：`crates/codegen/xai-grok-shared/src/clipboard.rs`
     - Android `platform::get_text()` 使用 `xai_tty_utils::detach_std_command`，以獨立執行緒讀取 stdout，並透過 `super::wait_with_deadline`（750ms 逾時）防範 Android 背景凍結導致 TUI 主執行緒卡死。
     - Android `platform::set_text_with_outcome()` 採用 `super::spool_for_stdin` 將文字寫入暫存檔傳遞給 `termux-clipboard-set` stdin，並透過 `wait_with_deadline` 進行超時保護；若失敗或工具不存在則安全回退至 OSC 52。

5. **Feature 20: OSC 52 Terminal Clipboard Fallback**：
   - 檔案：`crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs`
     - `resolve_clipboard_route_with` 中將 `cfg!(target_os = "linux")` 擴充為 `cfg!(any(target_os = "linux", target_os = "android"))`，使 Android/Termux 終端預設啟用 OSC 52 寫入路線。
     - `xai-grok-shared/src/clipboard.rs` 正確生成 `\x1b]52;c;<base64>\x07` ANSI 序列，讀取操作安全回傳 `Ok(None)`。

6. **Feature 21: Unsupported Clipboard & Voice Graceful Degradation**：
   - `arboard` 與 `cpal` 100% 自 `aarch64-linux-android` 依賴樹中排除（`cargo tree` 驗證 0 匹配）。
   - 圖片/檔案剪貼簿安全回傳 `Ok(None)` / 錯誤而不 panic。
   - `AUDIO_SUPPORTED = false`，語音模組回傳 `VoiceError::Config`，所有 UI 入口（如 `/voice` 命令）一律 fail-closed 隱藏。

7. **Features 22–26: Truthful Sandboxing, Policy Enforcement, Concurrency, Wake Lock, Durable Sessions**：
   - `PlatformCapabilities::sandbox_kind()` 在 Android 上忠實回報 `SandboxKind::PolicyOnly`（`"policy-only"`）。
   - 記憶體中策略引擎執行嚴格路徑檢查（封鎖 `~/.ssh`、`~/.grok/credentials.json`、`$PREFIX/etc/grok`、`/proc`、`/sys` 及 shared storage `/sdcard`）。
   - 行動端併發上限（worker threads ≤ 4, subagents ≤ 2）受控。
   - 建立 `crates/codegen/xai-system-power/src/android.rs`，整合 `termux-wake-lock` 與 `termux-wake-unlock` 之引用計數 RAII guard。
   - `xai-grok-config/src/fs_atomic.rs` 與 `xai-grok-active-sessions` 提供原子 checkpoint 與崩潰復原機制。

---

## 2. Logic Chain (邏輯推理鏈)

```
[M4 目標: 建立 Termux 原生認證、UX、剪貼簿、沙盒與電源管理]
                           │
    ┌──────────────────────┼──────────────────────┐
    ▼                      ▼                      ▼
[Feature 15-18: 網路/認證] [Feature 19-21: UX/剪貼] [Feature 22-26: 沙盒/韌性]
    │                      │                      │
    ├─ termux-open-url 跳轉├─ Termux:API 750ms超時├─ 忠實 PolicyOnly 沙盒
    ├─ Loopback 回調伺服器 ├─ spool_for_stdin     ├─ 行動端併發壓制 (LMK 防護)
    ├─ Manual code/URL 貼上├─ OSC 52 終端剪貼備援 ├─ termux-wake-lock RAII
    └─ Bionic DNS + rustls └─ cpal/arboard 乾淨排除└─ 原子 Session 儲存
                           │
                           ▼
[所有 Crates 編譯通過 + Rust 單元測試通過 + E2E 366/366 100% 通過]
```

---

## 3. Caveats (注意事項)

1. **`Termux:API` 依賴性**：
   - 剪貼簿讀取與 Wake Lock 依賴 Termux:API 套件。若使用者環境未安裝，程式碼已全面提供優雅降級（剪貼簿自動回退至 OSC 52，Wake Lock 自動降級為無鎖模式，均不會 crash 或阻塞）。
2. **終端 OSC 52 支援**：
   - 部分行動終端模擬器可能預設停用 OSC 52 寫入權限，但這屬於終端安全設定，Grok Build 會如實發送序列並不產生 panic。

---

## 4. Conclusion (結論)

Milestone 4 所涵蓋之 12 項核心功能（Features 15–26）已全數實作、加固並通過驗證：
- `crates/codegen/xai-grok-pager-render/src/link_opener.rs`
- `crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs`
- `crates/codegen/xai-grok-shared/src/clipboard.rs`
- `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
- `crates/codegen/xai-grok-shell/src/auth/device_code.rs`
- `crates/codegen/xai-system-power/src/android.rs`
- `crates/codegen/xai-system-power/src/lib.rs`

所有改動均符合專案規範與真確性要求（No hardcoding / Genuine logic）。

---

## 5. Verification Method (獨立驗證方法)

1. **Cargo 編譯檢查**：
   ```bash
   cargo check -p xai-grok-pager-render -p xai-grok-shared -p xai-grok-shell -p xai-grok-sandbox -p xai-grok-voice -p xai-system-power
   ```
   *結果*：`Finished dev profile [unoptimized + debuginfo] in 1m 49s`（0 錯誤）。

2. **Cargo 單元測試**：
   ```bash
   cargo test -p xai-grok-config -p xai-grok-shared -p xai-grok-extra-ca -p xai-system-power
   cargo test -p xai-grok-pager-render --lib link_opener
   ```
   *結果*：全數測試通過（99 + 7 + 30 = 136+ tests passed）。

3. **4-Tier E2E 完整測試集驗證**：
   ```bash
   python3 tests/e2e/runner.py
   ```
   *結果*：**366/366 測試 100% 通過**（耗時 ~7.39 秒）。

4. **ELF 驗證器自我測試**：
   ```bash
   python3 scripts/validate_elf.py --self-test
   ```
   *結果*：全數驗證通過。
