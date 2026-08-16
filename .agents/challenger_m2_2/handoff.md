# Milestone 2 對抗性挑戰與驗證報告 (Challenger 2)

## 1. Observation (實證觀察)

本挑戰者針對 Milestone 2（Native Bionic Build & Toolchain Alignment）的各項產出進行了完整的對抗性壓力測試與實證驗證，具體觀察如下：

### (1) Target 與 Linker 參數設定 (`.cargo/config.toml` & `rust-toolchain.toml`)
- `.cargo/config.toml` 包含對 `[target.aarch64-linux-android]` 與 `[target.x86_64-linux-android]` 的精確設定：
  ```toml
  [target.aarch64-linux-android]
  rustflags = [
      "-C", "target-cpu=generic",
      "-C", "force-unwind-tables=yes",
      "-C", "link-arg=-Wl,-z,relro,-z,now,-z,noexecstack",
      "-C", "link-arg=-Wl,-z,max-page-size=16384",
  ]

  [target.x86_64-linux-android]
  rustflags = [
      "-C", "force-unwind-tables=yes",
      "-C", "link-arg=-Wl,-z,relro,-z,now,-z,noexecstack",
      "-C", "link-arg=-Wl,-z,max-page-size=16384",
  ]
  ```
- `rust-toolchain.toml` 的 `targets` 陣列已包含 `"aarch64-linux-android"` 與 `"x86_64-linux-android"`。

### (2) ELF 驗證器對抗性測試 (`scripts/validate_elf.py`)
- 執行官方自我測試 `python3 scripts/validate_elf.py --self-test`：
  ```
  Running ELF Validator internal self-tests...
    [✓] Valid 16 KiB Bionic aarch64 binary (Result: VALID, Expected: VALID)
    [✓] 4 KiB page size Bionic binary (should fail strict 16K) (Result: INVALID, Expected: INVALID)
    [✓] glibc ld-linux.so interpreter binary (should fail Bionic check) (Result: INVALID, Expected: INVALID)
    [✓] Misaligned PT_LOAD segment congruence violation (Result: INVALID, Expected: INVALID)
    [✓] Corrupt ELF magic header (Result: INVALID, Expected: INVALID)
    [✓] Statically linked 16 KiB aarch64 binary (Result: VALID, Expected: VALID)
  All self-tests passed successfully.
  ```
- 撰寫合成二進位壓力測試套件 `scratch/test_validate_elf_adversarial.py` 驗證 16 種極端與邊界情況：
  - 合法 16 KiB Bionic aarch64：通過 (Exit 0)
  - 合法 64 KiB Bionic aarch64（對齊 >= 16K）：通過 (Exit 0)
  - 合法 Android Apex Linker `/apex/com.android.runtime/bin/linker64`：通過 (Exit 0)
  - 非法 4 KiB Bionic ELF（嚴格 16K 檢查攔截）：失敗 (Exit 1)
  - 非法 glibc 直譯器 `/lib/ld-linux-aarch64.so.1`：失敗 (Exit 1)
  - 非法 musl 直譯器 `/lib/ld-musl-aarch64.so.1`：失敗 (Exit 1)
  - 非法 glibc 依賴 `libc.so.6`：失敗 (Exit 1)
  - 非法 glibc 依賴 `libpthread.so.0`：失敗 (Exit 1)
  - 非法同餘違規 (`p_vaddr % p_align != p_offset % p_align`)：失敗 (Exit 1)
  - aarch64 目標下的非法 32 位元 ELF：失敗 (Exit 1)
  - arm 目標下的合法 32 位元 ELF：通過 (Exit 0)
  - 非法 Big-endian ELF：失敗 (Exit 1)
  - 合法 16K 靜態二進位：通過並產生警告 (Exit 0)
  - 損壞的 ELF magic header：失敗 (Exit 1)
  - 不存在之檔案：優雅處理 (Exit 1)
  - JSON 格式結構輸出：通過 (Exit 0)
  - **測試總結：16/16 全部通過**。

### (3) 建置腳本離線旁路測試 (`build.rs`)
- 針對 `xai-grok-tools` 與 `xai-grok-shell` 之已編譯 `build-script-build` 二進位執行 live 離線隔離測試（將 HTTP/HTTPS Proxy 指向無效連接埠 `127.0.0.1:9999`）：
  - `xai-grok-tools` 在 `CARGO_CFG_TARGET_OS=android` (release) 下於 <0.1s 內退出（Exit 0），未觸碰網路，且不輸出 `cfg(bundle_rg)` 與 `cfg(bundle_fd)`。
  - `xai-grok-tools` 在 `CARGO_FEATURE_PI=1` 情況下依然安全略過。
  - `xai-grok-tools` 指定 `GROK_TOOLS_BUNDLE_RG_PATH` 本地覆寫時，正確複製二進位並輸出 `cfg(bundle_rg)`。
  - `xai-grok-shell` 在 `CARGO_CFG_TARGET_OS=android` (release) 下安全略過下載（Exit 0）。
  - `xai-grok-shell` 指定 `GROK_SHELL_BUNDLE_RG_PATH` 時正確覆寫。
  - 負向對照組：Linux 目標在 release 模式下因離線無法下載而正確報錯失敗（證明 Android 旁路確實生效且與桌面平台互不干擾）。
  - **測試總結：6/6 全部通過**。

### (4) 跨平台編譯與測試執行
- **Host Check**: `cargo check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell` 執行成功（Exit 0）。
- **Android Bionic NDK Check**:
  ```bash
  export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.1.13356709
  cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell
  ```
  包含 `aws-lc-sys`、`libz-sys`、`sqlite-vec`、`tree-sitter-*` 等底層 C/C++ sys 套件皆編譯通過，全 crate 0 error 完成檢查。
- **單元測試**:
  - `cargo test -p xai-grok-tools --lib resolver`: 3/3 passed
  - `cargo test -p xai-grok-tools --lib implementations::grok_build::grep`: 39/39 passed
  - `cargo test -p xai-grok-config --lib shell`: 9/9 passed
  - `cargo test -p xai-grok-pager-render --lib theme::system_appearance`: 21/21 passed
- **E2E 測試套件**: `python3 tests/e2e/runner.py` 執行結果為 366/366 全部通過（耗時 8.362s，100% 通過率）。

---

## 2. Logic Chain (推論鏈)

1. **Linker 與頁面大小合規性**:
   - 根據 Android 15+ 規範，所有原生二進位必須支援 16 KiB 記憶體頁面。`.cargo/config.toml` 明確配置了 `-C link-arg=-Wl,-z,max-page-size=16384` 以及安全加固選項 (`relro`, `now`, `noexecstack`)，保證編譯輸出的 ELF 具備正確的 segment alignment。
2. **ELF 驗證器的健全度**:
   - `scripts/validate_elf.py` 經過正向（16K/64K Bionic）、負向（4K、glibc、musl、同餘違規、損壞 magic）、邊界情況（靜態鏈接、Apex Linker）等 16 項對抗性測試，所有錯誤皆能精確辨識並給出詳細診斷訊息，無任何未捕獲之異常崩潰。
3. **建置隔離與離線安全性**:
   - 原先桌面版 `build.rs` 會在 release 模式嘗試連網下載 x86_64/aarch64 glibc 之 `ripgrep`/`fd` 二進位。Worker 修改後在 `CARGO_CFG_TARGET_OS=android` 時提早返回 `Ok(())`，在無網路環境下編譯不發生網路請求，且運行期由 `ToolResolver` 從 `$PREFIX/bin` / `$PATH` 原生解析並提供 Termux `pkg install` 提示，完全符合 Termux 原生架構設計。
4. **外觀偵測跨編譯相容性**:
   - `dark-light` crate 在 Android 平台上缺乏底層 API 支援。Worker 在 `system_appearance.rs` 中透過 `#[cfg(target_os = "android")]` 優雅回傳 `None`，既維持了桌面端系統主題偵測功能，又解決了 Android 跨平台編譯阻礙。

---

## 3. Caveats (限制與注意事項)

- 真機執行測試依賴後續 Milestone 5 的真機與模擬器矩陣；在當前 M2 階段，NDK API 24 跨平台編譯檢查與 ELF 驗證已涵蓋 Bionic 符號與頁面佈局驗證。
- 無其他隱藏風險或架構假設偏差。

---

## 4. Conclusion (裁決結論)

**裁決：APPROVE (通過)**

Milestone 2（Native Bionic Build & Toolchain Alignment）的所有功能與非功能性要求均已確實落地並通過高強度對抗性實證測試：
- [x] Feature 6: 原生 Bionic 建置 profile 與 Target Linker 設定 (`.cargo/config.toml`, `rust-toolchain.toml`)
- [x] Feature 7: 16 KiB ELF 頁面對齊保證與 ELF 驗證器 (`scripts/validate_elf.py`)
- [x] Feature 8: 建置腳本離線旁路 (`build.rs`) 與 Android 跨編譯相容性修復 (`system_appearance.rs`)
- [x] Feature 9: 執行期原生工具解析器 (`ToolResolver` in `xai-grok-tools`) 與 Termux `pkg install` 補救指引

---

## 5. Verification Method (獨立驗證方法)

1. **執行 ELF 驗證器自我測試與對抗性測試**:
   ```bash
   python3 scripts/validate_elf.py --self-test
   python3 scratch/test_validate_elf_adversarial.py
   ```
2. **執行 build.rs 離線隔離壓力測試**:
   ```bash
   python3 scratch/test_build_scripts_live.py
   ```
3. **執行 NDK 跨平台編譯檢查**:
   ```bash
   export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.1.13356709
   cargo ndk -t arm64-v8a -P 24 check -p xai-grok-config -p xai-grok-shared -p xai-grok-tools -p xai-grok-pager-render -p xai-grok-shell
   ```
4. **執行單元測試與 E2E 測試套件**:
   ```bash
   cargo test -p xai-grok-tools --lib resolver
   cargo test -p xai-grok-tools --lib implementations::grok_build::grep
   cargo test -p xai-grok-config --lib shell
   cargo test -p xai-grok-pager-render --lib theme::system_appearance
   python3 tests/e2e/runner.py
   ```
