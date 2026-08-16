## 2026-08-15T15:33:24Z

Formulate the exact implementation design for Milestone 1 Dependency Gating:
1. `jemalloc`: Exclude `tikv-jemallocator` from Android builds in `crates/codegen/xai-grok-pager-bin/src/main.rs`, `Cargo.toml`, and `xai-grok-pager/Cargo.toml` so Android uses Bionic system allocator.
2. `arboard`: Exclude `arboard` on `target_os = "android"` in `crates/codegen/xai-grok-shared/Cargo.toml` and implement Termux clipboard seam (`termux-clipboard-get/set` + OSC 52 fallback).
3. `cpal`: Exclude `cpal` on `target_os = "android"` in `crates/codegen/xai-grok-voice/Cargo.toml` and disable voice UI/commands gracefully.
4. `nono` (Landlock sandbox): Gate out Linux Landlock syscalls in `crates/codegen/xai-grok-sandbox/` and return `policy-only`.
