use serde_json::{json, Value};

#[cfg(windows)]
pub fn memory() -> Value {
    #[repr(C)]
    #[derive(Default)]
    struct Counters {
        cb: u32,
        page_faults: u32,
        peak_working_set: usize,
        working_set: usize,
        peak_paged: usize,
        paged: usize,
        peak_nonpaged: usize,
        nonpaged: usize,
        pagefile: usize,
        peak_pagefile: usize,
        private: usize,
    }
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn GetCurrentProcess() -> *mut std::ffi::c_void;
        fn K32GetProcessMemoryInfo(
            process: *mut std::ffi::c_void,
            counters: *mut Counters,
            size: u32,
        ) -> i32;
    }
    let mut counters = Counters {
        cb: std::mem::size_of::<Counters>() as u32,
        ..Default::default()
    };
    // SAFETY: correctly sized PROCESS_MEMORY_COUNTERS_EX buffer and the current
    // process pseudo-handle; this is a read-only process-memory query.
    let ok = unsafe {
        K32GetProcessMemoryInfo(
            GetCurrentProcess(),
            &mut counters,
            std::mem::size_of::<Counters>() as u32,
        )
    };
    if ok == 0 {
        Value::Null
    } else {
        json!({"resident_bytes":counters.working_set,"peak_resident_bytes":counters.peak_working_set,"private_bytes":counters.private})
    }
}
#[cfg(not(windows))]
pub fn memory() -> Value {
    let Ok(status) = std::fs::read_to_string("/proc/self/status") else {
        return Value::Null;
    };
    let kb = |key: &str| {
        status
            .lines()
            .find(|l| l.starts_with(key))
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|v| v.parse::<u64>().ok())
            .map(|v| v * 1024)
    };
    json!({"resident_bytes":kb("VmRSS:"),"peak_resident_bytes":kb("VmHWM:")})
}
