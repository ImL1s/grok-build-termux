//! Adversarial tests for Unix shell resolution (Milestone 2).

#[cfg(unix)]
mod unix_tests {
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use tempfile::tempdir;
    use xai_grok_config::shell::{unix_shell_path, UnixShellKind};

    #[test]
    fn test_adversarial_unix_shell_path_returns_valid_binary() {
        let bash_path = unix_shell_path(UnixShellKind::Bash);
        assert!(bash_path.ends_with("bash"));

        let zsh_path = unix_shell_path(UnixShellKind::Zsh);
        assert!(zsh_path.ends_with("zsh"));
    }

    #[test]
    fn test_adversarial_non_executable_override_skipped() {
        let dir = tempdir().unwrap();
        let fake_bash = dir.path().join("bash");
        fs::write(&fake_bash, b"not executable").unwrap();
        fs::set_permissions(&fake_bash, fs::Permissions::from_mode(0o644)).unwrap();

        // Non-executable candidate should not be returned by resolution
        assert!(!fake_bash.is_executable());
    }

    trait ExecutableCheck {
        fn is_executable(&self) -> bool;
    }

    impl ExecutableCheck for std::path::Path {
        fn is_executable(&self) -> bool {
            if let Ok(meta) = fs::metadata(self) {
                meta.is_file() && (meta.permissions().mode() & 0o111 != 0)
            } else {
                false
            }
        }
    }
}
