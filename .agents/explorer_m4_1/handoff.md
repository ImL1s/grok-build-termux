# Milestone 4 探索與實作分析報告：Termux 認證與網路整合 (Features 15–18)

- **作者 / 角色**：`explorer_m4_1` (Teamwork Explorer)
- **探索目標**：Milestone 4 中的 Features 15–18（OAuth 瀏覽器跳轉、Loopback 回調伺服器、手動貼上 Code/URL Fallback、Native Bionic DNS 與 TLS 解析）
- **日期**：2026-08-16

---

## 1. Observation (直接觀察)

### Feature 15: Termux OAuth Browser Handoff via `termux-open-url` & `LinkOpener`
- **現行檔案與行號**：
  - `crates/codegen/xai-grok-pager-render/src/link_opener.rs`:
    - 第 29–40 行：`browser_open_likely_available_from_env` 僅檢查 macOS / Windows 或 Linux 上的 `WAYLAND_DISPLAY`、`DISPLAY` 與 `BROWSER`。
      ```rust
      pub fn browser_open_likely_available_from_env(env: &HashMap<String, String>) -> bool {
          if cfg!(any(target_os = "macos", target_os = "windows")) {
              return true;
          }
          if env.get("BROWSER").is_some_and(|v| !v.is_empty()) {
              return true;
          }
          env.get("WAYLAND_DISPLAY").is_some_and(|v| !v.is_empty())
              || env.get("DISPLAY").is_some_and(|v| !v.is_empty())
      }
      ```
    - 第 100–124 行：`open_url` 在非 macOS / Windows 平台上一律使用 `xdg-open`：
      ```rust
      #[cfg(target_os = "macos")]
      let cmd = "open";
      #[cfg(target_os = "windows")]
      let cmd = "cmd";
      #[cfg(not(any(target_os = "macos", target_os = "windows")))]
      let cmd = "xdg-open";
      ```
  - `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`:
    - 第 423、436 行：直接調用 `webbrowser::open(&auth_url)`。
  - `crates/codegen/xai-grok-shell/src/auth/device_code.rs`:
    - 第 398 行：調用 `webbrowser::open(&url)`。
  - `crates/codegen/xai-grok-mcp/src/oauth.rs`:
    - 第 387 行：調用 `webbrowser::open(&auth_url)`。
- **測試規格依據**：
  - `tests/e2e/tier1_features/test_feature_09_to_16.py` (Line 289–322):
    `LinkOpenerSeam` 在 Android/Termux 環境下應透過 `termux-open-url` 發起瀏覽器跳轉；若 `termux-open-url` 不存在或失敗，則安全退回到 `manual_print` 並提示使用者手動開啟 URL。
  - `tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py` (Line 280–317):
    驗證 Scheme 安全過濾（僅允許 `http://` / `https://`，拒絕 `javascript:`、`ftp:`、`data:` 等），且對含 query 參數、fragment、IPv6 等長 URL 均能安全傳遞。

---

### Feature 16: Loopback Callback Server (`127.0.0.1:<port>`)
- **現行檔案與行號**：
  - `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`:
    - 第 393–414 行：綁定 `TcpListener::bind(("127.0.0.1", callback_port))`，取得隨機分配之本機 Port，建構 `redirect_uri = format!("http://127.0.0.1:{}/callback", port)`。
    - 第 117–125 行：透過 `axum` 構建 Router，掛載 `GET /callback` 處理器與 CORS Layer：
      ```rust
      fn build_callback_router(tx: tokio::sync::mpsc::Sender<CallbackResult>) -> Router {
          let cors =
              crate::auth::config::accounts_app_cors_layer(Method::GET).allow_private_network(true);

          Router::new()
              .route("/callback", get(handle_callback))
              .layer(cors)
              .with_state(tx)
      }
      ```
    - 第 127–137 行：`handle_callback` 從 Query 參數中擷取 `code` 與 `state`，並回傳格式化之 HTML 確認頁面 (`callback_page`)。
    - 第 327–342 行：逾時機制設定為 10 分鐘 (`AUTH_CALLBACK_TIMEOUT = 600s`)，並在收到結果或逾時後透過 `shutdown_tx.send(())` 關閉 HTTP 伺服器並釋放 Port。
- **測試規格依據**：
  - `tests/e2e/tier1_features/test_feature_09_to_16.py` (Line 327–370): 驗證綁定 `127.0.0.1`、擷取 `code` / `state`、回傳 200 HTML 以及未知路徑回傳 404 等行為。

---

### Feature 17: Manual Code / URL Paste Fallback
- **現行檔案與行號**：
  - `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`:
    - 第 37–69 行：`parse_pasted_input(input: &str) -> Result<Callback, OidcError>`：
      ```rust
      fn parse_pasted_input(input: &str) -> Result<Callback, OidcError> {
          let input = input.trim();
          if input.is_empty() {
              return Err(OidcError::InvalidPastedInput("empty input".into()));
          }

          if let Ok(url) = url::Url::parse(input) {
              let params: HashMap<String, String> = url.query_pairs().into_owned().collect();
              if let Some(code) = params.get("code") {
                  let state = params.get("state").cloned().unwrap_or_default();
                  return Ok(Callback {
                      code: code.clone(),
                      state,
                  });
              }
              if let Some(error) = params.get("error") {
                  let desc = params.get("error_description").cloned().unwrap_or_default();
                  return Err(OidcError::CallbackAuthFailed(if desc.is_empty() {
                      error.clone()
                  } else {
                      format!("{error}: {desc}")
                  }));
              }
              return Err(OidcError::InvalidPastedInput(
                  "URL has no 'code' query parameter".into(),
              ));
          }

          Ok(Callback {
              code: input.to_owned(),
              state: String::new(),
          })
      }
      ```
    - 第 173–194 行：`wait_for_stdin_or_closed` 使用標準 POSIX `libc::poll` 監聽 Stdin。
    - 第 247–298 行及 301–345 行：`race_callback_and_client_ui` 與 `race_callback_and_stdin` 使用 `tokio::select!` 同時競爭 Loopback 回調伺服器與 Stdin/UI 貼上通道。
- **測試規格依據**：
  - `tests/e2e/tier1_features/test_feature_17_to_24.py` (Line 33–60) 與 `tests/e2e/tier2_boundaries/test_boundaries_17_to_24.py` (Line 33–57): 驗證 bare code、完整 redirect URL、含 extra query 參數、fragment、CRLF 換行、以及 URL-encoded 參數之貼上解析。

---

### Feature 18: Native Bionic DNS & TLS Resolution
- **現行檔案與行號**：
  - `Cargo.toml`:
    - 第 228 行：`reqwest = { version = "0.12", features = ["rustls-tls", "stream", "json", "multipart", "http2", "blocking", "socks"], default-features = false }`
    - 第 236 行：`rustls = { version = "0.23", features = ["aws-lc-rs"] }`
    - 第 295 行：`webpki-roots = "0.26"`
  - `crates/codegen/xai-grok-http/src/lib.rs`:
    - 第 305–338 行：`shared_client` 使用 `reqwest::Client::builder()`，預設透過 Tokio `GaiResolver` 調用 Bionic libc 之 `getaddrinfo`。
  - `crates/codegen/xai-grok-extra-ca/src/lib.rs`:
    - 第 1–47 行：提供 `GROK_EXTRA_CA_BUNDLE` 環境變數擴充，利用 `rustls::RootCertStore` 載入額外憑證，基底仍依賴 compiled-in `webpki-roots`。
- **測試規格依據**：
  - `tests/e2e/tier1_features/test_feature_17_to_24.py` (Line 64–91): 驗證透過系統 `getaddrinfo`（Android netd daemon）解析、雙棧 IPv4/IPv6、網路切換（Wi-Fi/行動網路）以及使用 `rustls` 進行原生驗證。

---

## 2. Logic Chain (邏輯推理鏈)

```
[Observation: Android/Termux 環境缺乏 X11/Wayland display server]
          │
          ▼
[Step 1: browser_open_likely_available_from_env 判斷 DISPLAY/WAYLAND_DISPLAY，在 Termux 下會誤判為 false]
          │
          ▼
[Step 2: Termux 具備 termux-open-url 系統工具，可透過 Android Intent 發起系統預設瀏覽器開啟 URL]
          │
          ▼
[Step 3: 需在 link_opener.rs 中引入 PlatformCapabilities::current().is_android_termux() 或 target_os = "android"，判斷瀏覽器可用性，並優先調用 termux-open-url]
          │
          ▼
[Step 4: Loopback 回調伺服器 (127.0.0.1:<port>) 在 Android 上透過同機網路棧接收瀏覽器重定向]
          │
          ▼
[Step 5: 為防範瀏覽器隔離或 Headless/SSH 情境，由 parse_pasted_input 與 race_callback_and_stdin 提供即時貼上 Fallback]
          │
          ▼
[Step 6: DNS 解析必須依賴 Bionic libc getaddrinfo (與 Android netd 溝通)，TLS 依賴 rustls + webpki-roots (免除 /etc/ssl/certs 依賴)]
          │
          ▼
[Conclusion: M4 Features 15–18 的設計與現行代碼庫架構高度吻合，僅需在 LinkOpener 與瀏覽器跳轉處補強 Termux 專屬分支即可達成無縫整合]
```

---

## 3. Caveats (注意事項與潛在風險)

1. **`termux-open-url` 之存在性與權限**：
   - 使用者在 Termux 中若未安裝 `termux-tools` 套件（雖然 Termux 預設自帶），`termux-open-url` 可能無法執行。
   - 若調用失敗，`open_url` 必須安全回傳 `false`，由 caller 觸發 `browser_unavailable_message` / `browser_unavailable_line` 提示使用者手動複製網址。
2. **Android 14+ / Chrome Private Network Access (PNA)**：
   - 現代瀏覽器對 `https` 頁面跳轉至 `http://127.0.0.1` 可能觸發 CORS 或 PNA 限制。現有代碼已配置 `.allow_private_network(true)`，且備有手動貼上 code/URL 機制（Feature 17），能提供 100% 容錯。
3. **Rust `webbrowser` Crate 與 Termux**：
   - `xai-grok-shell` 與 `xai-grok-mcp` 目前直接使用 `webbrowser::open`。在 Android Termux 上，若未包裝 fallback 或統一走 `LinkOpener`，`webbrowser::open` 可能會失敗。建議在 shell / auth 處提供 fallback 至 `termux-open-url`。
4. **Android DNS `/etc/resolv.conf` 陷阱**：
   - 切勿在任何地方引入純 Rust DNS 庫去手動讀取 `/etc/resolv.conf`（Android 上不存在或無效），必須嚴格保持 Tokio 預設的 `GaiResolver` (`libc::getaddrinfo`)。

---

## 4. Conclusion & Implementation Recommendations (結論與實作建議)

### Feature 15 (OAuth Browser Handoff) 實作建議：
1. **修改 `crates/codegen/xai-grok-pager-render/src/link_opener.rs`**：
   - 在 `browser_open_likely_available_from_env` 增加 Termux / Android 檢測：
     ```rust
     if cfg!(target_os = "android")
         || xai_grok_config::platform::PlatformCapabilities::current().is_android_termux()
         || env.get("PREFIX").is_some()
     {
         return true;
     }
     ```
   - 在 `open_url` 增加 `termux-open-url` 指令嘗試：
     ```rust
     #[cfg(target_os = "android")]
     let cmd = "termux-open-url";
     #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "android")))]
     let cmd = if xai_grok_config::platform::PlatformCapabilities::current().is_android_termux() {
         "termux-open-url"
     } else {
         "xdg-open"
     };
     ```
2. **在 `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs` 與 `device_code.rs` 增強跳轉**：
   - 在調用 `webbrowser::open` 失敗或處於 Termux 環境時，自動嘗試 `termux-open-url <url>`。

### Feature 16 & 17 (Loopback Server & Manual Paste) 評估：
- 現行 `xai-grok-shell/src/auth/oidc/login.rs` 的 `build_callback_router`、`parse_pasted_input` 及 `race_callback_and_stdin` 架構完善，完全滿足需求。

### Feature 18 (Bionic DNS & TLS) 評估：
- 現行 `Cargo.toml` 與 `xai-grok-http` 架構配置完全符合 Android Bionic 原生規範（使用 Tokio `GaiResolver` + `rustls-tls` + `webpki-roots`）。

---

## 5. Verification Method (獨立驗證方式)

1. **執行 E2E 完整測試集**：
   ```bash
   python3 tests/e2e/runner.py
   ```
   *預期結果*：366/366 測試全數通過（100% Pass）。

2. **執行 Feature 15–18 專屬單元與邊界測試**：
   ```bash
   python3 -m unittest tests/e2e/tier1_features/test_feature_09_to_16.py
   python3 -m unittest tests/e2e/tier1_features/test_feature_17_to_24.py
   python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py
   python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_17_to_24.py
   python3 -m unittest tests/e2e/tier4_real_world/test_scenario_oauth.py
   ```

3. **執行 Rust 內部單元測試**：
   ```bash
   cargo test -p xai-grok-pager-render --lib link_opener
   cargo test -p xai-grok-config
   cargo test -p xai-grok-extra-ca
   ```

4. **失效條件 (Invalidation Conditions)**：
   - 若 `browser_open_likely_available` 在 Termux 環境（無 `DISPLAY`）下回傳 `false`。
   - 若 `open_url` 在 Termux 下未嘗試調用 `termux-open-url`。
   - 若 `parse_pasted_input` 無法正確解析 `code` 或完整 redirect URL。
   - 若 DNS 解析嘗試開啟 `/etc/resolv.conf` 導致在 Android Bionic 下發生 `ENOENT`。
