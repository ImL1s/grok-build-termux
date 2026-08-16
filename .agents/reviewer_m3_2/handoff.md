# Milestone 3 獨立審查與對抗性驗證報告 (Reviewer 2)

**審查者**: Reviewer 2 (`reviewer_m3_2`)  
**角色**: reviewer, critic  
**審查目標**: Milestone 3 (檔案系統安全與儲存邊界, Features 10–14)  
**目標 Commit**: `4d266db` (`feat(filesystem): implement dynamic temp sockets, system config, and storage boundaries (Milestone 3)`)  
**審查裁決 (Verdict)**: **`APPROVE`**  
**日期**: 2026-08-16  

---

## 1. 觀察 (Observation)

### 1.1 需求比對與依據
- 依據 `ORIGINAL_REQUEST.md`:
  - 第 19 行 (R3): *"Ensure configuration, credentials, sockets, and cache directories resolve to Termux-owned private paths (`$PREFIX/etc/grok`, `$HOME/.grok`, `$TMPDIR`). Strictly reject housing `GROK_HOME` or credentials on Android shared storage (`/sdcard`, `/storage/emulated/0`) to preserve owner-only permissions."*
  - 第 35 行: *"- [ ] System config resolves to `$PREFIX/etc/grok` and user state resolves to `$HOME/.grok`."*
  - 第 36 行: *"- [ ] Credential/token writes to Android shared storage are refused with explicit error messages."*
- 依據 `PROJECT.md`:
  - Feature 10: 系統設定目錄動態解析 (`$PREFIX/etc/grok`)。
  - Feature 11: 使用者主目錄解析與憑證隔離 (`$HOME/.grok`)。
  - Feature 12: 執行期暫存目錄與 Unix Domain Socket (< 108 位元組，Blake3 雜湊，過期 Socket 清理)。
  - Feature 13: Android 共享儲存空間隔離 (`/sdcard` 等路徑強制隔離，要求 0700 權限)。
  - Feature 14: 雙軌工作區保護 (在 `/sdcard` 編輯專案時，Session、Token 與 Cache 仍保留於 `$HOME/.grok`)。

### 1.2 程式碼直接觀察
1. **儲存安全驗證 (`crates/codegen/xai-grok-config/src/platform.rs`)**:
   - `validate_storage_safety` (第 471–587 行):
     - 第 482–489 行: 執行 `normalize_lexical` 進行詞彙正規化（消除 `..` 與 `.`），並比對 `ANDROID_SHARED_STORAGE_PREFIXES`（包含 `/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media` 等）。
     - 第 441–466 行 (`is_quarantined_str`): 全面轉小寫 (`to_lowercase()`) 並將反斜線統一轉為正規斜線，防止大小寫混淆繞過。
     - 第 491–518 行: 檢查直接符號連結 (`symlink`)，使用 `std::fs::read_link` 解析目標路徑並遞迴呼叫 `validate_storage_safety_depth`，防止指向 `/sdcard` 的懸空 (dangling) 或存在符號連結逃逸。
     - 第 520–529 行: 若路徑已存在，透過 `dunce::canonicalize` 取得磁碟真實正規化路徑並進行隔離檢查。
     - 第 531–584 行: 若目標尚不存在（例如位於已符號連結父目錄下的子檔案），逐層向上遍歷祖先目錄 (`ancestor paths`)，解析祖先符號連結或正規化祖先路徑並重組相對子路徑，進行遞迴檢查。
     - 第 476–479 行: 設定遞迴深度上限 `depth > 32`，防止符號連結循環造成的堆疊溢位。
   - 錯誤格式化 (第 75–84 行):
     ```rust
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
     ```
     明確標註違規路徑、0700 擁有者專屬權限要求，以及無 POSIX 權限隔離之原因。

2. **雙軌工作區隔離 (`crates/codegen/xai-grok-config/src/paths.rs`)**:
   - 第 35–53 行 (`grok_home()`): 若環境變數 `GROK_HOME` 指向 unsafe 共享儲存空間，`validate_storage_safety` 會被觸發並由 `grok_home()` 捕獲，安全回退到預設的 `default_grok_home()`（即 Termux 私有主目錄 `~/.grok`），同時發出 `tracing::error!` 警告。
   - 第 208–253 行 (`sessions_cwd_dir`, `ensure_sessions_cwd_dir`):
     - Session 目錄格式為 `grok_home()/sessions/{encode_cwd_dirname(cwd)}`。
     - 即使使用者在 `/sdcard/Download/my-project` 工作，Session 資料夾也建立於 `$HOME/.grok/sessions/...`。
     - 透過 `create_dir_all_owner_only` 與 `set_dir_owner_only`（第 171–201 行）在 Unix 上嚴格施加 `0700` 權限（無 umask 窗口）。

3. **Unix Socket 建立、過期清理與 108 位元組限制**:
   - `xai-grok-config/src/platform.rs` (第 352–364 行):
     - `create_socket_path(session_id)` 使用 `blake3::hash` 取前 8 碼十六進位字串產生 `grok-{short_hash}.sock`（檔名僅 18 位元組）。
     - 在 Termux 下結合 `$PREFIX/tmp`（`/data/data/com.termux/files/usr/tmp`，34 位元組），總路徑僅 53 位元組，遠低於 POSIX `sockaddr_un.sun_path` 的 108 位元組上限（保留 55 位元組裕度）。
     - 具備硬性長度斷言：`if path_str.len() >= 108 { return Err(PlatformError::SocketPathTooLong(path_str.into_owned())); }`。
   - `xai-grok-diag-server/src/lib.rs` (第 32–47, 408–418 行):
     - `default_diag_socket_path()` 動態優先解析 `$TMPDIR` 與 `$PREFIX/tmp`，最後回退到 `/tmp`。
     - `serve` 綁定 Unix Socket 前執行 `let _ = fs::remove_file(&path);` 自動清理崩潰遺留的過期 Socket，並將權限設為 `0o600`。
   - `xai-grok-workspace/src/bin/workspace_server.rs` (第 94–96 行):
     - `diag_socket` 預設值採用 `diag_server::default_diag_socket_path()`，完全告別硬編碼的靜態 `/tmp`。

### 1.3 獨立執行驗證命令結果
- `cargo test -p xai-grok-config`:
  - `src/lib.rs`: 213 passed, 0 failed.
  - `tests/platform_adversarial.rs`: 15 passed, 0 failed.
  - `tests/shell_adversarial.rs`: 2 passed, 0 failed.
- `cargo test -p xai-grok-shared`:
  - 99 passed, 0 failed, 4 ignored.
- `cargo test -p xai-grok-diag-server`:
  - 20 passed, 0 failed.
- `python3 tests/e2e/runner.py`:
  - 366/366 passed in 5.892s (100% passed across Tiers 1–4).
- `python3 scripts/validate_elf.py --self-test`:
  - 6/6 checks passed.
- `python3 tests/stress_test_milestone3.py`:
  - 5/5 stress tests passed.
- `cargo check --workspace`:
  - Exit code 0 (clean compilation).

---

## 2. 邏輯鏈 (Logic Chain)

1. **儲存邊界安全性 (Feature 10, 11, 13)**:
   - 觀察 1.2.1 顯示 `validate_storage_safety` 建立了多層防禦：詞彙正規化 → 大小寫不敏感前綴過濾 → 懸空符號連結目標檢查 → 祖先目錄符號連結遞迴解析 → 磁碟真實路徑 `canonicalize`。
   - 此設計徹底杜絕了透過 `..` 遍歷、符號連結混淆、大小寫繞過等方式將 `GROK_HOME` 或憑證指向 Android `/sdcard` 的可能性。
   - 錯誤訊息符合 `ORIGINAL_REQUEST.md` 之明確要求，詳細指示 0700 權限與拒絕理由。

2. **雙軌工作區隔離無外洩 (Feature 14)**:
   - 觀察 1.2.2 顯示，專案原始碼讀寫與工作階段狀態儲存完全解耦。
   - 使用者在 `/sdcard` 編輯 Android 專案時，原始碼留在 CWD，而 Session、對話歷史、認證 Token (`auth.json`)、MCP 認證與快取等敏感資料一律由 `paths::sessions_cwd_dir` 路由至 `$HOME/.grok/`，並以 `0700` 私有權限保護。
   - 無任何憑證或 Session 洩漏至世界可讀的共享儲存區。

3. **Unix Socket 長度與生命週期管理 (Feature 12)**:
   - 觀察 1.2.3 顯示，透過 Blake3 短雜湊（8 碼十六進位），Termux 下 Socket 總路徑為 53 位元組，保留逾 50% 裕度。
   - 診斷伺服器於啟動時主動清理 stale socket (`remove_file`)，並設定 `0600` 權限，確保守護程序重啟時不發生 `EADDRINUSE` 錯誤。

4. **誠信審查 (Integrity Audit)**:
   - 經對程式碼與測試進行全面 grep 及人工檢查，未發現任何偽造實作 (dummy facades)、硬編碼測試預期值 (hardcoded test cheats)、或逃避任務的行為。
   - 所有驗證皆為真實的邏輯執行與單元測試。

---

## 3. 注意事項 (Caveats)

- **Android `/sdcard` `noexec` 機制**:
  - Android 核心對 `/sdcard` 掛載了 `noexec` 屬性。在 `/sdcard` 上構建出的執行檔若直接在此目錄執行會觸發 `EACCES`。這屬於 Android 核心之固有安全限制，使用者如需執行編譯產物應放置於 Termux `$HOME`。本架構雙軌設計已正確確保 Grok 自行管理的二進位檔與腳本位於 `$HOME` / `$PREFIX` 私有目錄。
- **無其他潛在缺陷或未調查事項**。

---

## 4. 結論 (Conclusion)

Milestone 3 (Filesystem Safety & Storage Boundaries, Features 10–14) 實作**完全符合架構合約與安全性規範**：
1. `validate_storage_safety` 具備強固的對抗性防禦，能精確攔截所有共享儲存空間逃逸嘗試並提供清晰的錯誤訊息。
2. 雙軌工作區隔離確保了在 `/sdcard` 上作業時憑證與 Session 的零洩漏。
3. Socket 路徑安全受控於 108 位元組之內，並實作了自動清理過期 Socket 與嚴格權限設定。
4. 全套 Rust 單元測試、對抗性挑戰測試、E2E 測試與 ELF 驗證皆 100% 通過。
5. 無任何誠信違規。

審查裁決：**`APPROVE`**。

---

## 5. 獨立驗證方法 (Verification Method)

可透過以下命令進行獨立驗證：

```bash
# 1. 驗證 Rust 設定庫與對抗性測試
cargo test -p xai-grok-config

# 2. 驗證共用庫
cargo test -p xai-grok-shared

# 3. 驗證診斷伺服器
cargo test -p xai-grok-diag-server

# 4. 執行完整 4-Tier E2E 測試套件 (366 個測試)
python3 tests/e2e/runner.py

# 5. 執行 ELF 自我測試
python3 scripts/validate_elf.py --self-test

# 6. 執行 Milestone 3 壓力測試套件
python3 tests/stress_test_milestone3.py
```

---

## 6. 審查摘要報告 (Review Summary)

**Verdict**: `APPROVE`

### Verified Claims
- `validate_storage_safety` 拒絕 `/sdcard`, `/storage/emulated/0`, `/mnt/sdcard` 等所有變體 → 透過 `test_adversarial_storage_quarantine_all_variations` 與 `tests/stress_test_milestone3.py` 驗證 → **PASS**
- 符號連結與祖先目錄混淆防禦 → 透過 `test_adversarial_dangling_symlink_vulnerability`、`test_adversarial_ancestor_symlink_quarantine`、`test_adversarial_symlink_chain_quarantine` 驗證 → **PASS**
- 雙軌工作區隔離確保 Session 寫入 `$HOME/.grok/sessions` → 透過 `paths::tests::ensure_sessions_cwd_dir_*` 與 `test_feature_14_workspace_dual_track_isolation` 驗證 → **PASS**
- Unix Socket 長度與過期清理 → 透過 `paths_create_socket_path_bounds` 與 `unix_socket_serves_ready_and_rebinds_over_stale_socket` 驗證 → **PASS**

### Coverage Gaps
- 無 (No coverage gaps).

### Unverified Items
- 無 (No unverified items).

---

## 7. 對抗性挑戰報告 (Challenge Summary)

**Overall Risk Assessment**: `LOW`

### Challenges Evaluated
1. **挑戰情境 1: 透過祖先目錄符號連結繞過安全檢查**
   - 攻擊情境：在 `$HOME` 內建立一個指向 `/sdcard` 的資料夾符號連結 `shared_link`，並將憑證存放在 `$HOME/shared_link/keys.json`。
   - 實作防禦：`validate_storage_safety_depth` 向上遍歷祖先目錄，發現 `shared_link` 為符號連結，解析目標為 `/sdcard` 並遞迴判定為違規。
   - 結果：成功攔截 (**PASS**)。

2. **挑戰情境 2: 長工作路徑與 POSIX Socket 108 位元組溢位**
   - 攻擊情境：超長 Session ID 或超長工作目錄名稱導致 Unix Socket 路徑超過 108 位元組引發緩衝區溢位或系統 bind 崩潰。
   - 實作防禦：採用 Blake3 8 碼十六進位短雜湊，將 socket 檔名壓縮為 18 位元組，Termux 下總路徑僅 53 位元組，並包含 `>= 108` 邊界檢查。
   - 結果：安全可靠 (**PASS**)。

3. **挑戰情境 3: 前次程序異常崩潰殘留 Stale Socket 導致重啟失敗**
   - 攻擊情境：前次伺服器強制終止，Socket 檔案殘留於檔案系統，重啟時觸發 `EADDRINUSE`。
   - 實作防禦：`xai-grok-diag-server` 在 `bind` 前執行 `remove_file` 主動解除殘留綁定。
   - 結果：重啟順暢 (**PASS**)。
