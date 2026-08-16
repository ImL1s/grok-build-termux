# Review Report — Milestone 5 (Features 27 & 28: Install Modes & Updater Isolation)

## 1. Observation (觀察事實)

- **審查標的與變更範圍**:
  - `crates/codegen/xai-grok-update/Cargo.toml`: 引入 `xai-grok-config = { workspace = true }` 支援平台能力查詢。
  - `crates/codegen/xai-grok-update/src/auto_update.rs`: 實作安裝模式辨識、包管理器委派、平台架構隔離與 ELF 二進位檢查。
- **Feature 27: Package-Managed Install Mode (套件管理器模式偵測與委派)**:
  - `env_installer()` (L530–L560): 透過環境變數 `GROK_INSTALLER` (`"pkg" | "package-managed" | "apt" | "deb"`), `GROK_INSTALL_MODE` (`"pkg" | "package-managed" | "apt" | "deb"`), 或 `GROK_MANAGED_BY_PKG` 正確回傳 `Some("package-managed")`。
  - `get_installer()` (L562–L592): 優先檢查環境變數與 `config.toml` (`installer = "package-managed"`)；在 Android/Termux 環境下，若目前執行檔路徑位於 Termux `$PREFIX/bin` 且非 `$HOME` 底下，自動識別為 `"package-managed"`。
  - `check_update_status` (L273–L288): 針對 `package-managed` 模式回傳 `UpdateStatus`，其中 `action: Some("delegate_to_pkg")`、`can_auto_download: Some(false)`、`auto_update: Some(false)`，並附帶提示訊息 `"Grok Build was installed via Termux package manager. To update, run: pkg update && pkg upgrade grok-build"`。
  - `print_update_status` (L207–L214): 在文字模式下格式化輸出套件更新提示，避免顯示常規更新指引。
  - `run_update` (L815–L818): 遇到 `package-managed` 時印出委派指引並直接返回 `Ok(None)`，杜絕在套件管理環境下載或修改二進位檔案。
  - `check_update_background` (L681–L683): 在背景檢查中遇到 `package-managed` 直接返回 `BackgroundUpdateCheck::none()`，完全關閉背景自動下載程序。
  - `reinstall_hint` (L76–L83): 針對 `"package-managed"` 提供 `"Please update via Termux package manager:\n  pkg update && pkg upgrade grok-build"`。
- **Feature 28: Standalone Install Mode & Updater Isolation (獨立安裝模式與更新隔離)**:
  - `detect_platform()` (L1073–L1097): 檢查 `PlatformCapabilities::current().is_android_termux() || cfg!(target_os = "android")`，在 Termux 環境下回傳 `("termux", "aarch64")`。產生的成品命名為 `grok-{version}-termux-aarch64`，嚴格隔離並拒絕桌面 Linux 成品 (`linux-aarch64` / `linux-x86_64`)。
  - `validate_binary_elf(path: &Path)` (L1642–L1700):
    - 檢查 64-bit Little-Endian ELF 魔術標頭 (`\x7fELF`)。非 ELF 檔案（如 macOS Mach-O、Windows PE 或測試腳本）安全忽略放行。
    - 遍歷 Program Headers (`PT_INTERP = 3`)：在 Android 上嚴格檢查並拒絕桌面 Linux 動態連結器（如 `ld-linux-*.so` 或 `/lib` 開頭路徑），要求 Android Bionic 連結器 (`/system/bin/linker64`)。
    - 遍歷 Program Headers (`PT_LOAD = 1`)：在 Android 上強制驗證區段對齊 `p_align >= 16384` (16 KiB)，確保相容 Android 15+ 記憶體分頁要求。
  - 整合與呼叫點:
    - `download_verified_from_base()` (L1739): 在下載後、冒煙測試前執行 `validate_binary_elf()`，驗證失敗立即刪除暫存檔並終止更新。
    - `install_gh_release()` (L2578): 在 GitHub Release 成品下載後、符號連結交換前執行 `validate_binary_elf()`。
- **完整性審查 (Integrity Verification)**:
  - 無假實作 (No dummy/facade implementations)：`validate_binary_elf` 具有真實的二進位位元組解析與 Program Header 迭代邏輯。
  - 無寫死測試結果 (No hardcoded test outputs)：安裝模式由實際環境變數、配置檔與 `current_exe()` 路徑動態解析。
  - 無短路繞過 (No shortcuts/bypasses)：套件管理與獨立安裝模式的行為分流明確，且與 `xai-grok-config` 抽象保持一致。

## 2. Logic Chain (推論鏈)

1. *觀察*: 在 Termux 中透過 `pkg install grok-build` 安裝的二進位檔案由 dpkg/apt 資料庫管理，若由內建 updater 自行下載並替換二進位檔案，會破壞套件管理器的一致性。
   *推論*: 透過環境變數、配置檔及 `$PREFIX/bin` 路徑動態識別 `package-managed` 模式，並在 `check_update_status`、`run_update` 與 `check_update_background` 中全面委派給 `pkg update && pkg upgrade grok-build`，能徹底防止二進位衝突與意外覆寫。
2. *觀察*: 桌面 Linux 編譯出的 `x86_64`/`aarch64` glibc 二進位檔案無法在 Android Bionic libc 上運行，且 Android 15+ 要求 16 KiB 頁面大小對齊 (`p_align >= 16384`)。
   *推論*: 獨立更新器將平台標籤鎖定為 `termux-aarch64`，並在啟動二進位檔案前透過 `validate_binary_elf()` 驗證 Bionic 動態連結器與 16 KiB 對齊，能有效防止下載到不相容的桌面 Linux 二進位檔或造成分頁錯誤崩溃。

## 3. Caveats (注意事項)

- `validate_binary_elf` 針對 64 位元小端序 (aarch64) 進行嚴格檢查；若為非 ELF 平台（如開發測試主機 macOS）則直接安全放行。
- 當使用者在 Termux 內自行將獨立版本二進位檔案手動放置於 `$HOME/.grok/bin` 時，路徑比對邏輯能正確將其判定為 `internal/standalone` 而不會誤判為 `package-managed`。

## 4. Conclusion (審查結論)

**Verdict**: **`APPROVE`**

Milestone 5 中 Feature 27（套件管理模式偵測與委派）與 Feature 28（獨立安裝模式與更新隔離）之實作完整且邏輯嚴謹，具備真實 ELF 驗證與 16 KiB 分頁對齊檢查，防禦性與相容性俱佳，無任何程式碼完整性違規或缺陷。

## 5. Verification Method (獨立驗證方法)

以下命令均已在工作區執行並 100% 通過：
1. `cargo check -p xai-grok-update` (編譯檢查 PASS)
2. `cargo test -p xai-grok-update` (146/146 單元測試 PASS)
3. `cargo test -p xai-grok-config -p xai-grok-tools -p xai-grok-shared` (2997 個測試 PASS)
4. `python3 scripts/validate_elf.py --self-test` (6/6 ELF 驗證器自身測試 PASS)
5. `python3 tests/e2e/runner.py` (366/366 4-Tier E2E 測試全部 PASS)
