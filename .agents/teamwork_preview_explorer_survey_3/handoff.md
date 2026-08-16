# 探索者調查報告：建置工具鏈、ELF 驗證與測試框架策略

**報告者**: `teamwork_preview_explorer_survey_3`  
**父節點**: `orchestrator_1` (`f8a62484-7465-4198-a94f-7093afe162ee`)  
**工作目錄**: `/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_survey_3`  
**時間**: 2026-08-15T23:32:00Z  

---

## 1. 觀察事實 (Observation)

### 1.1 主機環境與工具鏈狀態
- **Rustc 版本**: `rustc 1.88.0 (6b00bc388 2025-06-23)`
- **Cargo 版本**: `cargo 1.88.0 (873a06493 2025-05-10)`
- **已安裝之 Android Target**:
  - `aarch64-linux-android` (已安裝，主目標)
  - `x86_64-linux-android` (已安裝，模擬器/輔助目標)
  - `armv7-linux-androideabi`、`i686-linux-android` (已安裝)
- **主機已安裝之 Android NDK**:
  - `/Users/iml1s/Library/Android/sdk/ndk/28.2.13676358` (NDK r28b)
  - `/Users/iml1s/Library/Android/sdk/ndk/29.0.13113456` (NDK r29)
  - `/Users/iml1s/Library/Android/sdk/ndk/27.0.12077973` (NDK r27)
  - `/Users/iml1s/Library/Android/sdk/ndk/26.3.11579264` (NDK r26)
- **輔助建置工具**:
  - `cargo-ndk` 已就緒：`/Users/iml1s/.cargo/bin/cargo-ndk`
  - `llvm-readelf` / `llvm-objdump` / `ld.lld` 已就緒於 NDK LLVM 工具鏈及主機 `/opt/homebrew/opt/llvm@20/bin`
  - `adb` 已就緒：`/Users/iml1s/Library/Android/sdk/platform-tools/adb`

### 1.2 實測交叉編譯與 ELF 標頭分析（包含 C 擴展）
在沙盒測試專案中實測使用 NDK r28 (`API 24`) 交叉編譯包含 C 依賴 (`cc` crate) 之 Rust 程式：
- **編譯指令**:
  ```bash
  export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.2.13676358
  cargo ndk -t arm64-v8a -P 24 build --release
  ```
- **產出二進位檔**: `target/aarch64-linux-android/release/probe_crate`
- **`file` 輸出**:
  ```text
  probe_crate: ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV), dynamically linked, interpreter /system/bin/linker64, not stripped
  ```
- **`llvm-readelf -l` 程式標頭 (Program Headers)**:
  ```text
  Program Headers:
    Type           Offset   VirtAddr           PhysAddr           FileSiz  MemSiz   Flg Align
    PHDR           0x000040 0x0000000000000040 0x0000000000000040 0x000268 0x000268 R   0x8
    INTERP         0x0002a8 0x00000000000002a8 0x00000000000002a8 0x000015 0x000015 R   0x1
        [Requesting program interpreter: /system/bin/linker64]
    LOAD           0x000000 0x0000000000000000 0x0000000000000000 0x014b58 0x014b58 R   0x4000
    LOAD           0x014b58 0x0000000000018b58 0x0000000000018b58 0x03a888 0x03a888 R E 0x4000
    LOAD           0x04f3e0 0x00000000000573e0 0x00000000000573e0 0x0028e0 0x002c20 RW  0x4000
    LOAD           0x051cc0 0x000000000005dcc0 0x000000000005dcc0 0x0009b0 0x0012e8 RW  0x4000
    DYNAMIC        0x051908 0x0000000000059908 0x0000000000059908 0x000160 0x000160 RW  0x8
  ```
- **`llvm-readelf -d` 動態區段 (Dynamic Section)**:
  ```text
  0x0000000000000001 (NEEDED) Shared library: [libdl.so]
  0x0000000000000001 (NEEDED) Shared library: [libc.so]
  ```
- **實測對齊驗證**:
  - `PT_LOAD` 所有段 `Align` 皆為 `0x4000` (16,384 bytes = 16 KiB)。
  - `(VirtAddr - Offset) % 0x4000 == 0` 完全符合 Android 15+ 16 KiB 頁面載入規範。
  - `PT_INTERP` 請求 `/system/bin/linker64` (Android Bionic 動態連結器)。
  - 完全無 `libc.so.6`、`ld-linux-*.so.*` 等 glibc 依賴。

---

## 2. 邏輯推導鏈 (Logic Chain)

### 2.1 工具鏈配置策略（問題 1）
- **目標三元組**: 主力架構選定 `aarch64-linux-android`，模擬器架構選定 `x86_64-linux-android`。
- **Android API Level 選定**:
  - Termux 官方套件基底通常採用 **Android API Level 24 (Android 7.0 Nougat)**。
  - API 24 提供完整的現代 POSIX 呼叫（如 `epoll_create1`、`getauxval`、`pipe2`、`dup3`、`pthread_getname_np`、`openpty` 內建於 `libc.so`）。
  - 因此推薦使用 `aarch64-linux-android24-clang` 作為 Linker 與 C Compiler。
- **雙軌建置配置支援**:
  1. **標準 Cargo 方案 (`.cargo/config.toml` 或環境變數)**:
     ```toml
     [target.aarch64-linux-android]
     linker = "aarch64-linux-android24-clang"
     ar = "llvm-ar"
     rustflags = ["-C", "link-arg=-Wl,-z,max-page-size=16384"]

     [target.x86_64-linux-android]
     linker = "x86_64-linux-android24-clang"
     ar = "llvm-ar"
     rustflags = ["-C", "link-arg=-Wl,-z,max-page-size=16384"]
     ```
  2. **`cargo-ndk` 便捷方案**:
     `cargo ndk -t arm64-v8a -P 24 build --release`
     `cargo-ndk` 會自動向 `cc` crate 注入 `CC`、`CXX`、`AR` 與 sysroot 路徑，最適合含有原生 C 模組（如 SQLite, ring, zstd）的專案。

### 2.2 16 KiB 頁面對齊保證（問題 2）
- **Android 15+ 規範要求**:
  - Android 15 開始支援 16 KiB 記憶體分頁設備。ELF 檔案中若 `PT_LOAD` 區段對齊小於 16 KiB (0x4000)，在 16 KiB 核心上執行時 `mmap` 會失敗並引發 `SIGSEGV` 或動態連結器拒絕載入。
  - 要求條件：每個 `PT_LOAD` 的 `p_align >= 0x4000` 且 `p_vaddr % p_align == p_offset % p_align`。
- **實作保證**:
  - NDK r28+ 預設啟用 16 KiB 頁面對齊。
  - 為確保跨 NDK 版本（如 r26/r27/r28）一致性，在 `rustflags` 明確追加 `-C link-arg=-Wl,-z,max-page-size=16384`。
  - 此設定不需要任何二進位 patch 或修改 binary 內部 byte，由 LLD 連結器在輸出 ELF 時直接正確對齊。

### 2.3 ELF 標頭驗證自動化方法（問題 3）
- **驗證項目矩陣**:
  | 檢查項目 | 預期值 | 判定邏輯 | 違規行為 |
  | :--- | :--- | :--- | :--- |
  | **Magic / Class** | `\x7fELF` / 64-bit | `e_ident[4] == 2` | 非 ELF 或 32-bit |
  | **Machine** | `EM_AARCH64` (0xb7) / `EM_X86_64` (0x3e) | `e_machine == 0xb7 \| 0x3e` | 架構錯誤 |
  | **PT_INTERP** | `/system/bin/linker64` | 字串必須為 Bionic 動態載入器 | 若為 `/lib/ld-linux-*.so.*` 或 `/lib/ld-musl-*` 即判定為桌面 Linux/PRoot 雜質 |
  | **PT_LOAD 對齊** | `align >= 16384` (0x4000) | `align >= 0x4000` 且 `(vaddr % align) == (offset % align)` | 小於 16 KiB 會導致 Android 15+ 當機 |
  | **DT_NEEDED 依賴** | 僅允許 Bionic 庫 (`libc.so`, `libdl.so`, `libm.so`, `liblog.so`) | 不得包含 `libc.so.6`, `libpthread.so.0`, `ld-linux*` | 混入 glibc 執行期庫 |
  | **符號版本標籤** | 無 `GLIBC_*` 版本需求 | `.gnu.version_r` 不得有 `GLIBC_*` | 依賴 glibc 特有符號 |
  | **Android 識別** | 存在 `.note.android.ident` | 包含 `Android` OS 標籤與 NDK/API 版本 | 缺少 Android 原生元資料 |
- **實作方式**:
  - 提供輕量獨立 Python 腳本 (`scripts/validate_elf.py`) 或 Rust 測試 (`tests/elf_validation.rs`)，在 CI 與本地建置完成後 0.1 秒內完成靜態解析，無需依賴目標硬體。

### 2.4 四層測試套件設計架構 (Tier 1 - 4)（問題 4）
為達到高覆蓋率且不依賴實體 Android 手機即可在 macOS 開發主機上進行 90% 以上的驗證，設計 4-Tier 測試分層：

```
+-------------------------------------------------------------------------------+
| Tier 4: 真機 / 模擬器 E2E 整合測試 (ADB / QEMU / On-Device Termux)              |
|   - 實際在 Bionic 上執行 --version, --help, headless 任務, grok doctor        |
|   - 終端機色彩/大小調整, Ctrl+C 訊號, 背景 wake lock, Termux:API 剪貼簿互動    |
+-------------------------------------------------------------------------------+
| Tier 3: ELF 二進位靜態法醫學驗證 (Automated Binary Forensics)                    |
|   - 驗證 PT_INTERP (/system/bin/linker64), PT_LOAD 16KiB 對齊, 檢查 DT_NEEDED   |
|   - 保證零 glibc 殘留、零 musl byte-patch 殘留                                |
+-------------------------------------------------------------------------------+
| Tier 2: 交叉編譯與依賴樹防護審計 (Cargo Check & Tree Gate)                      |
|   - cargo check --target aarch64-linux-android                                |
|   - 依賴樹防護：驗證 jemalloc, arboard, cpal, alsa-sys 徹底不在依賴樹中       |
+-------------------------------------------------------------------------------+
| Tier 1: 主機端 Mock-Termux 單元與路徑測試 (Host macOS / Linux `cargo test`)      |
|   - 可注入的 PlatformContext / EnvContext                                     |
|   - 模擬 $PREFIX/etc/grok, $HOME/.grok, $TMPDIR                               |
|   - 嚴格阻擋 /sdcard, /storage/emulated/0 寫入私密金鑰與設定                   |
|   - 模擬 Mock Termux:API (termux-open-url, termux-clipboard-get/set)          |
|   - 驗證 OAuth callback, doctor 診斷輸出, 沙盒回報 policy-only                |
+-------------------------------------------------------------------------------+
```

### 2.5 潛在工具鏈障礙與建置調適（問題 5）
1. **記憶體配置器 (Allocator)**:
   - 桌面版常使用的 `jemalloc` / `tikv-jemallocator` 在 Android Bionic 上建置極易失敗或產生 16 KiB 頁面衝突。
   - **處理解法**: 在 Android 目標上徹底剔除 `tikv-jemallocator`，使用 Android Bionic 原生配置器（Android 現代 Bionic 已內建高效率 Scudo / jemalloc 實作）。
   - 程式碼範例：
     ```rust
     #[cfg(all(unix, not(target_os = "android")))]
     #[global_allocator]
     static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
     ```
2. **桌面專屬 Crate 隔離**:
   - `arboard` (剪貼簿)：依賴 X11/Wayland/AppKit，Android 上無法運作。
     - **處理解法**: 使用 `#[cfg(not(target_os = "android"))]` 隔離；Android 端透過 Termux:API (`termux-clipboard-*`) 與 ANSI OSC 52 跳脫序列實作純終端剪貼簿。
   - `cpal` (音訊/語音)：依賴 ALSA/CoreAudio。
     - **處理解法**: Android 端首發版本透過 capability 將 voice 功能關閉，不編譯 `cpal`。
3. **C 依賴庫（OpenSSL, SQLite, zstd, ring）編譯問題**:
   - TLS/Crypto 推薦優先採用 `rustls` + `ring`（純 Rust / ring 原生支援 Android NDK Clang）。
   - 若必須使用 OpenSSL，需啟用 `vendored` 特性避免尋找主機 OpenSSL 標頭檔。
   - SQLite 啟用 `bundled` 特性，讓 `cc` crate 自動使用 NDK Clang 編譯。
4. **沙盒權限與 PRoot 誤區**:
   - Android 沙盒已由系統 UID (`u0_aXXX`) 隔離，非 root 無法執行 `unshare(CLONE_NEWUSER)` 建立使用者命名空間。
   - 嚴禁偽造「已啟動核心沙盒」之宣告；`grok doctor` 與安全性模組應如實回報為 `policy-only`（基於路徑與許可權的政策防護）。
5. **工作區 Manifest 與上游同步衝突最小化**:
   - 上游根目錄 `Cargo.toml` 為自動生成，應盡量避免在根目錄大幅增修。
   - 透過子 crate 內部的 `[target.'cfg(...)'.dependencies]` 與建置指令 `--no-default-features --features ...` 來控制 Android 專屬相依性。

---

## 3. 限制與假設 (Caveats)

1. **Android 7.0 (API 24) 以下版本不在支援範圍**:
   - 由於 64-bit ARM 且支援現代 POSIX 呼叫，API 24 為合理的最低標準（現行 Termux 官方亦已不支援 Android 6 以下）。
2. **實體硬體測試環境**:
   - 本調查在 macOS 開發主機上完成工具鏈交叉編譯與 ELF 標頭驗證。真機測試 (Tier 4) 需在具備 ADB 連線之 Android 14/15 設備或 Termux App 環境中執行。
3. **非 Termux 之其他 Android 環境（如普通 adb shell）**:
   - 在無 Termux `$PREFIX` 之純 Android shell 下，執行時應由 `PlatformContext` 優雅退化，提示缺少 Termux 環境變數，而非崩潰。

---

## 4. 結論與具體決策 (Conclusion)

1. **建置設定**:
   - 採用 **Android NDK r28b+**，API Level 鎖定 **24** (`aarch64-linux-android24-clang`)。
   - 連結旗標統一加入 `-Wl,-z,max-page-size=16384` 保證 16 KiB ELF 頁面對齊，完美相容 Android 15+。
   - 建置指令標準化為：
     ```bash
     cargo ndk -t arm64-v8a -P 24 build --release --no-default-features --features termux
     ```
2. **ELF 驗證機制**:
   - 建立自動化驗證腳本 `scripts/validate_elf.py` 作為 CI Release Gate，確保 100% 符規（Bionic linker、16K 對齊、零 glibc）。
3. **測試策略**:
   - 採用 4-Tier 測試分層架構，以可注入的 `PlatformContext` 讓主機端測試覆蓋 90% 以上的 Termux 路徑、沙盒政策、OAuth 模擬與能力退化邏輯。

---

## 5. 獨立驗證方法 (Verification Method)

### 5.1 驗證交叉編譯與 C 擴展相容性
```bash
export ANDROID_NDK_HOME=/Users/iml1s/Library/Android/sdk/ndk/28.2.13676358
cargo ndk -t arm64-v8a -P 24 build --release --manifest-path /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_survey_3/probe_crate/Cargo.toml
```

### 5.2 驗證 ELF 標頭與 16 KiB 頁面對齊
```bash
/Users/iml1s/Library/Android/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-readelf -l -d /Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_survey_3/probe_crate/target/aarch64-linux-android/release/probe_crate
```
**預期結果**:
- `INTERP`: `/system/bin/linker64`
- 所有 `LOAD` 段之 `Align` 為 `0x4000` (16384 bytes)
- `DYNAMIC` 之 `NEEDED` 僅有 `libc.so` / `libdl.so`，無 `libc.so.6`

### 5.3 執行自動化 ELF 驗證腳本
```bash
python3 -c "
import struct
with open('/Users/iml1s/Documents/mine/grok-build-termux/.agents/teamwork_preview_explorer_survey_3/probe_crate/target/aarch64-linux-android/release/probe_crate', 'rb') as f:
    data = f.read()
e_phoff, e_phentsize, e_phnum = struct.unpack('<QQQ', data[32:56])[0], struct.unpack('<H', data[54:56])[0], struct.unpack('<H', data[56:58])[0]
for i in range(e_phnum):
    p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack('<IIQQQQQQ', data[e_phoff+i*56:e_phoff+(i+1)*56])
    if p_type == 1:
        assert p_align >= 16384 and (p_vaddr % p_align == p_offset % p_align), f'Alignment failure on segment {i}'
print('ELF 16 KiB Page Alignment Verification PASSED!')
"
```
