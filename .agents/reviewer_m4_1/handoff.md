# Milestone 4 審查與對抗性挑戰報告 (Review & Adversarial Challenge Report)

- **審查員 / 角色**：`reviewer_m4_1` (Reviewer / Adversarial Critic)
- **審查範圍**：Milestone 4 (Features 15–21: Auth, Network, UX & Clipboard)
- **工作目錄**：`/Users/iml1s/Documents/mine/grok-build-termux/.agents/reviewer_m4_1`
- **審查結論 (Verdict)**：**`APPROVE`**
- **誠信檢查 (Integrity Check)**：**`PASS`** (無寫死假測試、無 facade 假實作、無外包作弊、邏輯真確無欺)

---

## 1. Review Summary (審查摘要)

**Verdict**: **APPROVE**

Milestone 4 所包含之 7 項核心功能（Features 15–21）均已完成審查與獨立驗證。程式碼實作結構嚴謹，精準滿足 `ORIGINAL_REQUEST.md` 與 `PROJECT.md` 之所有介面契約與平台安全規範。

| Feature # | 功能名稱 | 關鍵實作檔案 | 審查狀態 | 誠信狀態 |
|---|---|---|:---:|:---:|
| **15** | Termux OAuth Browser Handoff | `crates/codegen/xai-grok-pager-render/src/link_opener.rs`<br>`crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`<br>`crates/codegen/xai-grok-shell/src/auth/device_code.rs` | **APPROVE** | Genuine |
| **16** | Loopback Callback Server | `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs` | **APPROVE** | Genuine |
| **17** | Manual Code / URL Paste Fallback | `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs` | **APPROVE** | Genuine |
| **18** | Native Bionic DNS & TLS Resolution | `Cargo.toml`<br>`crates/codegen/xai-grok-http/src/lib.rs`<br>`crates/codegen/xai-grok-extra-ca/src/lib.rs` | **APPROVE** | Genuine |
| **19** | Termux:API Text Clipboard | `crates/codegen/xai-grok-shared/src/clipboard.rs` | **APPROVE** | Genuine |
| **20** | OSC 52 Terminal Clipboard Fallback | `crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs`<br>`crates/codegen/xai-grok-shared/src/clipboard.rs` | **APPROVE** | Genuine |
| **21** | Unsupported Clipboard / Voice Degradation | `crates/codegen/xai-grok-shared/Cargo.toml`<br>`crates/codegen/xai-grok-voice/Cargo.toml`<br>`crates/codegen/xai-grok-voice/src/audio/capture_android.rs` | **APPROVE** | Genuine |

---

## 2. Observation (直接觀察與程式碼證據)

### Feature 15: Termux OAuth Browser Handoff (`termux-open-url` & LinkOpener)
- **觀察點 1 (`link_opener.rs:30-45`)**：
  ```rust
  pub fn browser_open_likely_available_from_env(env: &HashMap<String, String>) -> bool {
      if cfg!(any(target_os = "macos", target_os = "windows", target_os = "android")) {
          return true;
      }
      if xai_grok_config::platform::PlatformCapabilities::current().is_android_termux()
          || env.get("PREFIX").is_some_and(|v| !v.is_empty())
      {
          return true;
      }
      ...
  }
  ```
  在 Android 及 Termux 環境下正確判定瀏覽器可用，避免因缺乏 X11/Wayland `DISPLAY` 而被誤判為無瀏覽器。
- **觀察點 2 (`link_opener.rs:117-124`, `165-172`)**：
  `open_url` 與 `build_open_path_command` 在 Android 目標下分別調用 `termux-open-url` 與 `termux-open`，並以 `xai_tty_utils::detach_std_command` 防範子進程搶佔 `/dev/tty`。
- **觀察點 3 (`login.rs:421-445` & `device_code.rs:396-430`)**：
  在 `webbrowser::open` 失敗或處於 Android/Termux 時，自動 fallback 啟動 `termux-open-url`。若完全無法啟動瀏覽器，安全回傳 `false` 讓終端印出授權 URL。

### Features 16 & 17: Loopback Callback & Manual Code/URL Paste Fallback
- **觀察點 4 (`login.rs:393-402`, `117-125`)**：
  `TcpListener::bind(("127.0.0.1", callback_port))` 監聽隨機可用 Port 或開發固定 Port；Axum Router 配置 `allow_private_network(true)` CORS 設定，以相容現代行動瀏覽器 Private Network Access 規範。
- **觀察點 5 (`login.rs:37-69`)**：
  `parse_pasted_input` 完整處理：
  1. 完整 redirect URL (`http://127.0.0.1:PORT/callback?code=...&state=...`)，自動 URL 解碼參數；
  2. IdP 錯誤 URL (`error` / `error_description`)；
  3. 純授權碼 (Bare authorization code) 與前後空白修剪。
- **觀察點 6 (`login.rs:247-298`, `301-345`)**：
  `race_callback_and_client_ui` 與 `race_callback_and_stdin` 使用 `tokio::select!` 與 10 分鐘超時機制，在 HTTP 回調與使用者手動貼上之間進行競爭消費。

### Feature 18: Native Bionic DNS & TLS Resolution
- **觀察點 7 (`Cargo.toml:228`, `xai-grok-http/src/lib.rs`, `xai-grok-extra-ca/src/lib.rs`)**：
  - HTTP 客戶端採用 `reqwest` 配合 `rustls-tls`、`webpki-roots` 以及自訂 `xai-grok-extra-ca` 憑證載入機制。
  - Tokio 的標準 DNS 解析器在 Android 上直接調用 Bionic libc `getaddrinfo`，透過 Unix domain socket 與 Android 系統 `netd` daemon 溝通，杜絕 Linux glibc 對 `/etc/resolv.conf` 的硬性依賴。

### Feature 19: Termux:API Text Clipboard (750ms 超時保護與暫存檔串流)
- **觀察點 8 (`crates/codegen/xai-grok-shared/src/clipboard.rs:2809-2849`)**：
  Android `platform::get_text()` 使用 `xai_tty_utils::detach_std_command` 調用 `termux-clipboard-get`，於獨立執行緒讀取 stdout，並透過 `super::wait_with_deadline` 設定 750ms 嚴格超時，防範 Android 背景進程凍結（Process freezing）或 Termux:API 無響應導致 TUI 主執行緒掛死。
- **觀察點 9 (`crates/codegen/xai-grok-shared/src/clipboard.rs:2856-2889`)**：
  Android `platform::set_text_with_outcome()` 採用 `super::spool_for_stdin` 將剪貼簿內容先寫入 `0600` 暫存檔後傳入 `termux-clipboard-set` stdin，防範超大文本 (>64 KiB) 阻塞管道緩衝區；並在工具缺失或超時時自動降級至 OSC 52。

### Feature 20: OSC 52 Terminal Clipboard Fallback
- **觀察點 10 (`crates/codegen/xai-grok-pager-render/src/clipboard/mod.rs:170-175`)**：
  ```rust
  let osc52 = !opts.no_osc52
      && (cfg!(any(target_os = "linux", target_os = "android"))
          || is_tmux
          || is_remote()
          || is_container_no_display()
          || opts.wrap_sink);
  ```
  在 Android/Termux 終端中預設啟用 OSC 52 寫入路線。
- **觀察點 11 (`crates/codegen/xai-grok-shared/src/clipboard.rs:420-428`)**：
  `osc52_sequence` 使用標準 Base64 編碼，精確格式化為 `\x1b]52;c;<base64>\x07`（或 tmux passthrough 包裹序列），寫入 stderr 終端串流。讀取操作在 Android 上安全回傳 `Ok(None)`，符合終端安全防護要求。

### Feature 21: Unsupported Clipboard / Voice Graceful Degradation & Dependency Isolation
- **觀察點 12 (`crates/codegen/xai-grok-shared/Cargo.toml:43-44`)**：
  ```toml
  [target.'cfg(all(not(target_os = "macos"), not(target_os = "android")))'.dependencies]
  arboard = { workspace = true, features = ["wayland-data-control"] }
  ```
  `arboard` 完全自 Android 目標依賴中排除。`cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard` 驗證 0 依賴。
- **觀察點 13 (`crates/codegen/xai-grok-voice/Cargo.toml:46-49` & `src/lib.rs:46`)**：
  ```toml
  [target.'cfg(all(not(target_os = "linux"), not(target_os = "android")))'.dependencies.cpal]
  version = "0.15"
  optional = true
  ```
  `cpal` 100% 排除於 Android 目標。`AUDIO_SUPPORTED = false`。
- **觀察點 14 (`crates/codegen/xai-grok-voice/src/audio/capture_android.rs:1-33`)**：
  所有音訊擷取函式（`input_device_info`, `spawn_pcm_capture`, `capture_pcm_for_duration`）一律回傳 `Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))`，實現 fail-closed 安全降級。

---

## 3. Adversarial & Edge Case Analysis (對抗性測試與邊界分析)

1. **對抗情境 1：Android 系統休眠或 Termux:API 掛死**
   - **威脅**：Termux:API 在背景凍結時，`termux-clipboard-get` 或 `set` 子進程可能永久阻塞。
   - **防護機制**：`wait_with_deadline(&mut child, Duration::from_millis(750))` 輪詢 `try_wait`，超時立即 `child.kill()` 並 `child.wait()` 回收資源，安全降級回傳 `Ok(None)` / OSC 52，完全不阻礙 TUI 渲染。
2. **對抗情境 2：超大文本複製引發 Pipe Deadlock**
   - **威脅**：當複製超過 64 KiB 的大型代碼段時，若子進程未及時讀取 stdin，直接管道寫入將導致主執行緒死鎖。
   - **防護機制**：`spool_for_stdin` 先行建立私有暫存檔，確保 stdin 資料完全就緒且進程退出後自動刪除，杜絕管道死鎖。
3. **對抗情境 3：OAuth Redirect 遭受 URL 編碼或特異字元注入**
   - **威脅**：使用者手動貼上含有特殊編碼（例如 `code%2B123%3D%3D`）或片段識別碼（Fragment `#`）之 URL。
   - **防護機制**：`parse_pasted_input` 依循 `url::Url` 標準解析並呼叫 `query_pairs().into_owned()`，正確解碼出 `code+123==`，並能安全過濾前後空白與無效輸入。
4. **對抗情境 4：依賴污染與二進位體積膨脹**
   - **威脅**：桌面端 X11/Wayland 或 ALSA/OpenSL ES 原生庫被誤編譯進 Android 二進位檔。
   - **防護機制**：經 `cargo tree --target aarch64-linux-android` 驗證，`arboard` 與 `cpal` 均為 0 引用，完全維持純淨 Bionic libc 依賴。

---

## 4. Logic Chain (推理鏈)

```
[M4 目標: Termux 認證、網路、UX、剪貼簿與語音降級 (Features 15–21)]
                           │
    ┌──────────────────────┼──────────────────────┐
    ▼                      ▼                      ▼
[Feature 15-18: 網路/認證] [Feature 19-20: 剪貼簿] [Feature 21: 依賴隔離與降級]
    │                      │                      │
    ├─ termux-open-url 跳轉├─ Termux:API 750ms超時├─ arboard 自 Android 排除
    ├─ Loopback 回調監聽   ├─ spool_for_stdin 防阻├─ cpal 自 Android 排除
    ├─ 手動 Code/URL 貼上  ├─ OSC 52 Base64 格式  ├─ 非文字剪貼回傳 None
    └─ Bionic libc DNS+TLS └─ 讀取安全回傳 Ok(None)└─ AUDIO_SUPPORTED = false
                           │
                           ▼
[編譯無錯誤 + 依賴 0 污染 + Cargo 單元測試 PASS + 4-Tier E2E 366/366 100% 通過]
                           │
                           ▼
                    【 結論: APPROVE 】
```

---

## 5. Caveats (注意事項)

1. **Termux:API 應用程式安裝**：
   - 剪貼簿存取依賴使用者的 Android 裝置已安裝 `Termux:API` App 與套件。若未安裝，程式碼已全面提供 OSC 52 自動回退，不會產生 panic 或 UI 卡頓。
2. **終端 OSC 52 支援度**：
   - 使用者所使用的終端模擬器需支援 OSC 52 寫入（如 Termux、tmux、Ghostty 等）。若終端不支援，序列會被終端忽略而不影響主要功能。

---

## 6. Conclusion (審查結論)

**Verdict**: **`APPROVE`**

Milestone 4 (Features 15–21) 實作符合專案架構規範、介面契約與安全要求，無任何誠信違規或假實作問題，正式核准通過。

---

## 7. Verification Method (獨立驗證執行指令與結果)

1. **Cargo 編譯檢查**：
   ```bash
   cargo check -p xai-grok-pager-render -p xai-grok-shared -p xai-grok-shell -p xai-grok-voice
   ```
   *結果*：`Finished dev profile [unoptimized + debuginfo] in 38.64s`（0 錯誤）。

2. **Cargo 單元測試**：
   ```bash
   cargo test --lib -p xai-grok-shared
   cargo test --lib -p xai-grok-pager-render -- link_opener
   ```
   *結果*：
   - `xai-grok-shared`: 99 passed; 0 failed.
   - `xai-grok-pager-render (link_opener)`: 30 passed; 0 failed.

3. **依賴樹隔離檢查 (aarch64-linux-android)**：
   ```bash
   cargo tree --target aarch64-linux-android -p xai-grok-shared -i arboard
   cargo tree --target aarch64-linux-android -p xai-grok-voice -i cpal
   ```
   *結果*：`warning: nothing to print`（0 匹配，確定排除）。

4. **4-Tier E2E 完整測試集驗證**：
   ```bash
   python3 tests/e2e/runner.py
   ```
   *結果*：
   ```
   ================================================================================
    grok-build-termux : 4-Tier E2E Test Suite Execution
   ================================================================================
   [✓] Tier 1: Feature Coverage (32 Features × 5)              Tests: 160 | Passed: 160 | Failed:  0 | Time: 3.16s
   [✓] Tier 2: Boundary & Corner Cases (32 Features × 5)       Tests: 160 | Passed: 160 | Failed:  0 | Time: 2.12s
   [✓] Tier 3: Pairwise Cross-Feature Interactions             Tests:  34 | Passed:  34 | Failed:  0 | Time: 1.05s
   [✓] Tier 4: Real-World Application Scenarios                Tests:  12 | Passed:  12 | Failed:  0 | Time: 0.52s
   ================================================================================
   Summary: 366/366 passed in 6.866s | Result: SUCCESS (100% PASSED)
   ================================================================================
   ```

5. **ELF 驗證器自我測試**：
   ```bash
   python3 scripts/validate_elf.py --self-test
   ```
   *結果*：`All self-tests passed successfully.`
