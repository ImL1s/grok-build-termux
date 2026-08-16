# Handoff Report: Milestone 2 — Build Script Investigation & Desktop Tool Download Bypass

## 1. Observation

針對工作區所有 crate 的 `build.rs`、二進制打包與工具解析機制進行了完整普查，觀測結果如下：

### 1.1 工作區中所有 `build.rs` 檔案清單

| # | 檔案路徑 | 作用 | 是否涉及網路下載/二進制嵌入 |
|---|---|---|---|
| 1 | `crates/codegen/xai-grok-tools/build.rs` | 下載/嵌入 `rg` (15.0.0), `fd` (10.4.2), 嵌入 `bfs` (4.1), `ugrep` (7.7.0) | **是 (核心調查目標)** |
| 2 | `crates/codegen/xai-grok-shell/build.rs` | 下載/嵌入 `rg` (15.0.0) | **是 (核心調查目標)** |
| 3 | `crates/codegen/xai-grok-tools-api/build.rs` | 透過 `xai_proto_build` 編譯 `proto/grok-tools.proto` | 否 (純 protobuf 程式碼生成) |
| 4 | `crates/codegen/xai-grok-pager/build.rs` | 透過 `git rev-parse` 與 `GROK_VERSION` 注入版本環境變數 | 否 (純元資料) |
| 5 | `crates/codegen/xai-grok-pager-bin/build.rs` | 注入版本與 commit hash 環境變數 | 否 (純元資料) |
| 6 | `crates/codegen/xai-grok-version/build.rs` | 監聽 `GROK_VERSION` 環境變數變更 | 否 (純元資料) |

---

### 1.2 `crates/codegen/xai-grok-tools/build.rs` 詳細觀測

檔案位置：`crates/codegen/xai-grok-tools/build.rs` (352 行)

#### (A) `main()` 進入點 (第 41–53 行)
```rust
fn main() -> Result<(), Box<dyn std::error::Error>> {
    bundle_rg()?;
    // fd is an optional vendored file-search binary backing a feature-gated
    // toolset; skip the download/embed entirely when that feature is off
    // (shipped TUI binaries).
    if env::var_os("CARGO_FEATURE_PI").is_some() {
        bundle_fd()?;
    }
    // bfs/ugrep back the bash-harness find/grep shadows (embedded_search_tools).
    bundle_search_tool("bfs", "BFS", BFS_VER)?;
    bundle_search_tool("ugrep", "UGREP", UGREP_VER)?;
    Ok(())
}
```

#### (B) `bundle_rg()` 下載與目標判定 (第 236–295 行)
```rust
fn bundle_rg() -> Result<(), Box<dyn std::error::Error>> {
    // Only bundle in release builds to avoid slowing down cargo check.
    println!("cargo:rerun-if-env-changed=GROK_TOOLS_BUNDLE_RG_PATH");
    println!("cargo:rustc-check-cfg=cfg(bundle_rg)");

    let gen_dir = PathBuf::from(env::var("OUT_DIR")?).join("bundle-rg");
    fs::create_dir_all(&gen_dir)?;

    let path_override = env::var("GROK_TOOLS_BUNDLE_RG_PATH").ok();
    let is_release = env::var("PROFILE").as_deref() == Ok("release");
    if path_override.is_none() && !is_release {
        return Ok(());
    }

    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os == "windows" && path_override.is_none() {
        return Ok(());
    }

    // Expose cfg so the crate can include the bundled bytes.
    println!("cargo:rustc-cfg=bundle_rg");
    println!("cargo:rustc-env=GROK_TOOLS_RG_VER={}", RG_VER);

    if let Some(path) = path_override {
        ...
        return Ok(());
    }

    let target_arch = env::var("CARGO_CFG_TARGET_ARCH").unwrap_or_default();
    let asset_triple = match (target_os.as_str(), target_arch.as_str()) {
        ("macos", "aarch64") => "aarch64-apple-darwin",
        ("macos", "x86_64") => "x86_64-apple-darwin",
        ("linux", "x86_64") => "x86_64-unknown-linux-musl",
        ("linux", "aarch64") => "aarch64-unknown-linux-gnu",
        _ => {
            return Err(format!(
                "Unsupported target for ripgrep bundling: {os}-{arch}. Set GROK_TOOLS_BUNDLE_RG_PATH to a local rg binary for offline or unsupported builds.",
                os = target_os,
                arch = target_arch
            ).into());
        }
    };
```

#### (C) `bundle_fd()` 下載與目標判定 (第 59–96 行)
```rust
fn bundle_fd() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-env-changed=GROK_TOOLS_BUNDLE_FD_PATH");
    println!("cargo:rustc-check-cfg=cfg(bundle_fd)");

    let gen_dir = PathBuf::from(env::var("OUT_DIR")?).join("bundle-fd");
    fs::create_dir_all(&gen_dir)?;

    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os == "windows" {
        return Ok(());
    }

    let path_override = env::var("GROK_TOOLS_BUNDLE_FD_PATH").ok();
    let is_release = env::var("PROFILE").as_deref() == Ok("release");
    if path_override.is_none() && !is_release {
        return Ok(());
    }

    let target_arch = env::var("CARGO_CFG_TARGET_ARCH").unwrap_or_default();
    let (ver, asset_triple) = match (target_os.as_str(), target_arch.as_str()) {
        ("macos", "aarch64") => (FD_VER, "aarch64-apple-darwin"),
        ("macos", "x86_64") => (FD_VER_MACOS_X64, "x86_64-apple-darwin"),
        ("linux", "x86_64") => (FD_VER, "x86_64-unknown-linux-musl"),
        ("linux", "aarch64") => (FD_VER, "aarch64-unknown-linux-musl"),
        _ => {
            if path_override.is_none() {
                return Err(format!(
                    "Unsupported target for fd bundling: {target_os}-{target_arch}. Set GROK_TOOLS_BUNDLE_FD_PATH to a local fd binary for offline or unsupported builds.",
                )
                .into());
            }
            (FD_VER, "override")
        }
    };
```

#### (D) `bundle_search_tool` (`bfs`, `ugrep`) 邏輯 (第 201–232 行)
```rust
fn bundle_search_tool(
    name: &str,
    name_uc: &str,
    ver: &str,
) -> Result<(), Box<dyn std::error::Error>> {
    let override_env = format!("GROK_TOOLS_BUNDLE_{name_uc}_PATH");
    println!("cargo:rerun-if-env-changed={override_env}");
    println!("cargo:rustc-check-cfg=cfg(bundle_{name})");

    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        return Ok(());
    }

    let Some(src) = env::var(&override_env).ok().filter(|s| !s.is_empty()) else {
        return Ok(());
    };
...
```

---

### 1.3 `crates/codegen/xai-grok-shell/build.rs` 詳細觀測

檔案位置：`crates/codegen/xai-grok-shell/build.rs` (167 行)
- 第 51–54 行：
  ```rust
  let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
  if target_os == "windows" && path_override.is_none() {
      return Ok(());
  }
  ```
- 第 57 行：發出 `println!("cargo:rustc-cfg=bundle_rg");`
- 第 81–93 行：
  ```rust
  let asset_triple = match (target_os.as_str(), target_arch.as_str()) {
      ("macos", "aarch64") => "aarch64-apple-darwin",
      ("macos", "x86_64") => "x86_64-apple-darwin",
      ("linux", "x86_64") => "x86_64-unknown-linux-musl",
      ("linux", "aarch64") => "aarch64-unknown-linux-gnu",
      _ => {
          return Err(format!(
              "Unsupported target for ripgrep bundling: {os}-{arch}. Set GROK_SHELL_BUNDLE_RG_PATH to a local rg binary for offline or unsupported builds.",
              os = target_os,
              arch = target_arch
          ).into());
      }
  };
  ```

---

### 1.4 執行期二進制解析觀測

#### (A) Ripgrep (`rg`) 解析：`crates/codegen/xai-grok-tools/src/implementations/grok_build/grep/ripgrep.rs`
- 第 4–12 行：
  ```rust
  #[cfg(bundle_rg)]
  const RG_BYTES: &[u8] = include_bytes!(concat!(
      env!("OUT_DIR"),
      "/bundle-rg/rg-",
      env!("GROK_TOOLS_RG_VER"),
      "-",
      env!("GROK_TOOLS_RG_TARGET"),
      ".bin"
  ));
  ```
- 第 43–81 行：
  ```rust
  pub fn rg_path() -> PathBuf {
      static RG_EXEC: OnceLock<PathBuf> = OnceLock::new();
      RG_EXEC
          .get_or_init(|| {
              #[cfg(bundle_rg)]
              {
                  resolve_bundled_rg().unwrap_or_else(|_| PathBuf::from("rg"))
              }
              #[cfg(not(bundle_rg))]
              {
                  if let Ok(p) = std::env::var("RG_BIN_PATH") {
                      return PathBuf::from(p);
                  }
                  ...
                  PathBuf::from("rg")
              }
          })
          .clone()
  }
  ```

#### (B) 搜尋工具 (`bfs`, `ugrep`) 解析：`crates/codegen/xai-grok-tools/src/computer/local/embedded_search_tools.rs`
- 當 `cfg(not(bundle_bfs))` 時，`bundled_bfs()` 直接返回 `None` (第 182–186 行)。
- 當 `cfg(not(bundle_ugrep))` 時，`bundled_ugrep()` 直接返回 `None` (第 203–207 行)。
- `resolve_tool_from` 會自動依序檢查：環境變數覆蓋 → bundled → `~/.grok/vendor/<bin>` → `which::which(bin_name)` (第 223–241 行)。
- 注入的 shell 函式會在執行時動態調用 `command -v bfs` / `command -v ugrep`，若未安裝則透明無損地 fallback 至系統的 `command find` 與 `command grep` (第 297–311 行)。

---

## 2. Logic Chain

1. **觸發機制剖析**：
   - 上游為桌面環境（macOS, Linux glibc/musl）設計了自動下載機制：當 `PROFILE == "release"` 時，`build.rs` 會透過 `reqwest::blocking` 從 GitHub Releases 下載預編譯的 `ripgrep` 與 `fd` tarball。
   - 解壓縮後的二進制檔存放於 `OUT_DIR`，並發出 `cargo:rustc-cfg=bundle_rg` / `cargo:rustc-cfg=bundle_fd`。
   - `rustc` 編譯 crate 時，`include_bytes!` 巨集將這些二進制檔案直接編譯進可執行檔本體。

2. **Android/Termux 目標下的致命衝突**：
   - 當以 `aarch64-linux-android` 或 `x86_64-linux-android` 作為 target 進行 cross-compilation 時，Cargo 設定的 `CARGO_CFG_TARGET_OS` 為 `"android"`。
   - 目前 `build.rs` 僅對 `target_os == "windows"` 進行早退（early return）。因此在 `target_os == "android"` 時，程式碼不會早退，而是進入 `match (target_os, target_arch)`，因無匹配項而拋出 `Err("Unsupported target for ripgrep bundling: android-aarch64...")`，直接導致 release 編譯中斷。
   - 即使強行下載 Linux 的 `aarch64-unknown-linux-gnu` 或 `aarch64-unknown-linux-musl` 二進制檔：
     - **動態連結器不相容**：桌面 Linux 二進制檔依賴 glibc dynamic loader (`/lib/ld-linux-aarch64.so.1`) 或 musl (`/lib/ld-musl-aarch64.so.1`)，在原生 Android Bionic 系統（動態連結器為 `/system/bin/linker64`）上執行會直接回報 `ENOENT (No such file or directory)` 或崩潰。
     - **記憶體分頁對齊衝突**：Android 15+ 要求 ELF 二進制檔必須符合 16 KiB 分頁對齊 (`p_align >= 0x4000`)。預編譯的桌面 Linux 二進制檔為 4 KiB 對齊，會被 Android 核心拒絕載入。
     - **體積浪費與架構冗餘**：Termux 官方套件庫已原生提供針對 Bionic 編譯並符合 16 KiB 對齊的 `ripgrep` (`rg`)、`fd`、`git`、`bash`、`bfs`、`ugrep`，安裝於 `$PREFIX/bin/`。

3. **旁路與門控解決方案 (Bypass & Gating Mechanism)**：
   - 參照 Windows 的處理機制，在 `build.rs` 發出 `cargo:rustc-cfg=bundle_*` **之前**，判定 `target_os == "android"`。
   - 當 `target_os == "android"` 且未手動指定本機路徑覆蓋（`path_override.is_none()`）時，立即執行 `return Ok(())`。
   - 此舉產生三個關鍵效果：
     - **無網路請求**：交叉編譯環境不需要對外連線下載 GitHub Release。
     - **未發出 cfg**：不發出 `cargo:rustc-cfg=bundle_rg`、`cargo:rustc-cfg=bundle_fd`。
     - **編譯期完全排除**：`include_bytes!` 巨集所在的 `#[cfg(bundle_rg)]` 區塊完全不被 rustc 編譯，消除了數十 MB 的二進制體積膨脹，且在 release 模式下保證 0 錯誤。
   - 執行期時，`#[cfg(not(bundle_rg))]` 區塊生效，`rg_path()` 返回 `PathBuf::from("rg")`，由執行期行程環境變數 `$PATH` 直接解析 Termux 原生安裝的 `/data/data/com.termux/files/usr/bin/rg`。

---

## 3. Caveats

1. **手動本機覆蓋變數支援**：
   - 若使用者或發行管道顯式設置了 `GROK_TOOLS_BUNDLE_RG_PATH=/path/to/custom/bionic_rg`，目前的門控條件 `(target_os == "windows" || target_os == "android") && path_override.is_none()` 保留了手動覆蓋的能力，會將使用者提供的原生 Bionic 二進制檔打包嵌入。這保持了與上游管線的最大靈活性。
2. **`xai-grok-shell` vs `xai-grok-tools` 雙重打包歷史殘留**：
   - `xai-grok-shell/build.rs` 包含早期的 ripgrep 下載邏輯，雖然目前執行期主要由 `xai-grok-tools` 與 `xai-grok-workspace` 提供 `rg_path()`，但 `xai-grok-shell/build.rs` 仍會在 release 編譯時執行。因此**兩個 crate 的 `build.rs` 必須同時加入 Android 門控**，缺一不可。
3. **`bfs` 與 `ugrep` 狀態**：
   - `bundle_search_tool` 本身預設就是無下載行為（若無環境變數覆蓋即跳過），但在 `build.rs` 中加入 `target_os == "android"` 檢查可確保無論上游 CI 如何配置，都不會誤嵌桌面靜態二進制檔。

---

## 4. Conclusion & Implementation Strategy

### 4.1 具體修改方案 (Concrete Code Diffs)

#### (1) 修改 `crates/codegen/xai-grok-tools/build.rs`

```diff
--- a/crates/codegen/xai-grok-tools/build.rs
+++ b/crates/codegen/xai-grok-tools/build.rs
@@ -66,8 +66,8 @@ fn bundle_fd() -> Result<(), Box<dyn std::error::Error>> {
     // The consuming vendor extraction is unix-only — never bundle on
     // Windows targets, mirroring the bfs/ugrep skip.
     let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
-    if target_os == "windows" {
+    if (target_os == "windows" || target_os == "android") && path_override.is_none() {
         return Ok(());
     }

     let path_override = env::var("GROK_TOOLS_BUNDLE_FD_PATH").ok();
@@ -211,7 +211,8 @@ fn bundle_search_tool(
     // The consumer (`embedded_search_tools`) is `#[cfg(unix)]`, so embedding on a
     // Windows target is dead weight — skip (mirrors the ripgrep Windows skip).
-    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
+    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
+    if target_os == "windows" || target_os == "android" {
         return Ok(());
     }

@@ -256,7 +257,7 @@ fn bundle_rg() -> Result<(), Box<dyn std::error::Error>> {
     // PATH. Users install ripgrep separately (winget / scoop). An explicit
     // GROK_TOOLS_BUNDLE_RG_PATH still bundles regardless of target.
     let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
-    if target_os == "windows" && path_override.is_none() {
+    if (target_os == "windows" || target_os == "android") && path_override.is_none() {
         return Ok(());
     }
```

#### (2) 修改 `crates/codegen/xai-grok-shell/build.rs`

```diff
--- a/crates/codegen/xai-grok-shell/build.rs
+++ b/crates/codegen/xai-grok-shell/build.rs
@@ -49,7 +49,7 @@ fn main() -> Result<(), Box<dyn std::error::Error>> {
     // An explicit GROK_SHELL_BUNDLE_RG_PATH still bundles on Windows (the
     // override path below copies any binary regardless of target).
     let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
-    if target_os == "windows" && path_override.is_none() {
+    if (target_os == "windows" || target_os == "android") && path_override.is_none() {
         return Ok(());
     }
```

#### (3) 補充 `.cargo/config.toml` 之 Android Target 配置

在 `.cargo/config.toml` 中增加 Android 目標的 Rustflags 與 16 KiB 連結器設定：

```toml
[target.aarch64-linux-android]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,-z,relro,-z,now,-z,noexecstack",
    "-C", "force-unwind-tables=yes",
]

[target.x86_64-linux-android]
rustflags = [
    "-C", "link-arg=-Wl,-z,max-page-size=16384",
    "-C", "link-arg=-Wl,-z,relro,-z,now,-z,noexecstack",
    "-C", "force-unwind-tables=yes",
]
```

---

## 5. Verification Method

### 5.1 驗證指令

1. **E2E 測試驗證 (Python 測試套件)**：
   ```bash
   python3 tests/e2e/runner.py --tier tier1
   python3 tests/e2e/runner.py
   ```
   確認 Feature 8 (`test_feature_01_to_08.py`) 與 Feature 9 (`test_feature_09_to_16.py`) 的 10 個測試案例全部通過。

2. **ELF 結構與 16 KiB 對齊驗證**：
   ```bash
   python3 scripts/validate_elf.py --self-test
   ```

3. **Android 交叉檢查指令 (編譯期驗證)**：
   ```bash
   cargo check --target aarch64-linux-android
   cargo check --target aarch64-linux-android --release
   ```
   驗證在 `--release` 模式下編譯 `xai-grok-shell` 與 `xai-grok-tools` 時，不會拋出 `Unsupported target for ripgrep bundling` 錯誤，且不會發起任何 HTTP 下載連線。

### 5.2 失效條件 (Invalidation Conditions)
- 若在 `aarch64-linux-android` release 編譯時觀察到 `OUT_DIR/bundle-rg/` 或 `OUT_DIR/bundle-fd/` 產生檔案，則證明門控機制失效。
- 若編譯出的二進制檔中出現 `ld-linux-aarch64.so.1` 字符或解壓縮桌面 Linux 二進制檔至 `~/.grok/vendor/`，則證明二進制下載未被成功旁路。
