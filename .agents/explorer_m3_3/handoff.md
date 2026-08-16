# Milestone 3 調查報告：共用儲存區隔離（Feature 13）與共用儲存區工作區防護（Feature 14）

本報告針對 **Milestone 3 (Filesystem Safety & Storage Boundaries)** 的核心功能：**共用儲存區隔離 (Feature 13: Shared Storage Quarantine)** 與 **共用儲存區工作區防護 (Feature 14: Shared-Storage Workspace Protection)** 進行深度程式碼剖析、安全邊界驗證與實作策略彙整。

---

## 1. 觀察 (Observation)

### 1.1 儲存安全性驗證函式與錯誤型別
在 `crates/codegen/xai-grok-config/src/platform.rs` 中，定義了核心防護函式 `validate_storage_safety` 及相關型別：

- **錯誤型別定義 (`platform.rs:75-84`)**：
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
  該錯誤訊息清晰指明：
  1. 具體被拒絕的路徑 (`path`)；
  2. 拒絕的核心安全理由（需要 0700 擁有者專屬權限以保護憑證）；
  3. 底層機制原因（例如 Android 共用儲存區無法強制執行 POSIX 使用者/群組權限且可被其他 App 存取）。

- **共用儲存區前綴比對清單 (`platform.rs:388-401`)**：
  ```rust
  const ANDROID_SHARED_STORAGE_PREFIXES: &[&str] = &[
      "/sdcard",
      "/storage",
      "/mnt/sdcard",
      "/mnt/media_rw",
      "/data/sdcard",
      "/data/media",
      "sdcard",
      "storage",
      "mnt/sdcard",
      "mnt/media_rw",
      "data/sdcard",
      "data/media",
  ];
  ```

- **字串檢查與正規化比對 (`platform.rs:441-466`)**：
  ```rust
  fn is_quarantined_str(norm_str: &str) -> bool {
      let lower = norm_str.to_lowercase();
      let lower = lower.replace('\\', "/");

      for prefix in ANDROID_SHARED_STORAGE_PREFIXES {
          if lower == *prefix
              || lower.starts_with(&format!("{prefix}/"))
              || (prefix.starts_with('/') && lower.starts_with(prefix))
          {
              return true;
          }
      }

      if lower.contains("/sdcard")
          || lower.contains("/storage/")
          || lower == "/storage"
          || lower.contains("/storage/emulated")
          || lower.contains("/storage/self")
          || lower.contains("/mnt/sdcard")
          || lower.contains("/mnt/media_rw")
      {
          return true;
      }

      false
  }
  ```

- **深層防護驗證邏輯 (`platform.rs:471-587`)**：
  `validate_storage_safety` 包含多層防禦：
  1. **詞彙正規化 (Lexical Normalization)**：透過 `normalize_lexical(path)` 解析 `.` 與 `..`，阻斷如 `/data/data/com.termux/files/home/../../../../sdcard/.grok` 等穿越字元序列。
  2. **符號連結直接檢查 (Direct Symlink Resolution)**：使用 `std::fs::read_link` 檢查既有與懸空 (dangling) 符號連結，防止透過指向 `/sdcard` 的符號連結規避檢查。
  3. **磁碟標準化 (Disk Canonicalization)**：對已存在的目標使用 `dunce::canonicalize` 解析最終實際路徑。
  4. **祖先目錄符號連結巡檢 (Ancestor Directory Symlink Traversal)**：若目標檔案尚未建立，逐層往上檢查既有父目錄是否為指向共用儲存區的符號連結。
  5. **遞迴深度限制**：`depth > 32` 防止符號連結迴圈造成無限遞迴。

### 1.2 `PlatformCapabilities` 與路徑解析整合
在 `crates/codegen/xai-grok-config/src/platform.rs` 與 `crates/codegen/xai-grok-config/src/paths.rs`：

- **`PlatformCapabilities::home_dir` (`platform.rs:337-346`)**：
  ```rust
  pub fn home_dir(&self) -> Result<PathBuf, PlatformError> {
      if let Some(ref gh) = self.grok_home_env {
          validate_storage_safety(gh)?;
          return Ok(gh.clone());
      }
      let user_home = self.home.as_ref().ok_or(PlatformError::MissingHome)?;
      let gh = user_home.join(".grok");
      validate_storage_safety(&gh)?;
      Ok(gh)
  }
  ```
  當使用者在環境變數設定 `GROK_HOME=/sdcard/.grok` 時，`home_dir()` 嚴格拒絕並回傳 `Err(PlatformError::StorageSafety(...))`。

- **`paths::grok_home` 安全回退 (`paths.rs:35-53`)**：
  ```rust
  pub fn grok_home() -> PathBuf {
      GROK_HOME
          .get_or_init(|| {
              let grok_home = if let Ok(v) = std::env::var("GROK_HOME") {
                  let p = PathBuf::from(v);
                  if let Err(e) = crate::platform::validate_storage_safety(&p) {
                      tracing::error!(error = %e, "Rejected insecure GROK_HOME location; falling back to default");
                      default_grok_home()
                  } else {
                      p
                  }
              } else {
                  default_grok_home()
              };
              let _ = std::fs::create_dir_all(&grok_home);
              grok_home
          })
          .clone()
  }
  ```
  當 `GROK_HOME` 指向不安全的共用儲存區時，`grok_home()` 會記錄明確錯誤日誌，並自動回退至安全的 Termux 私有主目錄 `default_grok_home()` (`$HOME/.grok`)。

### 1.3 工作區狀態、連線階段與憑證的私有隔離
檢視工作區與連線階段相關 crate（`xai-grok-config`, `xai-grok-workspace`, `xai-grok-shell`, `xai-grok-mcp`）：

- **工作區連線階段路徑映射 (`paths.rs:198-206`)**：
  ```rust
  pub fn sessions_cwd_dir(cwd: &str) -> PathBuf {
      sessions_cwd_dir_in(&grok_home(), cwd)
  }

  pub fn sessions_cwd_dir_in(grok_home: &std::path::Path, cwd: &str) -> PathBuf {
      grok_home.join("sessions").join(encode_cwd_dirname(cwd))
  }
  ```
  無論工作區 `cwd` 位於何處（例如 `/sdcard/Download/my-project`），該專案的所有連線階段 (sessions) 永遠儲存在 `$GROK_HOME/sessions/{encoded_cwd}/`，即 Termux 私有應用程式目錄 `/data/data/com.termux/files/home/.grok/sessions/...`。

- **目錄權限自我修復 (`paths.rs:178-191`)**：
  `create_dir_all_owner_only` 與 `set_dir_owner_only` 在 Unix 上建立目錄時原生以 `0700` 建立（無 umask 暴露窗口），並在每次存取時對 `sessions/` 根目錄與工作區子目錄進行權限收緊修復。

- **提示詞歷史紀錄 (`xai-grok-shell/src/session/prompt_history.rs:28-37`)**：
  歷史紀錄儲存於 `sessions_cwd_dir(cwd).join(PROMPT_HISTORY_FILE)`，位置位於私有 `$HOME/.grok/sessions/.../prompt_history.json`。

- **權限授權狀態 (`xai-grok-workspace/src/permission/state.rs:165-172`)**：
  工作區工具授權儲存在 `xai_grok_config::ensure_sessions_cwd_dir(&root)`，同樣被隔離於 `$HOME/.grok/sessions/` 中。

- **認證金鑰與 OAuth 權杖 (`xai-grok-pager`, `xai-grok-mcp`)**：
  - 登入權杖：`$GROK_HOME/auth.json` (0600 權限)。
  - MCP OAuth 權杖：`$GROK_HOME/mcp_credentials.json` (0600 權限)。
  - 雲端設定簽章快取：`$GROK_HOME/requirements.toml`。
  - Worktrees 資料庫：`$GROK_HOME/worktrees.db`。

- **臨時檔案與 Unix Domain Socket (`platform.rs:348-364`)**：
  Socket 檔案固定建於 `temp_dir()`（即 `$TMPDIR` 或 `$PREFIX/tmp` = `/data/data/com.termux/files/usr/tmp`），檔名為 `grok-{short_hash}.sock`，保證字節長度嚴格小於 108 bytes（避免 `sockaddr_un` 緩衝區溢位），絕不會建立於 `/sdcard`。

### 1.4 測試套件驗證結果
- `cargo test -p xai-grok-config`:
  - 211 個單元測試全數通過（含 `test_storage_safety_quarantine_rejections`, `test_dangling_symlink_quarantine_unit`, `test_lexical_traversal_quarantine_unit`, `test_relative_path_prefix_quarantine_unit`, `test_case_insensitive_matching_unit`, `test_valid_termux_paths_accepted_unit`）。
  - `tests/platform_adversarial.rs`: 15 個對抗性測試全數通過（涵蓋各種大小寫變體、穿越路徑、祖先目錄符號連結、符號連結鏈、並行 MockEnv 壓力測試）。
- Python E2E 測試套件（`tests/e2e/runner.py`）：
  - `test_feature_09_to_16.py`（包含 F13 與 F14 共 10 個測試）：全部 PASS。
  - `test_boundaries_09_to_16.py`（包含 F13 與 F14 邊界測試 10 個）：全部 PASS。
  - `test_scenario_storage_quarantine.py`（Scenario 3 實機場景測試 2 個）：全部 PASS。

---

## 2. 邏輯鏈 (Logic Chain)

1. **Android 共用儲存區的安全弱點 (Security Vulnerability)**：
   Android 外接/共用儲存區（`/sdcard`, `/storage/emulated/0`, `/storage/*`, `/mnt/media_rw/*`）採用 FAT32/exFAT 或 FUSE/sdcardfs 仿真層，不具備 POSIX 擁有者存取控制（DAC 權限 `0700`/`0600` 無法生效）。所有獲取 `READ_EXTERNAL_STORAGE` 或 `MANAGE_EXTERNAL_STORAGE` 權限的第三方應用程式皆可讀取該處所有檔案。
   
2. **Feature 13 的防禦機制與明確錯誤通報 (Quarantine Logic)**：
   基於觀察 1.1 與 1.2，`validate_storage_safety` 在程式啟動或解析路徑時介入：
   - 藉由 `is_quarantined_str` 覆蓋全部 Android 共用儲存區前綴及關鍵字變體。
   - 藉由 `normalize_lexical`、`dunce::canonicalize` 與祖先目錄檢查，封堵 `..` 穿越與符號連結欺騙漏洞。
   - 當偵測到危險路徑時，拋出 `StorageSafetyError::SharedStorageQuarantine`，錯誤訊息精確告知「0700 擁有者權限為憑證所必需」以及「共用儲存區不支援 POSIX 權限且可被其他 App 讀取」，完全消除晦澀不明的錯誤回報。

3. **Feature 14 的雙軌隔離架構 (Dual-Track Workspace Isolation)**：
   基於觀察 1.3：
   - **軌道一（使用者原始碼）**：使用者在 `/sdcard/Download/my-project` 中的檔案操作（讀取、編輯、語法解析、Git diff）直接於該工作區執行，滿足使用者跨 Android 編輯器查看專案的需求。
   - **軌道二（敏感狀態與憑證）**：所有連線階段快照 (`sessions/`)、提示詞歷史 (`prompt_history.json`)、OAuth 權杖 (`auth.json`)、MCP 認證 (`mcp_credentials.json`)、工具授權狀態 (`permissions.json`) 與 IPC 通訊通訊端 (`$TMPDIR/*.sock`)，一律透過 `grok_home()` 與 `temp_dir()` 強制收容於 Termux 專屬私有資料目錄（`/data/data/com.termux/files/home/.grok` 及 `/data/data/com.termux/files/usr/tmp`）。
   
4. **結論支撐**：
   此雙軌架構既保證了 `/sdcard` 工作區的正常運作，又從架構上完全杜絕了敏感資料與憑證外洩至共用儲存區的可能。

---

## 3. 注意事項與限制 (Caveats)

1. **Android 共用儲存區的 `noexec` 限制**：
   Android 核心對 `/sdcard` 掛載點強制加上 `noexec` 旗標。若使用者在 `/sdcard` 工作區中嘗試編譯並直接在該處執行原生執行檔（如 `target/debug/my_app`），系統 `execve` 呼叫將遭核心拒絕（`EACCES: Permission denied`）。這是 Android 系統層級限制，非 Grok Build 的 bug。建議需執行的二進位檔案置於 Termux 私有儲存區（`$HOME`）內。
2. **`xai-fast-worktree` 獨立性注意**：
   `crates/codegen/xai-fast-worktree/src/db/mod.rs` 中的 `resolve_grok_home()` 為獨立實作（避免引入過多依賴），但其路徑解析原則與 `xai_grok_config::paths` 保持一致。
3. **路徑長度與 CWD 編碼**：
   在 `/sdcard` 上過深的中文/特殊字元目錄，透過 `encode_cwd_dirname` 的 Blake3 雜湊機制收斂為 `<= 57 bytes` 的目錄名，並在內部以 `.cwd` 記錄原路徑，相容 FAT32/ext4 檔名長度限制。

---

## 4. 結論 (Conclusion)

1. **Feature 13（共用儲存區隔離）完整驗證**：
   `validate_storage_safety` 與 `PlatformCapabilities::home_dir()`、`paths::grok_home()` 已建立嚴密的防禦體系，能精確阻擋 `/sdcard`、`/storage/emulated/0`、`/mnt/sdcard`、`/storage/*` 等共用儲存路徑，阻斷符號連結與路徑穿越攻擊，並產生清楚且具教育性的安全錯誤訊息。
2. **Feature 14（共用儲存區工作區防護）架構健全**：
   Grok Build 採用嚴格的「工作區程式碼與工作階段狀態分離」架構。使用者於 `/sdcard` 工作區內作業時，所有 session state、OAuth/API tokens、git credentials、shell history、worktree DB、permissions 與 temporary sockets 皆全數隔離保存在 Termux 私有資料夾（`$HOME/.grok` 與 `$TMPDIR`），符合 Milestone 3 之安全性與合規標準。

---

## 5. 獨立驗證方法 (Verification Method)

可執行以下命令獨立驗證：

1. **Rust 單元測試與對抗性安全測試**：
   ```bash
   cargo test -p xai-grok-config --test platform_adversarial
   cargo test -p xai-grok-config
   ```
2. **Python E2E 測試（Feature 13 & 14 與 Storage Quarantine Scenario）**：
   ```bash
   python3 -m unittest tests/e2e/tier1_features/test_feature_09_to_16.py
   python3 -m unittest tests/e2e/tier2_boundaries/test_boundaries_09_to_16.py
   python3 -m unittest tests/e2e/tier4_real_world/test_scenario_storage_quarantine.py
   ```
3. **全量 E2E 測試套件執行**：
   ```bash
   python3 tests/e2e/runner.py
   ```
