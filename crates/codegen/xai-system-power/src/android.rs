//! Android / Termux system power management via `termux-wake-lock` / `termux-wake-unlock`.

use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

use super::{PowerCallback, PowerState};

pub(crate) struct Listener;

impl Listener {
    pub(crate) fn start(_callback: PowerCallback) -> Option<Self> {
        None
    }
}

pub(crate) fn current_power_state() -> PowerState {
    PowerState::FullWake
}

static WAKE_LOCK_COUNT: AtomicUsize = AtomicUsize::new(0);

#[derive(Debug)]
pub(crate) struct Assertion;

impl Drop for Assertion {
    fn drop(&mut self) {
        let prev = WAKE_LOCK_COUNT.fetch_sub(1, Ordering::SeqCst);
        if prev == 1 {
            let _ = Command::new("termux-wake-unlock")
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn();
        }
    }
}

pub(crate) fn hold_awake(_reason: &str) -> Option<Assertion> {
    let prev = WAKE_LOCK_COUNT.fetch_add(1, Ordering::SeqCst);
    if prev == 0 {
        let spawned = Command::new("termux-wake-lock")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn();
        match spawned {
            Ok(_) => Some(Assertion),
            Err(_) => {
                // If tool not found, decrement back and degrade gracefully
                WAKE_LOCK_COUNT.fetch_sub(1, Ordering::SeqCst);
                None
            }
        }
    } else {
        Some(Assertion)
    }
}
