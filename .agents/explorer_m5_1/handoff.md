# Milestone 5 探索與實作架構報告：安裝模式與更新隔離機制 (Features 27 & 28)

- **作者 / 角色**：`explorer_m5_1` (Teamwork Explorer)
- **探索目標**：Milestone 5 中 Feature 27（套件管理安裝模式 / Package-Managed Install Mode）與 Feature 28（獨立安裝模式與更新通道隔離 / Standalone Install Mode & Updater Isolation）
- **日期**：2026-08-16
- **工作目錄**：`/Users/iml1s/Documents/mine/grok-build-termux/.agents/explorer_m5_1`

---

## 1. Observation (直接觀察與程式碼剖析)

### A. 權威文件與驗收規範依據

1. **`ORIGINAL_REQUEST.md` (Line 24–25)**:
   - *Requirement 5 (Distribution, Diagnostics & Upstream Synchronization)*:
     「Implement distinct install modes (package-managed vs standalone) to prevent auto-updating into upstream Linux binaries.」
2. **`PROJECT.md` (Line 56–57, 70)**:
   - **Feature 27**: *Package-Managed Install Mode* — 偵測透過 Termux `pkg` / `apt` / `.deb` 之安裝；禁用內建二進位自我更新，提示使用者透過 `pkg upgrade grok-build` 更新。
   - **Feature 28**: *Standalone Install Mode & Updater Isolation* — 獨立安裝之更新器僅鎖定 Android/Termux 專屬發布通道（`termux-aarch64` / `aarch64-linux-android`），嚴格拒絕下載與執行桌面版 glibc Linux 二進位檔（`x86_64-unknown-linux-gnu` / `aarch64-unknown-linux-gnu`），並在替換前執行 SHA-256 Checksum 與 ELF 完整性校驗。
3. **`TEST_READY.md` 與 E2E 測試規格實作**:
   - `tests/e2e/tier1_features/test_feature_25_to_32.py` (Line 151–240):
     - `test_f27_c01` 至 `c05`: 驗證 `install_mode = "package-managed"` 識別、禁用自動下載 (`can_auto_download: false`)、回傳 `action = "delegate_to_pkg"`、訊息包含 `pkg update && pkg upgrade grok-build`、以及依據 `$PREFIX/bin` 路徑自動辨識。
     - `test_f28_c01` 至 `c05`: 驗證 `install_mode = "standalone"` 僅抓取 `termux-aarch64` 資源、拒絕只有 `linux-aarch64` 或 `linux-x86_64` 之 Manifest (`no_compatible_asset`)、下載 SHA-256 Checksum 校驗失敗即中止、以及具備 Rollback 之原子性二進位替換。
   - `tests/e2e/tier4_real_world/test_scenario_install_update_gating.py` (Line 15–69):
     - `test_scenario_package_managed_grok_update_workflow`: 模擬 `grok update` 在套件管理環境下委派給 `pkg upgrade`。
     - `test_scenario_standalone_grok_update_workflow_with_channel_filtering`: 模擬獨立更新器嚴格拒絕 upstream 桌面 Linux 發布，只採納 Termux aarch64 構建。

---

### B. 現行程式碼庫 (Existing Codebase) 觀察

#### 1. `crates/codegen/xai-grok-config/src/platform.rs`
- **現行實作 (Line 10–21, 162–277, 304–321)**:
  - `PlatformKind` 定義了 `AndroidTermux`, `UnsupportedAndroid`, `DesktopLinux`, `MacOS`, `Windows`。
  - `PlatformCapabilities::is_android_termux(&self) -> bool`：集中判定當前是否運行於 Termux。
  - `PlatformCapabilities::prefix_dir(&self) -> Result<&Path, PlatformError>`：取得 Termux `$PREFIX`（例如 `/data/data/com.termux/files/usr`）。
  - `PlatformCapabilities::bin_dir(&self) -> Result<PathBuf, PlatformError>`：取得 Termux 系統執行檔目錄 `$PREFIX/bin`。
  - `PlatformCapabilities::home_dir(&self) -> Result<PathBuf, PlatformError>`：取得使用者私人 Grok 目錄 `$HOME/.grok`。

#### 2. `crates/codegen/xai-grok-update/src/auto_update.rs`
- **安裝器型態偵測 `get_installer()` / `env_installer()` (Line 485–516)**:
  ```rust
  fn env_installer() -> Option<&'static str> {
      if let Ok(v) = std::env::var("GROK_INSTALLER") {
          return match v.to_ascii_lowercase().as_str() {
              "npm" => Some("npm"),
              "internal" => Some("internal"),
              "gh-release" | "gh" => Some("gh-release"),
              _ => None,
          };
      }
      if std::env::var_os("GROK_MANAGED_BY_NPM").is_some() {
          return Some("npm");
      }
      if std::env::var_os("GROK_MANAGED_BY_INTERNAL").is_some() {
          return Some("internal");
      }
      if std::env::var_os("npm_config_user_agent").is_some() {
          return Some("npm");
      }
      None
  }

  pub async fn get_installer() -> Option<&'static str> {
      if let Some(i) = env_installer() {
          return Some(i);
      }
      let cfg = config::load_config().await;
      match cfg.cli.installer.as_deref() {
          Some("npm") => Some("npm"),
          Some("gh-release") => Some("gh-release"),
          _ => Some("internal"),
      }
  }
  ```
  - **觀察**：現行程式碼未識別 `package-managed` / `pkg` / `apt`，亦未檢查執行檔是否位於 `$PREFIX/bin`；在 Android/Termux 上會預設回退至 `"internal"`，導致嘗試執行桌面 GCS 二進位更新。

- **平台目標偵測 `detect_platform()` (Line 993–1014)**:
  ```rust
  pub(crate) fn detect_platform() -> Result<(&'static str, &'static str)> {
      let os = if cfg!(target_os = "macos") {
          "macos"
      } else if cfg!(target_os = "linux") {
          "linux"
      } else if cfg!(target_os = "windows") {
          "windows"
      } else {
          anyhow::bail!("Unsupported OS");
      };
      let arch = if cfg!(target_arch = "x86_64") {
          "x86_64"
      } else if cfg!(target_arch = "aarch64") {
          "aarch64"
      } else {
          anyhow::bail!("Unsupported architecture");
      };
      Ok((
          os,
          corrected_arch(os, arch, running_under_rosetta_on_apple_silicon()),
      ))
  }
  ```
  - **觀察**：現行 `detect_platform()` 未處理 `cfg!(target_os = "android")`，在 Android 編譯下會直接觸發 `bail!("Unsupported OS")`；且若直接使用 Linux 標籤，會下載到桌面 glibc 之 `grok-*-linux-aarch64` 二進位檔，導致 Bionic 載入器崩潰（缺少 `ld-linux-aarch64.so.1` 與 glibc 符號）。

- **更新狀態檢查 `check_update_status()` (Line 235–300)** 與 **更新執行 `run_update()` (Line 2640–2820)**:
  - 現行流程假設所有非 npm/gh 安裝均為可下載二進位的 internal 模式。若為 `package-managed` 模式，需要攔截並回傳提示指令 `pkg update && pkg upgrade grok-build`，並禁止觸發背景下載或複寫系統二進位檔。

---

## 2. Logic Chain (推理鏈與設計決策)

```
+-------------------------------------------------------------------------+
|                  Grok Build 啟動 / 更新檢查入口                           |
|       (grok update / check_update_status / check_update_background)     |
+------------------------------------+------------------------------------+
                                     |
                    +----------------+----------------+
                    | 判定安裝模式 (Install Mode Detection) |
                    +----------------+----------------+
                                     |
              +----------------------+----------------------+
              |                                             |
   [Package-Managed Mode]                         [Standalone / Internal Mode]
   - 條件：                                         - 條件：
     * GROK_INSTALLER="pkg"/"package-managed"        * GROK_INSTALLER="internal"/"standalone"
     * GROK_INSTALL_MODE="pkg"                       * config.toml 指定 internal/standalone
     * config.toml 指定 installer="pkg"               * 執行檔位於 ~/.grok/bin/grok
     * 執行檔位於 $PREFIX/bin (Termux 系統目錄)        * 非 $PREFIX/bin 系統目錄
              |                                             |
   +----------v------------------+               +----------v------------------+
   | Feature 27: 停用自動更新    |               | Feature 28: 獨立更新器隔離  |
   +-----------------------------+               +-----------------------------+
   | 1. check_update_status 回傳: |               | 1. 目標架構隔離：             |
   |    - installer="package-    |               |    - detect_platform 回傳:   |
   |      managed"               |               |      ("termux", "aarch64")   |
   |    - can_auto_download=false|               |    - 嚴格拒絕 linux-x86_64 / |
   |    - 提示: "pkg update &&   |               |      linux-aarch64 (glibc)   |
   |      pkg upgrade grok-build"|               |    - 僅鎖定 termux-aarch64   |
   | 2. run_update:              |               | 2. 安全防護與校驗：          |
   |    - 靜態印出升級指示退出   |               |    - SHA-256 Checksum 校驗   |
   |    - 不執行網路下載與寫入   |               |    - Bionic ELF / 16K 對齊檢查|
   | 3. check_update_background: |               | 3. 原子替換與 Rollback：     |
   |    - 立即回傳 None，不派發  |               |    - ~/.grok/bin/{grok,agent}|
   |      背景下載程序           |               |      原子符號連結切換        |
   +-----------------------------+               +-----------------------------+
```

### 決策 1：安裝模式的嚴密偵測階層 (Feature 27)
1. **最高優先級（環境變數）**：
   - `GROK_INSTALLER` / `GROK_INSTALL_MODE` 為 `"pkg"`、`"package-managed"`、`"apt"`、`"deb"` 時，強制定為 `PackageManaged`。
   - `GROK_MANAGED_BY_PKG=1` 時定為 `PackageManaged`。
2. **次高優先級（設定檔 `config.toml`）**：
   - `[cli] installer = "package-managed"` 或 `"pkg"` 時定為 `PackageManaged`。
3. **本機環境與路徑自動探測（零設定自動識別）**：
   - 藉由 `PlatformCapabilities::current().is_android_termux()` 判定是否處於 Termux。
   - 若為 Termux，取得 `std::env::current_exe()` 與 `PlatformCapabilities::current().prefix_dir()`：
     - 若 `current_exe` 位於 `$PREFIX/bin` 或以 `$PREFIX` 開頭，且不在 `$HOME/.grok/` 私人目錄下，則確信為 Termux 官方套件管理員安裝（例如 `/data/data/com.termux/files/usr/bin/grok`），判定為 `PackageManaged`。
4. **行為防護**：
   - 套件管理模式下，`check_update_status` 回傳 `action = "delegate_to_pkg"`，`can_auto_download = false`，並提供標準提示：
     `"Grok Build was installed via Termux package manager. To update, run: pkg update && pkg upgrade grok-build"`。
   - `run_update` 攔截任何下載動作，印出提示後回傳 `Ok(None)`。
   - `check_update_background` 立即回傳 `BackgroundUpdateCheck::none()`，杜絕背景程序消耗行動裝置流量與記憶體。

---

### 決策 2：獨立更新器的架構隔離與資安驗證 (Feature 28)
1. **平台標籤與發布通道隔離**：
   - 在 `detect_platform()` 中加入對 Android / Termux 的支援：
     ```rust
     let os = if caps.is_android_termux() || cfg!(target_os = "android") {
         "termux"
     } else if cfg!(target_os = "macos") {
         "macos"
     } else if cfg!(target_os = "linux") {
         "linux"
     } else if cfg!(target_os = "windows") {
         "windows"
     } else {
         anyhow::bail!("Unsupported OS");
     };
     ```
   - 產生平台名稱 `termux-aarch64`（或 `termux-x86_64`）。
2. **拒絕桌面 glibc Linux 發布檔案**：
   - 解析發布清單（Release Manifest）時，嚴格搜尋 `assets["termux-aarch64"]`。
   - 若發布清單中僅包含 `linux-x86_64`、`linux-aarch64` 等 desktop glibc 標籤，立即判定為 `no_compatible_asset`，拒絕下載，避免安裝後因 ELF Interpreter (`ld-linux`) 不相容而使應用程式損毀。
3. **下載完整性校驗（Checksum & ELF Sanity）**：
   - **SHA-256 校驗**：下載二進位檔後，比對 Manifest 所宣告之 `sha256` 雜湊值；若雜湊不符，立即刪除暫存檔並終止更新。
   - **ELF 標頭驗證**：檢查 ELF 魔術數字、Bionic 動態連結器路徑（`/system/bin/linker64`）、以及 16 KiB Page-Size 對齊（`p_align >= 0x4000`）。
4. **原子替換與回復機制 (Atomic Rollback)**：
   - 下載至 `~/.grok/downloads/grok-{version}-termux-{arch}`。
   - 執行 Smoke Test (`--version`) 確認能成功啟動。
   - 原子切換 `~/.grok/bin/grok` 與 `~/.grok/bin/agent` 之符號連結；若發生錯誤，立即還原至前一版本。

---

## 3. Caveats (邊界考量與注意事項)

1. **自訂 `$PREFIX` 與 PRoot 環境**：
   - 在部分使用者設定自訂 `$PREFIX`（例如 `/data/data/custom.pkg/files/usr`）時，路徑比對必須以動態解析之 `PlatformCapabilities::current().prefix_dir()` 為準，不可寫死 `/data/data/com.termux/files/usr`。
2. **`GROK_INSTALLER` 與手動編譯開發版**：
   - 開發者在 Termux 中以 `cargo build` 本機編譯並直接執行 target 目錄下之二進位檔時，`current_exe` 不在 `$PREFIX/bin` 亦不在 `~/.grok/bin`，會被視為開發/獨立環境；若未設定 `installer`，其行為保持與 upstream 一致。
3. **無網路環境下的更新檢查**：
   - 在離線或 DNS 異常時，`check_update_status` 應優雅回傳錯誤資訊或維持現有版本，不得 panic 或阻礙主程式啟動。

---

## 4. Conclusion (結論與具體實作建議)

### 建議之模組擴充規劃

#### 1. `crates/codegen/xai-grok-update/Cargo.toml`
引入 `xai-grok-config` 依賴：
```toml
[dependencies]
xai-grok-config = { workspace = true }
```

#### 2. `crates/codegen/xai-grok-update/src/auto_update.rs` 具體修改點

```rust
// 1. 擴充環境變數與套件模式偵測
fn env_installer() -> Option<&'static str> {
    if let Ok(v) = std::env::var("GROK_INSTALLER") {
        return match v.to_ascii_lowercase().as_str() {
            "npm" => Some("npm"),
            "internal" | "standalone" => Some("internal"),
            "gh-release" | "gh" => Some("gh-release"),
            "pkg" | "package-managed" | "apt" | "deb" => Some("package-managed"),
            _ => None,
        };
    }
    if let Ok(v) = std::env::var("GROK_INSTALL_MODE") {
        return match v.to_ascii_lowercase().as_str() {
            "pkg" | "package-managed" | "apt" | "deb" => Some("package-managed"),
            "standalone" | "internal" => Some("internal"),
            _ => None,
        };
    }
    if std::env::var_os("GROK_MANAGED_BY_PKG").is_some() {
        return Some("package-managed");
    }
    if std::env::var_os("GROK_MANAGED_BY_NPM").is_some() {
        return Some("npm");
    }
    if std::env::var_os("GROK_MANAGED_BY_INTERNAL").is_some() {
        return Some("internal");
    }
    if std::env::var_os("npm_config_user_agent").is_some() {
        return Some("npm");
    }
    None
}

// 2. 整合 PlatformCapabilities 判斷 $PREFIX/bin 位置
pub async fn get_installer() -> Option<&'static str> {
    if let Some(i) = env_installer() {
        return Some(i);
    }
    let cfg = config::load_config().await;
    if let Some(ref inst) = cfg.cli.installer {
        return match inst.as_str() {
            "npm" => Some("npm"),
            "gh-release" => Some("gh-release"),
            "pkg" | "package-managed" | "apt" => Some("package-managed"),
            "standalone" | "internal" => Some("internal"),
            _ => Some("internal"),
        };
    }
    
    // 檢查執行檔是否位於 Termux $PREFIX/bin 系統套件路徑
    let caps = xai_grok_config::PlatformCapabilities::current();
    if caps.is_android_termux() {
        if let Ok(exe) = std::env::current_exe() {
            if let Ok(pfx) = caps.prefix_dir() {
                if exe.starts_with(pfx) {
                    let home = caps.home_dir().unwrap_or_default();
                    if !exe.starts_with(home) {
                        return Some("package-managed");
                    }
                }
            }
        }
    }
    Some("internal")
}

// 3. 修正 detect_platform() 支援 Termux
pub(crate) fn detect_platform() -> Result<(&'static str, &'static str)> {
    let caps = xai_grok_config::PlatformCapabilities::current();
    let os = if caps.is_android_termux() || cfg!(target_os = "android") {
        "termux"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        anyhow::bail!("Unsupported OS");
    };
    let arch = if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else {
        anyhow::bail!("Unsupported architecture");
    };
    Ok((
        os,
        corrected_arch(os, arch, running_under_rosetta_on_apple_silicon()),
    ))
}

// 4. check_update_status 與 run_update 攔截 package-managed
// 當 installer == "package-managed" 時：
// - check_update_status: update_available = false, can_auto_download = false, 附帶 delegate 指示。
// - run_update: 顯示 "Grok Build was installed via Termux package manager. To update, run: pkg update && pkg upgrade grok-build" 並安全返回 Ok(None)。
// - check_update_background: 立即返回 BackgroundUpdateCheck::none()。
```

---

## 5. Verification Method (驗證方法)

### A. E2E 測試套件驗證 (Requirement-Driven)
執行全套 4-Tier 測試，確認 Feature 27 & 28 在各層級之測試均 100% 通過：
```bash
# 1. 執行包含 F27 & F28 的 Tier 1 功能測試
python3 tests/e2e/runner.py --tier tier1

# 2. 執行包含 F27 & F28 的 Tier 2 邊界測試
python3 tests/e2e/runner.py --tier tier2

# 3. 執行包含 F27 & F28 的 Tier 4 真實情境測試
python3 tests/e2e/runner.py --tier tier4

# 4. 執行全量 E2E 測試套件 (366 測試案例)
python3 tests/e2e/runner.py
```

### B. Rust 模組測試與回歸驗證
在實作完成後，執行 `xai-grok-update` 與 `xai-grok-config` 之單元與整合測試：
```bash
# 執行 xai-grok-update 測試
cargo test -p xai-grok-update

# 執行 xai-grok-config 平台測試
cargo test -p xai-grok-config --test platform_adversarial
```

### C. 失效條件 (Invalidation Conditions)
1. 若 `grok update` 在 `$PREFIX/bin` 套件安裝環境下仍嘗試下載二進位檔並複寫系統路徑，視為 Feature 27 驗證失敗。
2. 若 Termux 獨立更新器在面對只有 `linux-aarch64` / `linux-x86_64` 的 Release Manifest 時下載了桌面 glibc 二進位檔，視為 Feature 28 驗證失敗。
3. 若下載之二進位檔 SHA-256 雜湊值不符卻仍進行符號連結切換，視為 Feature 28 驗證失敗。
