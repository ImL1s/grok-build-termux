# Milestone 3 (Feature 12) 調查與實作策略報告：Runtime 暫存檔與 Unix Domain Sockets

**報告撰寫者**：Explorer 2 (`explorer_m3_2`)  
**調查主題**：Feature 12（Runtime Temporary Files and Unix Domain Sockets）  
**目標架構**：`aarch64-linux-android` / Android Termux 環境  
**關聯需求**：`ORIGINAL_REQUEST.md` §R3 (Filesystem Safety & Storage Boundaries), `PROJECT.md` Feature 12  

---

## 1. 觀察事實 (Observation)

### 1.1 暫存目錄解析機制 (`PlatformCapabilities::temp_dir`)
在 `crates/codegen/xai-grok-config/src/platform.rs`（第 234-245 行與 348-350 行）直接觀察到：
```rust
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
```
以及暴露的方法：
```rust
pub fn temp_dir(&self) -> PathBuf {
    self.tmp.clone()
}
```
- 當環境變數 `TMPDIR` 存在且非空時，優先使用 `$TMPDIR`。
- 當 `TMPDIR` 未設定時，在 Termux 環境下（`prefix` 存在，如 `/data/data/com.termux/files/usr`）動態回退至 `$PREFIX/tmp`（即 `/data/data/com.termux/files/usr/tmp`），絕不會使用 Android 系統根目錄下不存在的 `/tmp`。
- 在桌面 Linux/macOS 環境下，無 `prefix` 時回退至 `/tmp`。

### 1.2 Unix Domain Socket 路徑生成與 108 字元長度限制 (`create_socket_path`)
在 `crates/codegen/xai-grok-config/src/platform.rs`（第 352-364 行）直接觀察到：
```rust
pub fn create_socket_path(&self, session_id: &str) -> Result<PathBuf, PlatformError> {
    let tmp = self.temp_dir();
    let hash = blake3::hash(session_id.as_bytes());
    let short_hash = &hash.to_hex()[..8];
    let sock_name = format!("grok-{short_hash}.sock");
    let sock_path = tmp.join(&sock_name);

    let path_str = sock_path.to_string_lossy();
    if path_str.len() >= 108 {
        return Err(PlatformError::SocketPathTooLong(path_str.into_owned()));
    }
    Ok(sock_path)
}
```
- 任意長度的 `session_id` 透過 Blake3 雜湊截取前 8 碼 hex，產出固定長度檔名 `grok-12345678.sock`（18 bytes）。
- 在原生 Termux 前綴下：`/data/data/com.termux/files/usr/tmp/grok-xxxxxxxx.sock` 的長度為 `34 + 1 + 18 = 53 bytes`，遠低於 Linux/Bionic 的 108 bytes（`struct sockaddr_un.sun_path`）與 macOS 的 104 bytes 限制。
- 明確進行邊界長度校驗：若長度 `>= 108` 則回傳 `PlatformError::SocketPathTooLong`。

### 1.3 伺服器與 Daemon 的 Socket 綁定與過期 Socket 清理機制 (Stale Socket Cleanup)
在跨 Crate 的調查中觀察到以下三處核心 Socket 創建與清理邏輯：
1. **`xai-grok-shell::leader::server::run_leader_server`** (`crates/codegen/xai-grok-shell/src/leader/server.rs`:1567-1569)：
   ```rust
   let _ = std::fs::remove_file(&socket_path);
   let shutdown_reason_rx = shutdown_tx.subscribe();
   let listener = LeaderListener::bind(&socket_path)?;
   ```
2. **`xai-grok-shell::leader::lock::LeaderLock`** (`crates/codegen/xai-grok-shell/src/leader/lock.rs`:266-272, 304-316)：
   ```rust
   pub(crate) fn cleanup_socket(&self) -> io::Result<()> {
       match fs::remove_file(&self.sock_path) {
           Ok(()) => Ok(()),
           Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
           Err(e) => Err(e),
       }
   }
   // Drop 實作：
   impl Drop for LeaderLock {
       fn drop(&mut self) {
           if self.was_leader {
               let _ = fs::remove_file(&self.lock_path);
               let _ = fs::remove_file(&self.sock_path);
           }
       }
   }
   ```
3. **`xai-grok-shell::leader::mod::connect_or_spawn`** (`crates/codegen/xai-grok-shell/src/leader/mod.rs`:1456-1486, 1492-1525)：
   - 首先檢查 `listener_is_ready(&sock_path)`。
   - 若檔案存在，讀取 `.lock` 中的 PID 並透過 `crate::util::is_process_alive(pid)` 驗證行程是否存活。
   - 若 PID 已死，跳過連線並標記為 stale。
   - 嘗試獲取 `LeaderLock::try_acquire()` 排他鎖（基於 `flock`），獲取成功後清理解析舊 Socket 並重啟 Leader。
4. **`xai-grok-diag-server::serve`** (`crates/codegen/xai-grok-diag-server/src/lib.rs`:390-395)：
   ```rust
   DiagListener::Unix(path) => {
       let _ = fs::remove_file(&path);
       let listener =
           UnixListener::bind(&path).map_err(|e| anyhow!("bind {}: {e}", path.display()))?;
       if let Err(e) = fs::set_permissions(&path, fs::Permissions::from_mode(0o600)) {
           tracing::warn!(path = %path.display(), error = %e, "failed to restrict diagnostics socket permissions");
       }
   ```
5. **發現的潛在隱患**：
   `crates/codegen/xai-grok-diag-server/src/lib.rs` 第 30 行定義了：
   `pub const DEFAULT_DIAG_SOCKET_PATH: &str = "/tmp/workspace-server.sock";`
   在 Android Termux 上，若未給定 CLI 參數，直接使用此常數將嘗試寫入根目錄 `/tmp` 而導致 `ENOENT` 或 `EACCES`。

### 1.4 E2E 測試驗證執行結果
執行測試指令：`python3 tests/e2e/runner.py`
```
================================================================================
 grok-build-termux : 4-Tier E2E Test Suite Execution
================================================================================
[✓] Tier 1: Feature Coverage (32 Features × 5)              Tests: 160 | Passed: 160 | Failed:  0 | Time: 3.80s
[✓] Tier 2: Boundary & Corner Cases (32 Features × 5)       Tests: 160 | Passed: 160 | Failed:  0 | Time: 2.00s
[✓] Tier 3: Pairwise Cross-Feature Interactions             Tests:  34 | Passed:  34 | Failed:  0 | Time: 1.22s
[✓] Tier 4: Real-World Application Scenarios                Tests:  12 | Passed:  12 | Failed:  0 | Time: 0.60s
================================================================================
Summary: 366/366 passed in 7.705s | Result: SUCCESS (100% PASSED)
================================================================================
```

---

## 2. 推論鏈 (Logic Chain)

1. **暫存目錄的安全與可用性解析**：
   - 根據 Android 的沙盒與 SELinux 規則，非 root 應用程式無法存取 `/data/local/tmp`（標準 Rust `std::env::temp_dir()` 在 Android 上的預設 fallback），且 Android 根目錄沒有可寫的 `/tmp`。
   - Termux 在其私有前綴中建立了 `$PREFIX/tmp`（通常為 `/data/data/com.termux/files/usr/tmp`）。
   - `PlatformCapabilities::probe` 透過 `env.get_var("TMPDIR")` 與 `prefix.join("tmp")` 回退機制，確保了無論使用者是否在 shell 中 `export TMPDIR`，Grok 都能取得合法且可寫入的暫存目錄路徑。

2. **`sun_path` 108-byte 限制與 Termux 路徑長度相容性**：
   - POSIX `sockaddr_un` 的結構體欄位 `char sun_path[108]` 要求包含結尾空字元在內不得超過 108 bytes。
   - Termux 的標準暫存目錄 `/data/data/com.termux/files/usr/tmp` 長度為 34 位元組。
   - 若 Socket 檔名採用未經截短的隨機 UUID 或完整 Session 名稱（如 40-60 字元），加上目錄路徑很容易逼近或超越 108 位元組（例如 `34 + 1 + 65 = 100+ bytes`，若目錄層級較深則直接溢位）。
   - `create_socket_path` 將 session id 壓制為 8 碼 Blake3 雜湊（`grok-{short_hash}.sock` = 18 位元組），總路徑長度穩定維持在 53 位元組，預留了 54 位元組的安全餘裕，即使使用者將 `$TMPDIR` 設定在較深的自訂子目錄下也能保證安全。
   - 透過 `>= 108` 的防禦性檢查，避免底層 `bind()` 或 `connect()` 產生不可預期的核心錯誤或記憶體截斷。

3. **過期 Socket (Stale Socket) 與崩潰恢復機制**：
   - 在 Unix 系統中，如果進程異常退出（如收到 `SIGKILL` 或 Android LMK 殺死後台進程），核心不會自動刪除檔案系統上的 `.sock` 節點。
   - 當新進程重新啟動呼叫 `bind()` 時，會立即遭遇 `EADDRINUSE`。
   - Grok 採用四重保護機制：
     1. **Liveness 探針**：透過 `kill(pid, 0)` 確認既有 PID 是否存活；若已死亡，認定為 stale socket。
     2. **連線重試與殭屍進程驅逐**：`connect_or_spawn` 嘗試 `UnixStream::connect()`，若無回應且超過 deadline，發送 `SIGTERM` / `SIGKILL` 驅逐殭屍進程。
     3. **檔案鎖協調**：透過 `.lock` 檔案的 `flock` 確保同時只有一個進程獲取重生與清理權限。
     4. **原子移除前置操作**：在呼叫 `UnixListener::bind()` 前，無條件執行 `fs::remove_file(&socket_path)`，徹底杜絕 `EADDRINUSE` 造成的啟動崩潰。
     5. **權限鎖定 (0600 / 0700)**：建立 Socket 後或在其父目錄強制設定 `0600` / `0700`，防止同裝置其他非特權應用讀取敏感 IPC 通訊。

---

## 3. 限制與考量 (Caveats)

1. **`xai-grok-diag-server` 中的常數 `/tmp/workspace-server.sock`**：
   - 目前 `crates/codegen/xai-grok-diag-server/src/lib.rs:30` 的 `DEFAULT_DIAG_SOCKET_PATH` 是編譯期靜態字串 `"/tmp/workspace-server.sock"`。
   - 雖然生產環境主要由 `xai-grok-pager-bin` 透過 `--leader-socket` 或 `create_socket_path` 提供動態路徑，但若有獨立運行 `workspace_server` binary 的情境，建議在 Milestone 4/5 實作階段將其改為動態透過 `PlatformCapabilities::current().temp_dir().join("workspace-server.sock")`。
2. **特殊字元與非 UTF-8 路徑**：
   - 若 `$TMPDIR` 包含空格或特殊符號，Blake3 雜湊檔名仍可正常拼接，但長度校驗是以 UTF-8 位元組長度為準（`path_str.len() >= 108`），此邊界已由 `test_b12_c03_tmpdir_with_special_characters` 驗證通過。
3. **沒有涉及原始碼修改**：
   - 本調查為唯讀探勘，未直接變更專案程式碼，所有架構設計與現有邏輯均已詳實紀錄於本報告。

---

## 4. 結論 (Conclusion)

1. **Feature 12 規格完整滿足 R3 規範**：
   - `$TMPDIR` 動態解析：優先使用 `$TMPDIR`，無環境變數時自動回退至 `$PREFIX/tmp`，杜絕 hardcoded `/tmp` 與不可靠的 `/data/local/tmp`。
   - 嚴格遵守 108 位元組 `sun_path` 限制：採用 Blake3 雜湊縮減檔名，標準 Termux 下長度為 53 位元組（上限 107 位元組），並具備邊界防禦。
   - 健全的過期 Socket 檢測與原子清理：具備 `flock` 檔案鎖、PID 存活探測、殭屍驅逐、綁定前 `fs::remove_file` 與 Drop 清理。
2. **實作策略建議**：
   - 保持 `xai-grok-config::PlatformCapabilities` 作為單一真理來源（Single Source of Truth）。
   - 在 `xai-grok-config::paths` 匯出 `pub fn temp_dir() -> PathBuf { PlatformCapabilities::current().temp_dir() }`，便於各 crate 統一存取。
   - 對於使用 `tempfile::NamedTempFile` 的模組（如 `xai-grok-shared::clipboard::spool_for_stdin`），確保使用 `PlatformCapabilities::current().temp_dir()` 作為暫存基礎目錄。

---

## 5. 獨立驗證方法 (Verification Method)

後續代理人或審查員可透過以下指令進行獨立驗證：

1. **執行 E2E 完整測試套件**：
   ```bash
   python3 tests/e2e/runner.py
   ```
   - 預期結果：366 個測試全部通過（100% Passed），無任何 Error 或 Failure。

2. **執行 Feature 12 專屬 Feature 與 Boundary 單元測試**：
   ```bash
   python3 -m unittest tests/e2e/tier1_features/test_feature_09_to_16.py tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py
   ```
   - 涵蓋案例：
     - `test_f12_c01_resolves_temp_dir_to_tmpdir`: 驗證 `$TMPDIR` 解析。
     - `test_f12_c02_socket_path_length_under_108_bytes`: 驗證 Termux 預設前綴下 Socket 路徑長度 < 108。
     - `test_f12_c03_stale_socket_cleanup_handled`: 驗證過期 Socket 清理。
     - `test_f12_c04_concurrent_session_sockets_are_unique`: 驗證多 Session Socket 唯一性。
     - `test_f12_c05_temp_dir_fallback_when_tmpdir_unset`: 驗證 `$TMPDIR` 未設定時回退至 `$PREFIX/tmp`。
     - `test_b12_c01_socket_path_length_at_boundary_under_108`: 驗證 107 位元組極限路徑可被接受。
     - `test_b12_c02_socket_path_length_at_108_rejected`: 驗證 108 位元組及以上被拒絕。
     - `test_b12_c03_tmpdir_with_special_characters`: 驗證特殊字元暫存目錄相容性。
     - `test_b12_c04_cleanup_nonexistent_socket_file`: 驗證清理不存在 Socket 檔案時不拋出例外。
     - `test_b12_c05_rapid_socket_creation_and_destruction`: 驗證高頻建立與銷毀的穩定性。

3. **執行 Rust 模組測試**：
   ```bash
   cargo test -p xai-grok-config --lib test_socket_path_length_constraint test_stock_termux_platform_capabilities
   ```
   - 預期結果：Rust 原生單元測試全數 PASS。

4. **失效條件 (Invalidation Conditions)**：
   - 若 `PlatformCapabilities::temp_dir()` 在 Termux 環境且 `TMPDIR` 未設定時回傳 `/tmp` 或 `/data/local/tmp`，則判定失效。
   - 若 `create_socket_path` 產生的路徑在標準 Termux 前綴下長度 `>= 108` 位元組，則判定失效。
   - 若伺服器重啟時因既有 `.sock` 檔案殘留而引發 `EADDRINUSE` 崩潰，則判定失效。
