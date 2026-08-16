# Milestone 1 Dependency Gating: Exact Implementation Design Report

## 1. Observation

經深入檢視 `/Users/iml1s/Documents/mine/grok-build` 程式庫之依賴宣告與條件編譯配置，直接觀察到下列關鍵事實：

### 1.1 `jemalloc` (`tikv-jemallocator`)
1. **`crates/codegen/xai-grok-pager-bin/Cargo.toml`**（第 64–78 行）：
   ```toml
   [target.'cfg(unix)'.dependencies]
   libc = { workspace = true }
   tikv-jemallocator = { workspace = true, optional = true, features = ["stats"] }
   tikv-jemalloc-sys = { workspace = true, optional = true }
   tikv-jemalloc-ctl = { workspace = true, optional = true, features = ["stats", "use_std"] }
   ```
2. **`crates/codegen/xai-grok-pager-bin/src/main.rs`**（第 8–27, 2047–2160, 2391–2399 行）：
   ```rust
   #[cfg(all(feature = "jemalloc", unix))]
   #[global_allocator]
   static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

   #[cfg(all(feature = "jemalloc", feature = "release-dist", unix))]
   mod jemalloc_malloc_conf { ... }
   ```
   所有 jemalloc hook、`purge_jemalloc_retained_pages`、`jemalloc_allocator_stats`、`jemalloc_stats_dump` 及在 `main()` 中的註冊均使用 `#[cfg(all(feature = "jemalloc", unix))]` 條件。
3. **`crates/codegen/xai-grok-pager/Cargo.toml`**（第 290–301 行）：
   `default = ["jemalloc", "sandbox-enforce"]`，`jemalloc = []` 為空 feature（僅為 composition-root 傳遞）。
4. **Rust Target 分類事實**：在 `aarch64-linux-android` 上，`target_family = "unix"`（`unix`）為 **true**，但 `target_os = "android"` 為 **true**。現有 `cfg(unix)` 導致 Android 目標嘗試編譯並連結 `tikv-jemallocator`，在 Android Bionic libc 上引發連結衝突與 16 KiB page size 不相容。

---

### 1.2 `arboard` (Desktop Clipboard)
1. **`crates/codegen/xai-grok-shared/Cargo.toml`**（第 47–48 行）：
   ```toml
   [target.'cfg(not(target_os = "macos"))'.dependencies]
   arboard = { workspace = true, features = ["wayland-data-control"] }
   ```
2. **`crates/codegen/xai-grok-shared/src/clipboard.rs`**（第 300–317, 1191–1400 行）：
   - `native_tool_name()` 僅區分 `macos`、`linux` 與 `not(any(macos, linux))`（預設為 `"arboard"`）。
   - 第 1194 行：`#[cfg(not(target_os = "macos"))] mod platform { ... }` 直接引用 `arboard::Clipboard`，並依賴 X11 / Wayland / Windows API。
3. **Rust Target 分類事實**：Android 滿足 `not(target_os = "macos")`，導致 Android 被強行引入 `arboard`，在無 X11/Wayland 顯示伺服器的 Termux 環境中編譯依賴龐大且執行期失效。

---

### 1.3 `cpal` (Voice / Microphone Capture)
1. **`crates/codegen/xai-grok-voice/Cargo.toml`**（第 33–53 行）：
   ```toml
   [features]
   default = ["audio"]
   audio = ["dep:cpal"]

   [target.'cfg(not(target_os = "linux"))'.dependencies.cpal]
   version = "0.15"
   optional = true
   ```
2. **`crates/codegen/xai-grok-voice/src/lib.rs`**（第 37–87 行）：
   ```rust
   pub const AUDIO_SUPPORTED: bool = cfg!(feature = "audio");
   ```
   `maybe_run_capture_subprocess()` 使用 `#[cfg(all(feature = "audio", not(target_os = "linux")))]`。
3. **`crates/codegen/xai-grok-voice/src/audio/mod.rs`**（第 24–38 行）：
   ```rust
   #[cfg(not(target_os = "linux"))]
   mod capture;
   #[cfg(not(target_os = "linux"))]
   mod protocol;
   ```
   `capture.rs` 直接引用 `cpal::traits::*` 與 `cpal::*`。
4. **`crates/codegen/xai-grok-pager/src/app/dispatch/voice.rs`**（第 100–104 行）：
   ```rust
   if !app.voice_mode_enabled || !xai_grok_voice::AUDIO_SUPPORTED {
       return vec![];
   }
   ```
5. **Rust Target 分類事實**：Android 上 `target_os` 為 `"android"`，因此 `not(target_os = "linux")` 為 **true**，導致 Android 被誤判為 macOS/Windows 並引入 `cpal`。

---

### 1.4 `nono` (Landlock / Seatbelt Kernel Sandbox)
1. **`crates/codegen/xai-grok-sandbox/Cargo.toml`**（第 22–34 行）：
   ```toml
   [target.'cfg(unix)'.dependencies]
   libc = { workspace = true }
   nono = { version = "=0.53.0", default-features = false }
   globset = { workspace = true }
   ```
2. **`crates/codegen/xai-grok-sandbox/src/lib.rs`**（第 62, 175, 237, 259 行）：
   ```rust
   #[cfg(all(feature = "enforce", unix))]
   use nono::Sandbox;

   #[cfg(all(feature = "enforce", unix))]
   pub fn apply(&mut self, workspace: &Path) -> anyhow::Result<()> { ... }

   #[cfg(not(all(feature = "enforce", unix)))]
   pub fn apply(&mut self, _workspace: &Path) -> anyhow::Result<()> { ... }
   ```
3. **`crates/codegen/xai-grok-sandbox/src/profiles.rs`**（第 6–7 行）：
   ```rust
   #[cfg(all(feature = "enforce", unix))]
   use nono::{AccessMode, CapabilitySet};
   ```
4. **`crates/codegen/xai-grok-sandbox/src/deny/mod.rs` & `glob.rs`**：
   使用 `#[cfg(all(feature = "enforce", unix))]` 引入 `nono::CapabilitySet`。
5. **Rust Target 分類事實**：Android 滿足 `cfg(unix)`，編譯時會呼叫 `nono`（包含 Linux Landlock syscalls），但在 Android 環境下因 SELinux 限制與非標準 Linux 核心環境，無法保證 Landlock 正常運作，且誤將 Android 標記為 `kernel-enforced` 不符合安全誠實原則。

---

## 2. Logic Chain

由上述直接觀察推導出以下設計與實作邏輯：

1. **統一 Target 判斷原則**：
   - 桌面 Linux：`target_os = "linux"`
   - macOS：`target_os = "macos"`
   - Android：`target_os = "android"`（屬於 `unix` 家族，但絕不是桌面 Linux 或 macOS）
   - Windows：`target_os = "windows"`
   - 核心修正原則：所有原本寫 `cfg(unix)`、`cfg(not(target_os = "macos"))`、`cfg(not(target_os = "linux"))` 的桌面專用依賴，必須明確排除 `target_os = "android"`。

2. **`jemalloc` 隔離邏輯**：
   - `tikv-jemallocator` 僅在 `cfg(all(unix, not(target_os = "android")))` 下引入。
   - `xai-grok-pager-bin/src/main.rs` 將所有 jemalloc 巨集條件由 `cfg(all(feature = "jemalloc", unix))` 改為 `cfg(all(feature = "jemalloc", unix, not(target_os = "android")))`。
   - 當 Android 目標編譯時，`#[global_allocator]` 不會被宣告，Rust runtime 自動使用標準庫 `std::alloc::System`（即 Android Bionic 最佳化記憶體配置器）。
   - `xai-grok-shell/src/heap_profile` 與 `xai-grok-pager/src/memory_release` 本身即為 IoC seam（無 hook 時自動為 no-op），完全不會有執行期異常。

3. **`arboard` 隔離與 Termux Clipboard 實作邏輯**：
   - 將 `xai-grok-shared/Cargo.toml` 中的 `arboard` 限制為 `cfg(all(not(target_os = "macos"), not(target_os = "android")))`。
   - 在 `xai-grok-shared/src/clipboard.rs` 中：
     - `native_tool_name()` 針對 `target_os = "android"` 返回 `"termux-clipboard"`。
     - 桌面版 `mod platform` 限制為 `cfg(all(not(target_os = "macos"), not(target_os = "android")))`。
     - 新增 `#[cfg(target_os = "android")] mod platform`：
       - `get_text()`: 透過 `std::process::Command` 調用 `termux-clipboard-get`，若未安裝 Termux:API 或失敗則優雅返回 `Ok(None)`。
       - `set_text_with_outcome()`: 優先嘗試 `termux-clipboard-set`，若未安裝或失敗則自動 fallback 呼叫 `super::set_text_osc52(text, false)` 輸出 ANSI OSC 52 序列至終端。
       - `get_image()` / `get_file_urls()`: 返回 `Ok(None)`。
       - `set_image_file()`: 返回 `Err` 明確提示不支援。

4. **`cpal` 隔離與 Voice 優雅降級邏輯**：
   - 將 `xai-grok-voice/Cargo.toml` 中的 `cpal` 限制為 `cfg(all(not(target_os = "linux"), not(target_os = "android")))`。
   - 在 `xai-grok-voice/src/lib.rs` 中：
     - `pub const AUDIO_SUPPORTED: bool = cfg!(all(feature = "audio", not(target_os = "android")));`
     - 當 Android 目標編譯時，`AUDIO_SUPPORTED` 自動為 `false`。
   - `xai-grok-pager` 所有語音入口（快捷鍵 Ctrl+Space、`/voice` 指令、TUI 麥克風提示）皆在第一行檢查 `xai_grok_voice::AUDIO_SUPPORTED`，為 `false` 時靜默略過或顯示不支援，不會造成 panic。
   - 在 `xai-grok-voice/src/audio/mod.rs` 中新增 `capture_android.rs` stub，若被直接呼叫則返回 `VoiceError::Config("Audio capture not supported on Android")`。

5. **`nono` (Landlock) 隔離與沙盒真實性邏輯**：
   - 將 `xai-grok-sandbox/Cargo.toml` 中的 `nono` 限制為 `cfg(all(unix, not(target_os = "android")))`。
   - 在 `xai-grok-sandbox/src/lib.rs`、`profiles.rs`、`deny/mod.rs` 中，將 `use nono::*` 及 `Sandbox::apply` 條件改為 `cfg(all(feature = "enforce", unix, not(target_os = "android")))`。
   - Android 目標走 `cfg(not(all(feature = "enforce", unix, not(target_os = "android"))))` 分支：
     - `apply()` 記錄日誌 `"Sandbox enforcement unavailable on Android (policy-only)"`，不執行 Landlock syscalls。
     - `is_active()` 返回 `false`，但所有路徑安全檢查（如直接 Hook 防寫保護、路徑正規化等 in-process 規則）仍然生效。
     - `grok doctor` 與 UI 能真實報告 Android 為 `policy-only` 沙盒，杜絕虛假的 `kernel-enforced` 聲明。

---

## 3. Concrete Code Changes & Design Specification

### 3.1 `jemalloc` Gating

#### File 1: `crates/codegen/xai-grok-pager-bin/Cargo.toml`
```toml
<<<<
[target.'cfg(unix)'.dependencies]
libc = { workspace = true }
# Default allocator on Unix; gated by the `jemalloc` feature (see main.rs
# `#[global_allocator]`, cfg(all(feature = "jemalloc", unix))).
# `stats` is binary-scoped only (not workspace-wide) so this CLI jemalloc
# link gets --enable-stats for stats.allocated / stats.resident mallctl.
tikv-jemallocator = { workspace = true, optional = true, features = ["stats"] }
# Raw mallctl for the memory-cliff arena purge hook (see
# `purge_jemalloc_retained_pages` + the `install_release_hook` call in
# main.rs). Same version family as the
# allocator; adds no new build units beyond what tikv-jemallocator pulls in.
tikv-jemalloc-sys = { workspace = true, optional = true }
# Heap-profile / stats mallctl helpers (prof.active, prof.dump, epoch, stats.*).
tikv-jemalloc-ctl = { workspace = true, optional = true, features = ["stats", "use_std"] }
====
[target.'cfg(unix)'.dependencies]
libc = { workspace = true }

[target.'cfg(all(unix, not(target_os = "android")))'.dependencies]
# Default allocator on desktop Unix; gated by the `jemalloc` feature.
# Excluded on Android/Termux to use Bionic's system allocator.
tikv-jemallocator = { workspace = true, optional = true, features = ["stats"] }
tikv-jemalloc-sys = { workspace = true, optional = true }
tikv-jemalloc-ctl = { workspace = true, optional = true, features = ["stats", "use_std"] }
>>>>
```

#### File 2: `crates/codegen/xai-grok-pager-bin/src/main.rs`
在 `main.rs` 中將所有 jemalloc 相關的 `cfg` 條件改為 `cfg(all(feature = "jemalloc", unix, not(target_os = "android")))`：
1. **第 8 行**：
   ```rust
   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   #[global_allocator]
   static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
   ```
2. **第 11 行**：
   ```rust
   #[cfg(all(feature = "jemalloc", feature = "release-dist", unix, not(target_os = "android")))]
   mod jemalloc_malloc_conf { ... }
   ```
3. **第 2047, 2074, 2101, 2119, 2131, 2135, 2139, 2143, 2152 行**：
   ```rust
   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn purge_jemalloc_retained_pages() { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_allocator_stats() -> Option<xai_grok_pager::memory_trace::AllocatorStats> { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_stats_dump() -> String { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_heap_stats() -> Option<xai_grok_shell::heap_profile::JemallocStats> { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_set_prof_active(active: bool) -> bool { ... }

   #[cfg(all(test, feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_read_prof_active() -> Option<bool> { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_prof_available() -> bool { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn jemalloc_dump_to_path(path: &std::path::Path) -> Result<(), String> { ... }

   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   fn install_heap_profile_hooks() { ... }
   ```
4. **第 2391, 2393, 2398 行（`main()` 註冊 hook 處）**：
   ```rust
   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   xai_grok_pager::memory_release::install_release_hook(purge_jemalloc_retained_pages);
   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   {
       xai_grok_pager::memory_trace::install_allocator_stats_provider(jemalloc_allocator_stats);
       xai_grok_pager::memory_trace::install_allocator_dump_provider(jemalloc_stats_dump);
   }
   #[cfg(all(feature = "jemalloc", unix, not(target_os = "android")))]
   install_heap_profile_hooks();
   ```

---

### 3.2 `arboard` Gating & Termux Clipboard Seam

#### File 1: `crates/codegen/xai-grok-shared/Cargo.toml`
```toml
<<<<
[target.'cfg(not(target_os = "macos"))'.dependencies]
arboard = { workspace = true, features = ["wayland-data-control"] }
====
[target.'cfg(all(not(target_os = "macos"), not(target_os = "android")))'.dependencies]
arboard = { workspace = true, features = ["wayland-data-control"] }
>>>>
```

#### File 2: `crates/codegen/xai-grok-shared/src/clipboard.rs`
1. **更新 `native_tool_name()`**（第 304–317 行）：
   ```rust
   pub fn native_tool_name() -> &'static str {
       #[cfg(target_os = "macos")]
       {
           "pbcopy"
       }
       #[cfg(target_os = "android")]
       {
           "termux-clipboard"
       }
       #[cfg(target_os = "linux")]
       {
           platform::linux_tool_spec().map_or("arboard", |spec| spec.name)
       }
       #[cfg(not(any(target_os = "macos", target_os = "android", target_os = "linux")))]
       {
           "arboard"
       }
   }
   ```
2. **桌面版 `platform` 模組條件改為**：
   ```rust
   #[cfg(all(not(target_os = "macos"), not(target_os = "android")))]
   mod platform { ... }
   ```
3. **新增 Android 專用 `platform` 模組**：
   ```rust
   #[cfg(target_os = "android")]
   mod platform {
       use super::{ClipboardAttachments, ImageData, NativeWriteOutcome};
       use std::io::Write;
       use std::path::Path;
       use std::process::{Command, Stdio};

       pub(super) fn clipboard_image_snapshot() -> (Option<u64>, bool) {
           (None, false)
       }

       pub(super) fn clipboard_change_count() -> Option<u64> {
           None
       }

       pub(super) fn clipboard_prewarm() {}

       pub(super) fn wayland_data_control_supported() -> bool {
           false
       }

       pub(super) fn probe_wayland_data_control() -> super::WaylandDataControlProbe {
           super::WaylandDataControlProbe {
               available: false,
               primary_selection_supported: false,
               data_control_supported: false,
           }
       }

       pub(super) fn get_text() -> anyhow::Result<Option<String>> {
           let output = match Command::new("termux-clipboard-get")
               .stdin(Stdio::null())
               .stdout(Stdio::piped())
               .stderr(Stdio::null())
               .output()
           {
               Ok(out) => out,
               Err(e) => {
                   tracing::debug!("termux-clipboard-get not found or failed: {e}");
                   return Ok(None);
               }
           };

           if !output.status.success() {
               return Ok(None);
           }

           let text = String::from_utf8_lossy(&output.stdout).to_string();
           if text.is_empty() {
               Ok(None)
           } else {
               Ok(Some(text))
           }
       }

       pub(super) fn set_text_with_outcome(text: &str) -> NativeWriteOutcome {
           let mut outcome = NativeWriteOutcome {
               cli_tools_tried: vec!["termux-clipboard-set"],
               ..Default::default()
           };

           let mut success = false;
           if let Ok(mut child) = Command::new("termux-clipboard-set")
               .stdin(Stdio::piped())
               .stdout(Stdio::null())
               .stderr(Stdio::null())
               .spawn()
           {
               if let Some(mut stdin) = child.stdin.take() {
                   let _ = stdin.write_all(text.as_bytes());
               }
               if let Ok(status) = child.wait() {
                   if status.success() {
                       outcome.cli_ok_tools.push("termux-clipboard-set");
                       outcome.cli_ok = true;
                       outcome.any_ok = true;
                       success = true;
                   }
               }
           }

           // Fallback to ANSI OSC 52 sequence if termux-clipboard-set is unavailable or fails
           if !success {
               if super::set_text_osc52(text, false).is_ok() {
                   outcome.any_ok = true;
               }
           }

           outcome
       }

       pub(super) fn get_image() -> anyhow::Result<Option<ImageData>> {
           Ok(None)
       }

       pub(super) fn get_file_urls() -> anyhow::Result<Option<String>> {
           Ok(None)
       }

       pub(super) fn get_attachments() -> anyhow::Result<ClipboardAttachments> {
           Ok(ClipboardAttachments::default())
       }

       pub(super) fn set_image_file(_path: &Path) -> anyhow::Result<()> {
           anyhow::bail!("image clipboard is not supported on Android/Termux")
       }
   }
   ```

---

### 3.3 `cpal` Gating & Voice Graceful Degradation

#### File 1: `crates/codegen/xai-grok-voice/Cargo.toml`
```toml
<<<<
[target.'cfg(not(target_os = "linux"))'.dependencies.cpal]
version = "0.15"
optional = true
====
[target.'cfg(all(not(target_os = "linux"), not(target_os = "android")))'.dependencies.cpal]
version = "0.15"
optional = true
>>>>
```

#### File 2: `crates/codegen/xai-grok-voice/src/lib.rs`
1. **第 46 行**：
   ```rust
   <<<<
   pub const AUDIO_SUPPORTED: bool = cfg!(feature = "audio");
   ====
   pub const AUDIO_SUPPORTED: bool = cfg!(all(feature = "audio", not(target_os = "android")));
   >>>>
   ```
2. **第 65, 75 行（`maybe_run_capture_subprocess`）**：
   ```rust
   <<<<
   #[cfg(all(feature = "audio", not(target_os = "linux")))]
   ====
   #[cfg(all(feature = "audio", not(any(target_os = "linux", target_os = "android"))))]
   >>>>
   ```

#### File 3: `crates/codegen/xai-grok-voice/src/audio/mod.rs`
```rust
<<<<
#[cfg(not(target_os = "linux"))]
mod capture;
#[cfg(not(target_os = "linux"))]
mod protocol;
#[cfg(not(target_os = "linux"))]
pub use capture::capture_pcm_for_duration;
#[cfg(not(target_os = "linux"))]
pub(crate) use capture::run_capture_child_cli;
#[cfg(target_os = "windows")]
pub use capture::{CaptureHandle, input_device_info, spawn_pcm_capture};
====
#[cfg(all(not(target_os = "linux"), not(target_os = "android")))]
mod capture;
#[cfg(all(not(target_os = "linux"), not(target_os = "android")))]
mod protocol;
#[cfg(all(not(target_os = "linux"), not(target_os = "android")))]
pub use capture::capture_pcm_for_duration;
#[cfg(all(not(target_os = "linux"), not(target_os = "android")))]
pub(crate) use capture::run_capture_child_cli;
#[cfg(target_os = "windows")]
pub use capture::{CaptureHandle, input_device_info, spawn_pcm_capture};

#[cfg(target_os = "android")]
mod capture_android;
#[cfg(target_os = "android")]
pub use capture_android::{
    CaptureHandle, capture_pcm_for_duration, input_device_info, spawn_pcm_capture,
};
>>>>
```

#### File 4: `crates/codegen/xai-grok-voice/src/audio/capture_android.rs` (New File)
```rust
use crate::error::VoiceError;
use crate::event::VoiceEvent;
use crate::probe::InputDeviceInfo;
use std::time::Duration;

pub struct CaptureHandle;

impl CaptureHandle {
    pub fn stop(&self) {}
}

pub fn input_device_info() -> Result<InputDeviceInfo, VoiceError> {
    Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))
}

pub fn spawn_pcm_capture(
    _sample_rate: u32,
    _event_tx: tokio::sync::mpsc::Sender<VoiceEvent>,
) -> Result<CaptureHandle, VoiceError> {
    Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))
}

pub fn capture_pcm_for_duration(
    _sample_rate: u32,
    _duration: Duration,
) -> Result<Vec<u8>, VoiceError> {
    Err(VoiceError::Config("Audio capture is not supported on Android/Termux".into()))
}
```

---

### 3.4 `nono` (Landlock) Gating & Policy-Only Sandbox

#### File 1: `crates/codegen/xai-grok-sandbox/Cargo.toml`
```toml
<<<<
[target.'cfg(unix)'.dependencies]
libc = { workspace = true }
nono = { version = "=0.53.0", default-features = false }
globset = { workspace = true }
====
[target.'cfg(unix)'.dependencies]
libc = { workspace = true }

[target.'cfg(all(unix, not(target_os = "android")))'.dependencies]
nono = { version = "=0.53.0", default-features = false }
globset = { workspace = true }
>>>>
```

#### File 2: `crates/codegen/xai-grok-sandbox/src/lib.rs`
1. **第 62 行**：
   ```rust
   <<<<
   #[cfg(all(feature = "enforce", unix))]
   use nono::Sandbox;
   ====
   #[cfg(all(feature = "enforce", unix, not(target_os = "android")))]
   use nono::Sandbox;
   >>>>
   ```
2. **第 175 行與 237 行（`SandboxManager::apply`）**：
   ```rust
   <<<<
   #[cfg(all(feature = "enforce", unix))]
   pub fn apply(&mut self, workspace: &Path) -> anyhow::Result<()> {
   ====
   #[cfg(all(feature = "enforce", unix, not(target_os = "android")))]
   pub fn apply(&mut self, workspace: &Path) -> anyhow::Result<()> {
   >>>>
   ```
   ```rust
   <<<<
   #[cfg(not(all(feature = "enforce", unix)))]
   pub fn apply(&mut self, _workspace: &Path) -> anyhow::Result<()> {
       tracing::info!(
           profile = %self.profile,
           "Sandbox enforcement unavailable (built without 'enforce' feature)"
       );
       Ok(())
   }
   ====
   #[cfg(not(all(feature = "enforce", unix, not(target_os = "android"))))]
   pub fn apply(&mut self, _workspace: &Path) -> anyhow::Result<()> {
       tracing::info!(
           profile = %self.profile,
           "Sandbox enforcement unavailable on Android/Termux (running in policy-only mode)"
       );
       Ok(())
   }
   >>>>
   ```
3. **第 259 行（`support_info`）**：
   ```rust
   <<<<
   #[cfg(all(feature = "enforce", unix))]
   pub fn support_info() -> nono::SupportInfo {
       Sandbox::support_info()
   }
   ====
   #[cfg(all(feature = "enforce", unix, not(target_os = "android")))]
   pub fn support_info() -> nono::SupportInfo {
       Sandbox::support_info()
   }
   >>>>
   ```

#### File 3: `crates/codegen/xai-grok-sandbox/src/profiles.rs`
```rust
<<<<
#[cfg(all(feature = "enforce", unix))]
use nono::{AccessMode, CapabilitySet};
====
#[cfg(all(feature = "enforce", unix, not(target_os = "android")))]
use nono::{AccessMode, CapabilitySet};
>>>>
```
以及將 `capability_set_from_profile` 與相關 deny 函數引用同樣由 `cfg(all(feature = "enforce", unix))` 更新為 `cfg(all(feature = "enforce", unix, not(target_os = "android")))`。

#### File 4: `crates/codegen/xai-grok-sandbox/src/deny/mod.rs` & `glob.rs`
將 `#[cfg(all(feature = "enforce", unix))]` 統一調整為 `#[cfg(all(feature = "enforce", unix, not(target_os = "android")))]`。

---

## 4. Caveats

1. **Termux:API 相依性**：
   - 剪貼簿讀寫在 Termux:API 未安裝時會自動 fallback 到 OSC 52（寫入）與 `Ok(None)`（讀取）。這是 Termux CLI 應用程式之標準優雅降級模式，使用者若需與 Android 系統剪貼簿雙向同步，只需執行 `pkg install termux-api`。
2. **`globset` 與 `ignore` 在 Android 上的角色**：
   - `globset` 本身為 pure Rust crate，在 Android 上若僅作路徑匹配並無系統呼叫問題；但由於 `nono` 被隔離，沙盒層的 glob 展開僅在啟用 Landlock/Seatbelt 的桌面環境中編譯使用。
3. **`xai-grok-pager` 預設 Features**：
   - `xai-grok-pager/Cargo.toml` 內的 `default = ["jemalloc", "sandbox-enforce"]` 中，`jemalloc` 是空 feature（由 `xai-grok-pager-bin` 實際 link），而 `sandbox-enforce` 連結到 `xai-grok-sandbox/enforce`。經由上述 target-gating，在 Android 上編譯時兩者皆能安全解析，無需為 Android 修改 workspace 的 default feature 結構，維持與上游 upstream 高度相容。

---

## 5. Conclusion

本設計以精準的 `not(target_os = "android")` 條件編譯與 target-specific dependencies，達成以下 Milestone 1 目標：
1. **`jemalloc` 徹底自 Android 目標剔除**：Android 自然使用 Bionic 系統配置器，避免 16 KiB page size 崩潰與符號衝突。
2. **`arboard` 徹底自 Android 目標剔除**：建立 Termux 剪貼簿 seam，整合 `termux-clipboard-get/set` 與 ANSI OSC 52 fallback。
3. **`cpal` 徹底自 Android 目標剔除**：將 `AUDIO_SUPPORTED` 於 Android 上設為 `false`，UI 與快捷鍵優雅降級，麥克風路徑不產生 crash 或 fake UI。
4. **`nono` (Landlock) 徹底自 Android 目標剔除**：沙盒真實回報 `policy-only`，保留 in-process 檔案路徑與安全限制，杜絕非法的 kernel syscalls。

---

## 6. Verification Method

實作完成後，可依下列方法進行獨立驗證：

1. **依賴樹稽核（Dependency Tree Audit）**：
   執行 cross-target metadata 檢查，確認 `tikv-jemallocator`、`arboard`、`cpal`、`nono` 不在 `aarch64-linux-android` 依賴樹中：
   ```bash
   cargo tree --target aarch64-linux-android -p xai-grok-pager-bin -i tikv-jemallocator
   # 預期：錯誤或回傳空（未找到該依賴）
   cargo tree --target aarch64-linux-android -p xai-grok-pager-bin -i arboard
   # 預期：未找到
   cargo tree --target aarch64-linux-android -p xai-grok-pager-bin -i cpal
   # 預期：未找到
   cargo tree --target aarch64-linux-android -p xai-grok-pager-bin -i nono
   # 預期：未找到
   ```

2. **跨平台編譯檢查（Cargo Check / Build）**：
   ```bash
   cargo check --target aarch64-linux-android --bin xai-grok-pager
   ```
   驗證全 workspace 在 `aarch64-linux-android` 目標下無編譯或型別錯誤。

3. **桌面端行為回歸驗證（Non-Regression Test）**：
   ```bash
   cargo test -p xai-grok-shared --lib clipboard
   cargo test -p xai-grok-voice --lib
   cargo test -p xai-grok-sandbox --lib
   ```
   確認 macOS / Linux / Windows 上的現有單元測試與 feature behavior 100% 不受影響。
