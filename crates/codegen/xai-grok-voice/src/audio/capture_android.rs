use crate::error::VoiceError;
use crate::probe::InputDeviceInfo;

pub struct CaptureHandle;

impl CaptureHandle {
    pub fn stop(&self) {}
}

pub fn input_device_info() -> Result<InputDeviceInfo, VoiceError> {
    Err(VoiceError::Config(
        "Audio capture is not supported on Android/Termux".into(),
    ))
}

pub fn spawn_pcm_capture(
    _sample_rate: u32,
    _pcm_tx: tokio::sync::mpsc::Sender<Vec<u8>>,
) -> Result<CaptureHandle, VoiceError> {
    Err(VoiceError::Config(
        "Audio capture is not supported on Android/Termux".into(),
    ))
}

pub fn capture_pcm_for_duration(
    _sample_rate: u32,
    _seconds: u32,
) -> Result<(Vec<u8>, u32), VoiceError> {
    Err(VoiceError::Config(
        "Audio capture is not supported on Android/Termux".into(),
    ))
}
