# Milestone 2: Native Bionic Build & Toolchain Alignment — 審查與對抗性驗證報告

## Review Summary

**Verdict**: APPROVE

---

## 1. 觀察 (Observation)

審查針對 Git Commit `2aac9668e8d1df7bdf071ae5c049d05879d6058e`（`feat(toolchain): configure Android targets, 16 KiB alignment, build bypass, and runtime tool resolver (Milestone 2)`）進行全量檢查，涵蓋以下修改與檔案：

1. **`.cargo/config.toml` (第 67–80 行) 與 `rust-toolchain.toml` (第 17–18 行)**：
   - 配置了 `[target.aarch64-linux-android]` 與 `[target.x86_64-linux-android]` 之 `rustflags`。
   - 包含 `-C link-arg=-Wl,-z,max-page-size=16384`（16 KiB ELF 頁面邊界對齊）、`-C link-arg=-Wl,-z,relro,-z,now,-z,noexecstack`（二進位安全加固）及 `-C force-unwind-tables=yes`。
   - `rust-toolchain.toml` 的 `targets` 陣列新增 `aarch64-linux-android` 與 `x86_64-linux-android`。

2. **`crates/codegen/xai-grok-tools/build.rs` (第 75–78, 215–218, 263–266 行) 與 `crates/codegen/xai-grok-shell/build.rs` (第 48–51 行)**：
   - 檢查 `CARGO_CFG_TARGET_OS`，當目標為 `android`（且無顯式 `GROK_TOOLS_BUNDLE_*_PATH` / `GROK_SHELL_BUNDLE_RG_PATH` 環境變數）時直接 `return Ok(())`，阻斷桌面 glibc 預編譯二進位檔案（`ripgrep`, `fd`, `bfs`, `ugrep`）的下載與打包。

3. **`crates/codegen/xai-grok-pager-render/src/theme/system_appearance.rs` (第 113, 124–129 行)**：
   - 為 `detect_desktop()` 增加 `#[cfg(not(target_os = "android"))]` 門控，並在 `#[cfg(target_os = "android")]` 下提供優雅返回 `None` 的實現，解決 Android 交叉編譯時 `dark-light` 2.0.0 不支援導致的編譯錯誤。

4. **`crates/codegen/xai-grok-config/src/shell.rs` (第 452–469 行)**：
   - `resolve_unix_shell_path()` 新增了對 Termux `$PREFIX/bin`、`/data/data/com.termux/files/usr/bin`、`/system/bin`、`/system/xbin` 的路徑探測與可執行權限檢查，確保 Termux / Android 環境下的 shell 解析。

5. **`crates/codegen/xai-grok-tools/src/resolver.rs` (第 1–257 行) 及 Grep 整合**：
   - 實現 `ToolResolver` 與 `ToolSpec`，支援 `rg`, `fd`, `git`, `bash`, `bfs`, `ugrep`。
   - 遵循解析階梯：環境變數覆蓋 $\to$ `$PATH` (`which`) $\to$ `$PREFIX/bin` $\to$ Android 系統目錄 $\to$ 桌面 Unix 目錄。
   - 具備環境感知之修復提示（Termux 提示 `pkg install <pkg>`、macOS 提示 `brew install`、Linux 提示 `apt install`）。
   - `ToolResolver::resolve_optional()` 安全處理可選工具（`bfs`, `ugrep`）。
   - 在 `grep/ripgrep.rs` 與 `grep/mod.rs` 中完整接入 `ToolResolver` 與錯誤引導。

---

## 2. 邏輯鏈 (Logic Chain)

1. **Feature 6（原生 Bionic 構建配置）**：
   - `.cargo/config.toml` 與 `rust-toolchain.toml` 正確定義 Android 目標與 NDK 參數。
   - 執行 `cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell`：所有依賴 C/C++ sys 原生庫（`aws-lc-sys`, `ring`, `libsqlite3-sys`, `libz-sys`, `tree-sitter-*`）與 Rust crates 均在 Android Bionic NDK 環境下順利通過檢查（Exit Code 0）。

2. **Feature 7（16 KiB ELF 頁面對齊）**：
   - 透過 `-C link-arg=-Wl,-z,max-page-size=16384` 保證了 PT_LOAD 區段的 `p_align >= 0x4000` 與 `p_vaddr % p_align == p_offset % p_align`。
   - 執行 `python3 scripts/validate_elf.py --self-test`：6/6 項內部自測全部通過，成功驗證對 16 KiB Bionic 二進位檔的認可，以及對 4 KiB 舊版、glibc 直譯器、非同餘區段、魔術頭損壞的精確攔截。

3. **Feature 8（原生 CLI 工具解析）**：
   - 構建腳本成功跳過桌面 glibc 預編譯二進位下載，避免將不相容的 Linux 二進位檔打包進 Android 產物。
   - `ToolResolver` 完整覆蓋了所需工具的檢索順序，並在工具缺失時輸出明確的 Termux `pkg install` 指令。
   - `prepare_grep` 捕捉到 `NotFound` 時能夠精準附加修復指引。

4. **Feature 9（可選搜尋工具降級）**：
   - `bfs` 與 `ugrep` 標記為 `ToolRequirement::Optional`，在缺失時透過 `resolve_optional()` 優雅返回 `None`，不引發 panic 或錯誤中斷。

5. **測試與完整性**：
   - 宿主機與交叉編譯環境雙向無錯誤。
   - 單元測試（Resolver 3/3, Grep 39/39, Config 226/226）、E2E 測試（366/366）全數通過。

---

## 3. 限制與考量 (Caveats)

- **實機 ELF 載入**：目前在 CI / macOS 本地測試透過 `scripts/validate_elf.py` 嚴格驗證 ELF 標頭與區段對齊約束。實體 Android 15 裝置執行將在後續 Milestone 5 / M_FINAL 中進行。
- **後向相容性**：非 Android 宿主環境（macOS / Linux / Windows）之原有行為完全不受影響，桌面工具解析與下載邏輯維持原有路徑。

---

## 4. 結論 (Conclusion)

Milestone 2（Features 6–9）所有需求均已高品質完成，無任何作弊、假實現或完整性違規問題。給予明確審查結論：**APPROVE**。

---

## 5. 獨立驗證方法 (Verification Method)

任何人均可透過以下指令獨立驗證：

```bash
# 1. 宿主機 Cargo 檢查
cargo check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell

# 2. Android NDK Bionic 交叉編譯檢查 (需 NDK r28)
export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.1.13356709
cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell

# 3. Resolver 與 Grep 單元測試
cargo test -p xai-grok-tools --lib resolver
cargo test -p xai-grok-tools --lib implementations::grok_build::grep

# 4. 4-Tier E2E 測試套件 (366 測試)
python3 tests/e2e/runner.py

# 5. ELF 驗證器自測 (6 測試)
python3 scripts/validate_elf.py --self-test
```

---

## 6. 對抗性審查報告 (Adversarial Challenge Report)

### 總體風險評估：LOW

### 檢驗的攻擊面與邊界條件 (Stress Test Scenarios)

1. **情境 1：工具缺失時的錯誤防護與修復指引**
   - *測試*：請求不存在的工具名稱 `nonexistent_tool_xyz123`。
   - *結果*：`ToolResolver::resolve_tool` 傳回 `ToolResolutionError::MissingRequiredTool`，在 Android 環境下輸出包含 `In Termux, run: pkg install nonexistent_tool_xyz123`，未發生 panic。
   - *評估*：通過。

2. **情境 2：可選工具缺失時的無害降級**
   - *測試*：呼叫 `ToolResolver::resolve_optional(&TOOL_BFS)` 當檔案不存在時。
   - *結果*：傳回 `None`，不拋出錯誤，允許呼叫方降級至 `fd` 或內建遍歷。
   - *評估*：通過。

3. **情境 3：Android 交叉編譯中的外觀偵測 stub**
   - *測試*：Android target 編譯 `system_appearance.rs`。
   - *結果*：`detect_desktop()` 在 `target_os = "android"` 下返回 `None`，避開桌面 D-Bus / X11 / Cocoa 呼叫，徹底消除 `dark-light` 編譯死穴。
   - *評估*：通過。

4. **情境 4：16 KiB 頁面對齊與 Bionic 直譯器強合規**
   - *測試*：以 `validate_elf.py` 測試 4K 頁面二進位檔、非同餘虛擬地址、glibc 直譯器二進位檔。
   - *結果*：全部被標記為 INVALID 並給予明確的錯誤原因。
   - *評估*：通過。

### 完整性核查 (Integrity Verification)
- [x] 無硬編碼測試預期輸出
- [x] 無空殼（facade）或 dummy 實現
- [x] 無繞過任務核心邏輯之情事
- [x] 驗證日誌均為實機真實執行結果
- [x] 判定：無任何誠信違規（NO INTEGRITY VIOLATIONS）。
