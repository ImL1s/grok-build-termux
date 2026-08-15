#!/usr/bin/env bash
set -Eeuo pipefail

UPSTREAM="${UPSTREAM:-xai-org/grok-build}"
FORK_NAME="${FORK_NAME:-grok-build-termux}"
MILESTONE="${MILESTONE:-v0.1.0-termux-native}"

log() { printf '\n==> %s\n' "$*" >&2; }
warn() { printf '\nWARNING: %s\n' "$*" >&2; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v gh >/dev/null 2>&1 || die "GitHub CLI (gh) is required. In Termux: pkg install gh"
command -v jq >/dev/null 2>&1 || die "jq is required. In Termux: pkg install jq"
gh auth status >/dev/null 2>&1 || die "GitHub CLI is not authenticated. Run: gh auth login"

OWNER="${OWNER:-$(gh api user --jq .login)}"
REPO="$OWNER/$FORK_NAME"
DEFAULT_FORK="$OWNER/$(basename "$UPSTREAM")"
CREATED=0

UPSTREAM_BRANCH="$(gh repo view "$UPSTREAM" --json defaultBranchRef --jq '.defaultBranchRef.name')"
UPSTREAM_SHA="$(gh api "repos/$UPSTREAM/commits/$UPSTREAM_BRANCH" --jq .sha)"

log "Upstream: $UPSTREAM@$UPSTREAM_SHA ($UPSTREAM_BRANCH)"
log "Target fork: $REPO"

if gh repo view "$REPO" --json nameWithOwner >/dev/null 2>&1; then
  PARENT="$(gh repo view "$REPO" --json parent --jq '.parent.nameWithOwner // ""')"
  [[ "$PARENT" == "$UPSTREAM" ]] || die "$REPO exists but is not a fork of $UPSTREAM (parent: ${PARENT:-none})"
  log "Fork already exists; keeping it and applying the backlog idempotently"
else
  log "Forking the current upstream default branch as $FORK_NAME"
  if gh repo fork "$UPSTREAM" --fork-name "$FORK_NAME" --clone=false; then
    CREATED=1
  else
    # Compatibility fallback for older gh versions that do not support --fork-name.
    warn "Direct named fork failed; checking for the default-name fork"
    if ! gh repo view "$DEFAULT_FORK" --json parent >/dev/null 2>&1; then
      gh repo fork "$UPSTREAM" --clone=false
    fi
    PARENT="$(gh repo view "$DEFAULT_FORK" --json parent --jq '.parent.nameWithOwner // ""')"
    [[ "$PARENT" == "$UPSTREAM" ]] || die "$DEFAULT_FORK is not the expected upstream fork"
    gh repo rename -R "$DEFAULT_FORK" "$FORK_NAME" --yes
    CREATED=1
  fi
fi

# GitHub can take a moment to make a new fork queryable.
for _ in $(seq 1 30); do
  gh repo view "$REPO" --json nameWithOwner >/dev/null 2>&1 && break
  sleep 2
done
gh repo view "$REPO" --json nameWithOwner >/dev/null 2>&1 || die "Fork was created but did not become queryable"

if [[ "$CREATED" == "1" ]]; then
  log "Hard-syncing the fresh fork to the latest upstream commit"
  gh repo sync "$REPO" --source "$UPSTREAM" --branch "$UPSTREAM_BRANCH" --force
else
  log "Fast-forwarding the existing fork without overwriting downstream work"
  if ! gh repo sync "$REPO" --source "$UPSTREAM" --branch "$UPSTREAM_BRANCH"; then
    warn "The fork has diverged from upstream; no force-reset was performed"
  fi
fi

FORK_SHA="$(gh api "repos/$REPO/commits/$UPSTREAM_BRANCH" --jq .sha)"
if [[ "$CREATED" == "1" && "$FORK_SHA" != "$UPSTREAM_SHA" ]]; then
  die "Fresh fork is not at the upstream head: fork=$FORK_SHA upstream=$UPSTREAM_SHA"
fi

log "Configuring repository metadata"
gh repo edit "$REPO" \
  --description "Unofficial native Android/Termux port of Grok Build, tracking $UPSTREAM." \
  --enable-issues \
  --enable-wiki=false \
  --enable-projects \
  --enable-squash-merge \
  --enable-rebase-merge \
  --enable-merge-commit=false \
  --delete-branch-on-merge || warn "Some repository settings could not be updated"

for topic in grok-build termux android rust bionic cli tui; do
  gh repo edit "$REPO" --add-topic "$topic" >/dev/null || true
done

create_label() {
  local name="$1" color="$2" description="$3"
  gh label create "$name" -R "$REPO" --color "$color" --description "$description" --force >/dev/null
}

log "Creating/updating labels"
create_label "epic" "5319E7" "Umbrella issue spanning multiple deliverables"
create_label "termux" "008672" "Termux-specific work"
create_label "android" "3DDC84" "Android platform work"
create_label "P0" "B60205" "Blocks a usable native port"
create_label "P1" "D93F0B" "Required before a stable release"
create_label "P2" "1D76DB" "Follow-up hardening or maintainability"
create_label "platform" "0E8A16" "Platform abstraction and capability detection"
create_label "build" "0052CC" "Build system, toolchain, ABI, or linker"
create_label "dependencies" "0366D6" "Dependency graph and feature gating"
create_label "auth" "6F42C1" "Authentication, OAuth, or credentials"
create_label "network" "1D76DB" "DNS, TLS, proxy, or connectivity"
create_label "filesystem" "C2E0C6" "Paths, storage, permissions, or sockets"
create_label "runtime" "5319E7" "Runtime behavior and process lifecycle"
create_label "security" "B60205" "Security boundaries and sandbox behavior"
create_label "distribution" "FBCA04" "Packaging, releases, installers, or updater"
create_label "testing" "C5DEF5" "CI, integration tests, or device validation"
create_label "documentation" "0075CA" "Documentation and migration guidance"
create_label "upstream-sync" "EDEDED" "Keeping the fork synchronized with upstream"
create_label "ux" "D4C5F9" "Termux-facing user experience"

MILESTONE_NUMBER="$(gh api --paginate "repos/$REPO/milestones?state=all&per_page=100" \
  | jq -r --arg title "$MILESTONE" '.[] | select(.title == $title) | .number' \
  | head -n1)"
if [[ -z "$MILESTONE_NUMBER" ]]; then
  log "Creating milestone $MILESTONE"
  MILESTONE_NUMBER="$(gh api -X POST "repos/$REPO/milestones" \
    -f title="$MILESTONE" \
    -f description="First native Bionic-based Grok Build release for Termux; no musl byte patch and no PRoot requirement." \
    --jq .number)"
fi

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

find_issue_url() {
  local title="$1"
  gh issue list -R "$REPO" --state all --limit 200 --json title,url \
    | jq -r --arg title "$title" '.[] | select(.title == $title) | .url' \
    | head -n1
}

create_issue() {
  local title="$1" labels="$2" parent="${3:-}"
  local body_file="$TMP_ROOT/$(printf '%s' "$title" | sha256sum | cut -d' ' -f1).md"
  cat > "$body_file"

  local existing
  existing="$(find_issue_url "$title")"
  if [[ -n "$existing" ]]; then
    printf 'Already exists: %s\n' "$existing" >&2
    printf '%s\n' "$existing"
    return 0
  fi

  local -a args=(issue create -R "$REPO" --title "$title" --body-file "$body_file" --label "$labels" --milestone "$MILESTONE")
  if [[ -n "$parent" ]]; then
    args+=(--parent "$parent")
  fi

  local url
  url="$(gh "${args[@]}")"
  printf 'Created: %s\n' "$url" >&2
  printf '%s\n' "$url"
}

issue_number() { printf '%s\n' "${1##*/}"; }

link_blocked_by() {
  local issue="$1" blocker="$2"
  gh issue edit "$issue" -R "$REPO" --add-blocked-by "$blocker" >/dev/null 2>&1 || \
    warn "Could not add blocked-by relation: #$issue <- #$blocker"
}

log "Creating the Termux port backlog"

EPIC_URL="$({
  printf 'Baseline: `%s@%s` on branch `%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA" "$UPSTREAM_BRANCH"
  cat <<'EOF'
## Goal

Ship a first-class, native Termux port of Grok Build that targets Android/Bionic directly rather than running the Linux musl artifact through byte patches or requiring PRoot.

## Definition of done

- A native `aarch64-linux-android` binary starts and runs in stock Termux.
- OAuth discovery, browser login, loopback callback, and manual-code fallback work.
- TUI, shell tools, Git operations, file edits, MCP, hooks, headless mode, and session resume work on-device.
- Termux paths, browser integration, optional clipboard support, process lifecycle, and update behavior are explicit and tested.
- Unsupported desktop capabilities are disabled or degraded without crashes or misleading claims.
- Package-managed installs cannot self-update into an upstream Linux artifact.
- Security status truthfully distinguishes policy enforcement from kernel-enforced sandboxing.
- Release gates cover real Android devices, including 4 KiB and 16 KiB page-size environments.

## Non-goals for the first native release

- Treating a patched `linux-aarch64`/musl binary as the final architecture.
- Treating PRoot as the primary runtime or as a security boundary.
- Claiming full image/file clipboard or microphone parity before an Android-native backend exists.

## Delivery order

1. Platform truth and native build.
2. Dependency/feature cleanup, paths, auth, and runtime tools.
3. UX integration, sandbox truth, lifecycle hardening, and release packaging.
4. Device matrix, documentation, and sustainable upstream synchronization.
EOF
} | create_issue "[EPIC] Native Android/Termux port of Grok Build" "epic,termux,android,P0")"
EPIC_NUM="$(issue_number "$EPIC_URL")"

PLATFORM_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Android satisfies Rust's `cfg(unix)`, but it is not a normal FHS Linux distribution. Existing decisions for config paths, browser opening, clipboard, desktop audio, sandboxing, updater artifacts, and bundled tools are spread across crates and can accidentally classify Android as desktop Linux or generic Unix.

## Scope

- Add one injectable source of truth for platform kind and capabilities.
- Distinguish at least desktop Linux, macOS, Windows, Android/Termux, and unsupported Android hosts.
- Derive Termux locations from environment/runtime facts such as `PREFIX`; do not hard-code one package name or `/data/data/com.termux`.
- Model capabilities such as URL opening, text clipboard, image clipboard, microphone, hard sandbox, package-managed updates, and background leader support.
- Make the result available to config, auth, pager/render, shell, tools, sandbox, updater, doctor, and release code with minimal upstream-conflict surface.
- Add environment-injected unit tests for Termux, non-Termux Android, and every existing desktop platform.

## Acceptance criteria

- `grok doctor` can report Android/Termux, ABI, prefix, home, temp/runtime path, page size, install mode, and capability flags.
- New Termux behavior does not depend on scattered `cfg!(unix)` checks.
- Non-Termux platform behavior and tests remain unchanged.
- Missing or malformed `PREFIX` fails with a useful diagnosis rather than silently using `/etc`, `/usr`, or `/tmp`.
- The implementation respects the upstream note that the root workspace manifest is generated and keeps recurring sync conflicts small.

## Likely touch points

- `crates/codegen/xai-grok-config/src/paths.rs`
- `crates/codegen/xai-grok-shared/src/clipboard.rs`
- `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
- `crates/codegen/xai-grok-pager-render/src/link_opener.rs`
- `crates/codegen/xai-grok-update/`
- `crates/codegen/xai-grok-sandbox/`
EOF
} | create_issue "[P0] Add a centralized Android/Termux platform capability layer" "termux,android,P0,platform" "$EPIC_NUM")"
PLATFORM_NUM="$(issue_number "$PLATFORM_URL")"

BUILD_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

The current released Linux ARM64 artifact is not a supported Android ABI target. Running it in Termux exposes resolver, filesystem, dependency, and updater mismatches even when the TUI happens to start.

## Scope

- Add a supported `aarch64-linux-android` build using the Android NDK and Bionic.
- Use an explicit Termux feature/profile rather than inheriting the desktop default feature set.
- Pin and document a reproducible NDK/Rust toolchain; prefer an NDK version whose default linker output supports 16 KiB page-size devices.
- Start with a justified minimum Android API level and record the reason in build/release docs.
- Keep optional `x86_64-linux-android` cross-build support available for emulator validation.
- Produce an artifact whose name identifies Android/Termux rather than Linux.

## Acceptance criteria

- `cargo build -p xai-grok-pager-bin --target aarch64-linux-android --release ...` succeeds in CI.
- ELF inspection proves the artifact does not require a glibc loader or ship a desktop Linux ABI by mistake.
- The artifact starts on a clean Termux installation and passes `--version`, `--help`, headless smoke, and TUI startup/terminal-restore tests.
- Native libraries are compatible with both 4 KiB and 16 KiB page-size Android devices.
- No binary byte patch or synthetic `/etc/resolv.conf` is required.

## Likely touch points

- `crates/codegen/xai-grok-pager-bin/Cargo.toml`
- `crates/codegen/xai-grok-pager-bin/src/main.rs`
- `.cargo/config.toml` or dedicated build scripts
- release workflows and artifact validation scripts
EOF
} | create_issue "[P0] Build a native aarch64-linux-android Bionic binary" "termux,android,P0,build" "$EPIC_NUM")"
BUILD_NUM="$(issue_number "$BUILD_URL")"
link_blocked_by "$BUILD_NUM" "$PLATFORM_NUM"

DEPS_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Several dependency and feature gates classify every Unix or every non-Linux platform as a supported desktop target. Android can therefore inherit jemalloc/profiling, desktop sandbox enforcement, `arboard`, and `cpal`/voice paths that are not valid for a Termux CLI.

## Scope

- Gate jemalloc and its profiling/stat hooks to supported desktop Unix targets, excluding Android unless separately proven.
- Make the Termux build use Bionic's allocator initially.
- Exclude `arboard` from Android and provide a platform backend seam instead of a fake desktop display.
- Disable microphone capture in the first Termux feature set; ensure `cpal` is not pulled into the Android dependency graph.
- Disable desktop hard-sandbox enforcement by default on Android while retaining policy-level checks.
- Audit other native/transitive dependencies for X11, Wayland, ALSA, AppKit, glibc, or unsupported syscalls.

## Acceptance criteria

- `cargo tree` for `aarch64-linux-android` contains no accidental desktop clipboard/audio stack and no glibc-only native dependency.
- Termux builds with an explicit feature set and no hidden dependency on desktop defaults.
- Disabled voice/image/file clipboard paths are not advertised and do not panic.
- Existing desktop release feature sets remain behaviorally unchanged.
- CI has compile guards preventing future `cfg(unix)` regressions from reintroducing these dependencies.

## Known starting points

- `crates/codegen/xai-grok-pager-bin/Cargo.toml`
- `crates/codegen/xai-grok-pager-bin/src/main.rs`
- `crates/codegen/xai-grok-shared/Cargo.toml`
- `crates/codegen/xai-grok-voice/Cargo.toml`
EOF
} | create_issue "[P0] Gate desktop-only allocators, sandbox, clipboard, and voice dependencies on Android" "termux,android,P0,dependencies,build" "$EPIC_NUM")"
DEPS_NUM="$(issue_number "$DEPS_URL")"
link_blocked_by "$DEPS_NUM" "$PLATFORM_NUM"

PATHS_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Generic Unix paths such as `/etc/grok` and assumptions around `/tmp`, runtime sockets, executable extraction, permissions, and symlinks do not map cleanly to Termux. Android shared storage also lacks the security and filesystem semantics required for credentials, session state, binaries, and atomic updates.

## Scope

- Resolve system config under `$PREFIX/etc/grok` and temporary/runtime state under Termux-owned locations.
- Keep user state under a private `$HOME/.grok` by default.
- Audit all absolute FHS paths and external command locations.
- Keep auth, sessions, hooks, caches containing private data, update staging, and extracted executables off shared storage.
- Permit shared-storage workspaces only with an explicit capability/warning model; disable features that require unsupported permissions or symlink semantics instead of corrupting state.
- Use short, hashed Unix-socket paths under a Termux runtime directory and clean stale sockets safely.
- Preserve owner-only permissions where the filesystem supports them and fail closed for credential storage when it does not.

## Acceptance criteria

- No Termux code path reads or writes `/etc/grok`, `/usr/bin`, `/bin`, or desktop `/tmp` by assumption.
- `GROK_HOME` on Android shared storage is rejected with a precise remediation message.
- A workspace on shared storage cannot cause credentials, hooks, vendor executables, or update payloads to be stored there implicitly.
- Auth/session persistence, atomic writes, symlink checks, socket startup, and stale-socket recovery pass on a real device.
- Existing macOS/Linux/Windows path behavior is unchanged.

## Known starting point

- `crates/codegen/xai-grok-config/src/paths.rs`
EOF
} | create_issue "[P0] Make config, runtime, socket, and storage paths Termux-safe" "termux,android,P0,filesystem,security" "$EPIC_NUM")"
PATHS_NUM="$(issue_number "$PATHS_URL")"
link_blocked_by "$PATHS_NUM" "$PLATFORM_NUM"

AUTH_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

The OIDC flow already has a loopback callback and manual-paste fallback, but browser opening uses a desktop-oriented backend and current Linux artifacts can fail before login during OIDC discovery. Termux users need a native resolver path and actionable diagnostics rather than a generic `error sending request for url`.

## Scope

- Route OAuth browser opening through the platform capability layer and `termux-open-url` when available.
- Preserve the `127.0.0.1` loopback callback and bare-code/full-callback-URL paste paths.
- Use the Android/Bionic resolver by virtue of the native target; do not hard-code public DNS servers or mutate `/etc/resolv.conf`.
- Add structured network diagnostics for DNS, TCP, TLS, HTTP status, OIDC discovery, IPv4/IPv6, proxy environment, custom CA, VPN/Private DNS symptoms, and loopback binding.
- Make failures identify the failing stage and retain the underlying error chain.
- Cover both the pager UI flow and non-interactive/headless login entry points.

## Acceptance criteria

- Login works on stock Termux over Wi-Fi and mobile data without a resolver patch.
- Opening the auth URL works without X11/Wayland; when it cannot open, the URL and manual instructions remain usable.
- Mock OIDC tests cover loopback callback, manual code, discovery failure, TLS failure, and browser-opener failure.
- Credentials are written only to the private path defined by the filesystem issue.
- Existing desktop OAuth behavior remains unchanged.

## Known starting points

- `crates/codegen/xai-grok-shell/src/auth/oidc/login.rs`
- `crates/codegen/xai-grok-shell/src/auth/oidc/protocol.rs`
- pager doctor/diagnostics modules
EOF
} | create_issue "[P0] Make OAuth login and network diagnostics native to Termux" "termux,android,P0,auth,network" "$EPIC_NUM")"
AUTH_NUM="$(issue_number "$AUTH_URL")"
link_blocked_by "$AUTH_NUM" "$PLATFORM_NUM"
link_blocked_by "$AUTH_NUM" "$BUILD_NUM"
link_blocked_by "$AUTH_NUM" "$PATHS_NUM"

TOOLS_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Release build scripts currently download/embed desktop Linux or macOS assets for tools such as `rg` and `fd`, with unsupported-target failures for Android. Shipping a Linux binary inside an otherwise native Android executable would reintroduce ABI and loader failures at runtime.

## Scope

- Make Android release builds skip automatic desktop asset bundling unless an explicitly supplied binary is verified as Android/Bionic-compatible.
- Resolve native Termux tools from `$PATH`, including at least `bash`, `git`, `rg`, and `fd` where enabled.
- Define package dependencies and graceful fallback behavior for optional `bfs`/`ugrep` features.
- Keep extracted executables and vendor caches in private executable storage, never shared storage.
- Validate child-process spawn, cancellation, signals, pipes, redirects, PTY behavior, and exit-status handling under Android.
- Report missing dependencies with exact `pkg install ...` remediation.

## Acceptance criteria

- Android release builds do not download a `*-unknown-linux-*` tool artifact automatically.
- Search, file discovery, Git, shell execution, cancellation, and timeout smoke tests pass in stock Termux.
- Missing optional tools degrade explicitly without crashing the agent.
- Explicit bundle overrides are rejected when the ELF target/loader is incompatible.
- Desktop bundling behavior and checksum verification remain intact.

## Known starting points

- `crates/codegen/xai-grok-shell/build.rs`
- `crates/codegen/xai-grok-tools/build.rs`
- runtime resolvers under `xai-grok-shell` and `xai-grok-tools`
EOF
} | create_issue "[P0] Use native Termux runtime tools instead of bundled Linux executables" "termux,android,P0,build,runtime,dependencies" "$EPIC_NUM")"
TOOLS_NUM="$(issue_number "$TOOLS_URL")"
link_blocked_by "$TOOLS_NUM" "$BUILD_NUM"
link_blocked_by "$TOOLS_NUM" "$PATHS_NUM"

UX_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Desktop link, clipboard, image/file paste, and microphone assumptions cannot simply be exposed unchanged in a terminal-only Android host. Termux needs capability-driven integration and honest graceful fallbacks.

## Scope

- Use the shared Android URL opener for every TUI link/CTA, not only OAuth.
- Add optional text clipboard integration through `termux-clipboard-get` / `termux-clipboard-set` when Termux:API is available.
- Keep OSC 52 as an appropriate copy fallback; do not pretend it can read clipboard contents.
- Hide or clearly disable image/file clipboard ingestion on the initial port unless a tested Android implementation exists.
- Keep voice/microphone UI disabled by capability, with a future backend seam rather than a crashing `cpal` path.
- Ensure Unicode, CJK IME, bracketed paste, text selection, tmux/screen, terminal resize, Ctrl+C, and terminal restoration remain correct.

## Acceptance criteria

- The TUI starts and all normal text workflows function with no Termux:API app/package installed.
- Installing Termux:API enables text clipboard operations without changing the core binary.
- Missing helpers produce a short capability message, not a stack trace or startup failure.
- Every URL-opening surface uses the same tested platform service.
- Unsupported image/file/voice controls are not misleadingly presented as functional.
EOF
} | create_issue "[P1] Integrate Termux browser and text clipboard with graceful capability fallbacks" "termux,android,P1,ux,runtime" "$EPIC_NUM")"
UX_NUM="$(issue_number "$UX_URL")"
link_blocked_by "$UX_NUM" "$PLATFORM_NUM"
link_blocked_by "$UX_NUM" "$DEPS_NUM"

SECURITY_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

The desktop sandbox model is built around platform-specific kernel mechanisms. An Android/Termux build must not silently downgrade while still presenting itself as kernel-confined, and PRoot must not be described as a security boundary.

## Scope

- Introduce an explicit Termux sandbox state such as `policy-only`, distinct from kernel-enforced and off.
- Retain tool allow/deny rules, permission prompts, workspace path validation, sensitive-path protection, hook/config write protection, and shared-storage restrictions.
- Disable claims of filesystem/network kernel confinement unless a real Android kernel mechanism is probed and verified on-device.
- Audit subprocess inheritance, environment leakage, credential paths, symlink/hardlink handling, executable staging, and workspace escapes on Android filesystems.
- Add a future-compatible probe seam for Android Landlock or another enforceable kernel mechanism without making it a release prerequisite.

## Acceptance criteria

- UI, `grok doctor`, logs, and docs all report the actual sandbox strength.
- A policy-only Termux build never labels itself `sandbox-enforced`.
- Security-sensitive operations fail closed when required filesystem semantics are unavailable.
- Tests cover shared-storage escape attempts, symlink traversal, protected config/auth writes, and unsupported hard-sandbox requests.
- Desktop sandbox behavior and wording remain unchanged.
EOF
} | create_issue "[P1] Provide truthful policy-only sandboxing and Android security guards" "termux,android,P1,security,runtime" "$EPIC_NUM")"
SECURITY_NUM="$(issue_number "$SECURITY_URL")"
link_blocked_by "$SECURITY_NUM" "$PLATFORM_NUM"
link_blocked_by "$SECURITY_NUM" "$DEPS_NUM"
link_blocked_by "$SECURITY_NUM" "$PATHS_NUM"

LIFECYCLE_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Long-running coding-agent sessions create child processes, sockets, background tasks, and checkpoint state. Android may suspend or kill the host process, and aggressive desktop concurrency can be unreliable on a mobile device.

## Scope

- Define conservative Termux defaults for leader mode, subagent concurrency, Tokio blocking threads, and detached/background processes.
- Make every completed model/tool/edit transaction recoverable through durable session checkpoints.
- Handle SIGINT/SIGTERM/SIGHUP, stale leader sockets, orphaned child processes, interrupted edits, and restart/resume deterministically.
- Add optional active-task wake-lock integration through Termux helpers with guaranteed cleanup on idle, cancel, normal exit, and panic paths.
- Keep wake locks opt-in or narrowly scoped; never use them as a substitute for persistence.
- Add diagnostics for low-memory/process-limit symptoms and actionable tuning.

## Acceptance criteria

- A killed process can restart and resume without corrupting session history or leaving an ambiguous edit transaction.
- Screen-off/background tests do not silently lose a completed tool result.
- Child processes are cancelled/reaped and terminal state is restored after interruption.
- Wake lock acquisition/release is balanced in success, error, cancellation, and crash-recovery tests.
- Termux defaults reduce process pressure without changing desktop defaults.
EOF
} | create_issue "[P1] Harden process lifecycle, concurrency, wake locks, and session resume on Android" "termux,android,P1,runtime" "$EPIC_NUM")"
LIFECYCLE_NUM="$(issue_number "$LIFECYCLE_URL")"
link_blocked_by "$LIFECYCLE_NUM" "$BUILD_NUM"
link_blocked_by "$LIFECYCLE_NUM" "$PATHS_NUM"

DIST_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

The upstream updater and installers target macOS, desktop Linux, and Windows. A Termux package must never replace itself with an upstream Linux artifact, while a standalone Termux install needs its own signed release channel and ABI-specific artifact.

## Scope

- Model at least package-managed Termux installs, standalone Termux installs, and upstream desktop installs as distinct modes.
- Disable in-app binary replacement for package-managed installs and direct users to `pkg upgrade`.
- Point standalone Termux updates only at this fork's Android/Termux artifacts and manifests.
- Use unambiguous artifact names such as `grok-<version>-termux-aarch64`; never alias them to `linux-aarch64`.
- Publish checksums and signed provenance; verify before activation and retain rollback-safe atomic replacement.
- Provide a Termux package recipe with explicit runtime dependencies and a separate reviewed standalone installer.
- Preserve upstream LICENSE, NOTICE, and third-party notices and identify the port as unofficial.

## Acceptance criteria

- No Termux install mode can download or activate an upstream desktop Linux binary.
- Package installs report the package manager as the update mechanism.
- Standalone updates verify target ABI, checksum/signature, smoke-test the staged binary, and roll back on failure.
- Release artifacts pass native ELF, dependency, page-size, and clean-install checks.
- Installer reruns are idempotent and never place executables or secrets on shared storage.

## Known starting point

- `crates/codegen/xai-grok-update/`
EOF
} | create_issue "[P1] Add Termux-native packaging, release artifacts, and updater isolation" "termux,android,P1,distribution,security" "$EPIC_NUM")"
DIST_NUM="$(issue_number "$DIST_URL")"
link_blocked_by "$DIST_NUM" "$BUILD_NUM"
link_blocked_by "$DIST_NUM" "$TOOLS_NUM"
link_blocked_by "$DIST_NUM" "$PATHS_NUM"
link_blocked_by "$DIST_NUM" "$SECURITY_NUM"

CI_URL="$({
  printf 'Baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

Cross-compilation alone cannot prove that authentication, TUI/PTY behavior, Android resolver integration, filesystem semantics, process lifecycle, and page-size compatibility work in real Termux environments.

## Scope

Create a two-level validation system:

1. Hosted CI for cross-builds, dependency audits, ELF/ABI checks, unit tests, and artifact reproducibility.
2. A real-device/self-hosted Termux suite for runtime behavior that emulators or generic Linux runners cannot establish.

The device matrix should cover:

- At least AArch64 Android environments with 4 KiB and 16 KiB page sizes.
- Clean Termux with and without optional Termux:API helpers.
- Wi-Fi/mobile, IPv4/IPv6, VPN/Private DNS, proxy, and loopback callback scenarios where practical.
- TUI startup/restore, resize, CJK input, bracketed paste, tmux, Ctrl+C, and headless mode.
- Shell/Git/search/file-edit/MCP/session-resume flows.
- Screen off, app backgrounding, forced process termination, low storage, and stale socket recovery.
- Package install, standalone install, update refusal/isolation, and rollback.

## Acceptance criteria

- Pull requests cannot publish a Termux release unless hosted checks pass.
- A release candidate has a recorded real-device result matrix and machine-readable report.
- Tests verify the binary is Bionic/Android-native and 16 KiB-page compatible.
- Upstream desktop CI remains green and is not weakened to accommodate the port.
- Failures preserve logs without leaking auth tokens, local identities, private paths, or session content.
EOF
} | create_issue "[P1] Add Android cross-build CI and a real-device Termux release matrix" "termux,android,P1,testing,build" "$EPIC_NUM")"
CI_NUM="$(issue_number "$CI_URL")"
link_blocked_by "$CI_NUM" "$BUILD_NUM"
link_blocked_by "$CI_NUM" "$AUTH_NUM"
link_blocked_by "$CI_NUM" "$TOOLS_NUM"

DOCS_URL="$({
  printf 'Initial baseline: `%s@%s`.\n\n' "$UPSTREAM" "$UPSTREAM_SHA"
  cat <<'EOF'
## Problem

The repository is periodically synced from an internal monorepo, and the root workspace manifest is generated. A long-lived Termux fork needs a low-conflict patch strategy, explicit provenance, and documentation that does not confuse users about official support or platform guarantees.

## Scope

- Keep a clean upstream-tracking branch and a separate Termux integration branch/patch stack.
- Record the exact upstream commit/source revision used by every Termux release.
- Add an automated scheduled sync that opens a reviewable PR rather than force-overwriting downstream work.
- Categorize downstream patches by platform, build, runtime, security, distribution, and tests so conflicts are isolated.
- Document native installation, source builds, required Termux packages, optional Termux:API integration, troubleshooting, logs/doctor output, updater behavior, and uninstall.
- Document capability differences: text clipboard, image/file clipboard, voice, hard sandbox, background operation, and shared-storage caveats.
- Preserve Apache-2.0 obligations and upstream/third-party notices; state clearly that the port is unofficial.

## Acceptance criteria

- A maintainer can rebase/sync to a new upstream snapshot using a documented, repeatable procedure.
- Sync automation never force-pushes over Termux changes and reports conflicts precisely.
- README instructions work from a clean supported Termux install.
- Every release names its upstream commit and downstream patch revision.
- Support claims match runtime capability reporting and security wording.
EOF
} | create_issue "[P2] Document the Termux port and maintain a low-conflict upstream sync workflow" "termux,android,P2,documentation,upstream-sync" "$EPIC_NUM")"
DOCS_NUM="$(issue_number "$DOCS_URL")"
link_blocked_by "$DOCS_NUM" "$DIST_NUM"
link_blocked_by "$DOCS_NUM" "$CI_NUM"

log "Backlog ready"
printf '\nRepository: https://github.com/%s\n' "$REPO"
printf 'Upstream baseline: %s@%s\n' "$UPSTREAM" "$UPSTREAM_SHA"
printf 'Epic: %s\n' "$EPIC_URL"
printf 'Milestone: https://github.com/%s/milestone/%s\n' "$REPO" "$MILESTONE_NUMBER"
printf '\nCreated/verified child issues:\n'
printf '  %s\n' \
  "$PLATFORM_URL" "$BUILD_URL" "$DEPS_URL" "$PATHS_URL" "$AUTH_URL" "$TOOLS_URL" \
  "$UX_URL" "$SECURITY_URL" "$LIFECYCLE_URL" "$DIST_URL" "$CI_URL" "$DOCS_URL"
