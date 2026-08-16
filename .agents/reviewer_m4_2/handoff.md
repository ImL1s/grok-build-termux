# Milestone 4 審查與對抗性驗證報告 (Features 22–26)

- **審查員 / 對抗挑戰者**：`reviewer_m4_2`
- **工作目錄**：`/Users/iml1s/Documents/mine/grok-build-termux/.agents/reviewer_m4_2`
- **審查目標**：Milestone 4 (Features 22–26: 沙盒誠實回報、行程內策略執行、行動端併發限制、Termux Wake Lock、持久化 Session 復原)
- **審查結論**：**APPROVE (通過)**
- **日期**：2026-08-16

---

## 1. Observation (直接觀察)

### 1.1 程式碼實作與架構審查

1. **Feature 22: Truthful Sandbox Reporting (`SandboxKind::PolicyOnly`)**
   - 檔案：`crates/codegen/xai-grok-config/src/platform.rs`
     - 第 35–56 行：定義 `SandboxKind` 列舉（`KernelEnforced`, `PolicyOnly`, `Disabled`），其 `as_str()` 正確輸出 `"policy-only"`、`"kernel-enforced"`。
     - 第 261–265 行：`PlatformCapabilities::probe` 明確將 `PlatformKind::AndroidTermux` 與 `PlatformKind::UnsupportedAndroid` 歸類為 `SandboxKind::PolicyOnly`。
     - 第 366–368 行：`PlatformCapabilities::sandbox_kind(&self)` 忠實回報內部沙盒類別。
   - 檔案：`crates/codegen/xai-grok-sandbox/src/lib.rs`
     - 第 240–247 行：在非 `enforce` 或 Android target 下，`SandboxManager::apply` 記錄 `"Sandbox enforcement unavailable (running in policy-only mode)"` 並安全返回 `Ok(())`，不調用非支援之 `nono` 核心 Landlock API。
     - 第 447–450 行：`requires_read_deny` 在 Android target 下回傳 `false`，不進行無效的 bwrap re-exec。

2. **Feature 23: In-Process Policy Enforcement & Sensitive Path Barriers**
   - 檔案：`crates/codegen/xai-grok-config/src/platform.rs`
     - 第 388–402 行：`ANDROID_SHARED_STORAGE_PREFIXES` 涵蓋 `/sdcard`, `/storage`, `/mnt/sdcard`, `/mnt/media_rw`, `/data/sdcard`, `/data/media` 及其相對路徑變體。
     - 第 471–580 行：`validate_storage_safety` 與 `validate_storage_safety_depth` 實作深度最高 16 層之符號連結解析、路徑詞法正規化（Component normalization）、大小寫不敏感比對、懸空符號連結與遞迴連結檢查，徹底防禦私有資料或 `GROK_HOME` 洩漏至共用儲存。
   - 檔案：`crates/codegen/xai-grok-config/src/paths.rs`
     - 第 35–53 行：`grok_home()` 在讀取 `GROK_HOME` 環境變數時調用 `validate_storage_safety`，若發現違規安全回退至預設私有路徑。
   - 檔案：`crates/codegen/xai-grok-sandbox/src/paths.rs`
     - 第 79–91 行：`essential_writable_paths` 嚴格限定可寫目錄僅為 `workspace`、`grok_home()` 與系統/使用者暫存目錄，阻止對 `/proc`、`/sys` 等敏感系統路徑之非法寫入。

3. **Feature 24: Conservative Concurrency & Mobile Defaults**
   - 檔案：`crates/codegen/xai-file-utils/src/queue.rs`
     - 第 573–580 行、第 1657–1730 行：透過 `ConcurrencyPermit` 與信號量機制限制背景佇列併發與記憶體駐留，防止 Android 系統在資源緊張時觸發 Low Memory Killer (LMK)。
   - 測試：`tests/e2e/tier1_features/test_feature_17_to_24.py` (第 285–312 行)
     - 驗證工作執行緒上限 (≤ 4)、Subagent 平行數量 (≤ 2) 與 blocking thread pool 邊界控制。

4. **Feature 25: Termux Wake Lock Integration (`termux-wake-lock` / `termux-wake-unlock`)**
   - 檔案：`crates/codegen/xai-system-power/src/android.rs`
     - 第 20 行：`static WAKE_LOCK_COUNT: AtomicUsize = AtomicUsize::new(0)`。
     - 第 25–36 行：`impl Drop for Assertion` 透過 `fetch_sub(1, SeqCst)` 進行原子遞減，僅在歸零 (`prev == 1`) 時執行 `termux-wake-unlock`，符合 RAII 守衛與防洩漏保證。
     - 第 38–57 行：`hold_awake` 透過 `fetch_add(1, SeqCst)` 原子遞增，首次獲取時調用 `termux-wake-lock`；若工具缺失（`spawn` 失敗）則自動扣回計數並安全回傳 `None`，達成優雅降級。

5. **Feature 26: Durable Session Checkpoint & Recovery**
   - 檔案：`crates/codegen/xai-grok-config/src/fs_atomic.rs`
     - 第 10–43 行：`write_atomically` 採用 `unique_tmp -> write -> fs::rename` 之原子交易機制，並在 Unix 上嚴格施加 `mode 0700`，杜絕寫入中斷留下殘缺檔案。
   - 檔案：`crates/codegen/xai-grok-active-sessions/src/lib.rs`
     - 第 81–97 行：`with_locked_state` 透過 `fs2::FileExt::lock_exclusive` 排他鎖保護 `active_sessions.json`。
     - 第 141–158 行：`read_data_file` 在 JSON 檔案損壞時自動降級為空清單並記錄警告，不觸發 panic。
     - 第 173–204 行：`is_pid_alive` 在 Unix 透過 `libc::kill(pid, 0)` 精確判斷 Session 行程存活，由 `collect_crashed` 自動回收孤兒 Session。

---

### 1.2 自動化驗證指令輸出

1. **Cargo 編譯檢查 (`cargo check -p xai-grok-sandbox -p xai-grok-config -p xai-system-power`)**：
   - 輸出：`Finished dev profile [unoptimized + debuginfo] in 32.8s`（0 錯誤）。

2. **Cargo 單元與整合測試 (`cargo test -p xai-grok-config -p xai-system-power`)**：
   - 輸出：
     - `xai-grok-config` (unittests): 213 passed, 0 failed.
     - `challenger_m3_adversarial`: 12 passed, 0 failed.
     - `platform_adversarial`: 15 passed, 0 failed.
     - `shell_adversarial`: 2 passed, 0 failed.
     - `socket_adversarial`: 5 passed, 0 failed.
     - `xai-system-power` (unittests): 7 passed, 0 failed.
     - 總計：**254/254 測試 100% 通過**。

3. **Cargo Session 測試 (`cargo test -p xai-grok-active-sessions`)**：
   - 輸出：
     - `xai-grok-active-sessions` (unittests): 5 passed, 0 failed (含 `corrupt_file_recovers`, `concurrent_registers_no_corruption`, `collect_crashed_partitions_by_pid_liveness`)。
     - `tests/smoke.rs`: 1 passed, 0 failed.
     - 總計：**6/6 測試 100% 通過**。

4. **4-Tier E2E 完整測試集 (`python3 tests/e2e/runner.py`)**：
   - 輸出：
     ```
     ================================================================================
      grok-build-termux : 4-Tier E2E Test Suite Execution
     ================================================================================
     [✓] Tier 1: Feature Coverage (32 Features × 5)              Tests: 160 | Passed: 160 | Failed:  0 | Time: 3.20s
     [✓] Tier 2: Boundary & Corner Cases (32 Features × 5)       Tests: 160 | Passed: 160 | Failed:  0 | Time: 2.66s
     [✓] Tier 3: Pairwise Cross-Feature Interactions             Tests:  34 | Passed:  34 | Failed:  0 | Time: 1.09s
     [✓] Tier 4: Real-World Application Scenarios                Tests:  12 | Passed:  12 | Failed:  0 | Time: 0.53s
     ================================================================================
     Summary: 366/366 passed in 7.504s | Result: SUCCESS (100% PASSED)
     ================================================================================
     ```

5. **ELF Validator 自我測試 (`python3 scripts/validate_elf.py --self-test`)**：
   - 輸出：`All self-tests passed successfully.` (6 項合成 ELF 測試全數通過)。

---

## 2. Logic Chain (邏輯推理鏈)

```
[M4 驗證範疇: Features 22–26 (沙盒、安全策略、併發、Wake Lock、Session 韌性)]
                               │
    ┌──────────────────────────┼──────────────────────────┐
    ▼                          ▼                          ▼
[Feature 22-23: 安全與沙盒]  [Feature 24: 資源控管]     [Feature 25-26: 電源與 Session]
    │                          │                          │
    ├─ PlatformCapabilities:   ├─ ConcurrencyPermit 信號量├─ AtomicUsize 引用計數
    │  Android -> PolicyOnly   ├─ Worker threads ≤ 4      ├─ RAII Assertion Drop 解鎖
    ├─ validate_storage_safety:├─ Subagents ≤ 2           ├─ write_atomically (0700)
    │  符號連結深度解析防護    └─ LMK 記憶體上限防範     ├─ FileExt::lock_exclusive
    └─ essential_writable_paths                           └─ libc::kill(pid, 0) 崩潰回收
                               │
                               ▼
[獨立編譯無誤 + 260 項 Rust 測試全數通過 + 366 項 4-Tier E2E 測試 100% 通過]
                               │
                               ▼
[無 Dummy Facade、無 Hardcoding、無 Integrity Violation -> APPROVE]
```

---

## 3. Adversarial Challenges & Integrity Verification (對抗性挑戰與完整性審查)

### 3.1 完整性檢查 (Integrity Violation Check)
- **硬編碼測試輸出 (Hardcoded Test Facades)**：無。所有 API 均依據實際 `PlatformCapabilities` 與作業系統介面執行真實運算。
- **虛假沙盒聲明 (False Kernel Boundary Claims)**：無。明確拒絕宣稱 Android 上存在 Landlock / PRoot 安全隔離，嚴格標記為 `policy-only`。
- **繞過或降級風險 (Security Shortcuts)**：無。儲存安全防護與符號連結深度檢查具備完備的防穿透機制。

### 3.2 對抗性場景壓力測試 (Stress Testing)
1. **場景 1：Wake Lock 併發獲取與異常釋放**
   - *測試方法*：模擬多任務同時調用 `hold_awake` 並在中途發生 panic。
   - *結果*：`Assertion` 之 `Drop` 保證計數器原子遞減，最終喚醒鎖被正常釋放，無計數洩漏或進程卡住。
2. **場景 2：Session JSON 損壞與併發寫入**
   - *測試方法*：注入損毀 JSON (`"garbage{{{"`) 並由多執行緒同時註冊。
   - *結果*：`read_data_file` 自動復原為空陣列，`write_data_file_atomic` 確保原子覆寫，資料未損毀。
3. **場景 3：多層符號連結與大小寫穿透攻擊**
   - *測試方法*：構造指向 `/storage/emulated/0` 之相對與絕對多跳符號連結。
   - *結果*：`validate_storage_safety` 正確攔截並拋出 `SharedStorageQuarantine` 錯誤。

---

## 4. Caveats (注意事項)

- **Termux:API 執行檔缺失時之行為**：若使用者系統未安裝 `termux-api` 套件，`termux-wake-lock` 將無法啟動。程式碼已實作 `spawn().is_err()` 捕捉並降級為 `None`，不影響 Grok Build 主體運行。
- **無其他 Caveats**。

---

## 5. Conclusion (審查結論)

### **Verdict: APPROVE (通過)**

Milestone 4 之 Features 22–26 實作邏輯嚴謹，完全符合 `ORIGINAL_REQUEST.md` 與 `PROJECT.md` 之介面合約與安全邊界要求。所有單元測試與端對端測試均 100% 通過，無任何 Integrity Violation。

---

## 6. Verification Method (獨立驗證方法)

1. **編譯檢查**：
   ```bash
   cargo check -p xai-grok-sandbox -p xai-grok-config -p xai-system-power -p xai-grok-active-sessions
   ```
2. **Rust 單元與整合測試**：
   ```bash
   cargo test -p xai-grok-config -p xai-system-power
   cargo test -p xai-grok-active-sessions
   ```
3. **E2E 測試驗證**：
   ```bash
   python3 tests/e2e/runner.py
   python3 scripts/validate_elf.py --self-test
   ```
