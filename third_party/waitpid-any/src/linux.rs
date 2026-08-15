use std::io::{Error, ErrorKind, Result};
use std::time::Duration;

#[cfg(unix)]
use std::os::fd::FromRawFd;

use rustix::event::{poll, PollFd, PollFlags};
use rustix::io::Errno;

pub type WaitHandle = rustix::fd::OwnedFd;

pub fn open(pid: i32) -> Result<WaitHandle> {
    if pid <= 0 {
        return Err(Error::new(ErrorKind::InvalidInput, format!("invalid PID {pid}")));
    }
    #[cfg(target_os = "linux")]
    {
        use rustix::process::{pidfd_open, Pid, PidfdFlags};
        let pid = Pid::from_raw(pid)
            .ok_or_else(|| Error::new(ErrorKind::InvalidInput, format!("invalid PID {pid}")))?;
        let pidfd = pidfd_open(pid, PidfdFlags::empty())?;
        Ok(pidfd)
    }
    #[cfg(target_os = "android")]
    {
        const SYS_PIDFD_OPEN: libc::c_long = 434;

        let res = unsafe { libc::syscall(SYS_PIDFD_OPEN, pid as libc::pid_t, 0u32) };
        if res < 0 {
            return Err(Error::last_os_error());
        }
        let raw_fd = res as std::os::fd::RawFd;
        unsafe { Ok(rustix::fd::OwnedFd::from_raw_fd(raw_fd)) }
    }
}

pub fn wait(pidfd: &mut WaitHandle, timeout: Option<Duration>) -> Result<Option<()>> {
    let timespec = match timeout {
        Some(dur) => Some(dur.try_into().map_err(|_| Errno::INVAL)?),
        // Infinite.
        None => None,
    };
    let mut fds = [PollFd::new(&*pidfd, PollFlags::IN)];
    let ret = poll(&mut fds, timespec.as_ref())?;
    if ret == 0 {
        // Timeout.
        return Ok(None);
    }
    debug_assert!(fds[0].revents().contains(PollFlags::IN));
    Ok(Some(()))
}
