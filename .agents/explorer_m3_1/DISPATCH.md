## 2026-08-15T17:31:00Z
Investigate System Configuration Resolution (Feature 10: `$PREFIX/etc/grok`) and User Home Directory Resolution (Feature 11: `$HOME/.grok`).
Examine `crates/codegen/xai-grok-config`, `crates/codegen/xai-grok-home`, and all places where global config, auth, and state paths are determined.
Determine what needs to be verified or implemented so that on Android/Termux:
1. System configuration resolves to `$PREFIX/etc/grok` (falling back to `/etc/grok` on desktop Linux).
2. User state, credentials, auth tokens, logs, and telemetry resolve exclusively to `$HOME/.grok` (or `$GROK_HOME` if set).
