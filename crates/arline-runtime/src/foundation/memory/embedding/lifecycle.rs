//! Session-cache pattern adapted from Verithen semantic_native.rs (MIT OR Apache-2.0).
//! Unlike Verithen's process singleton, each Arline AppState owns its cache.
#![cfg_attr(not(any(feature = "native-bekko", test)), allow(dead_code))]
use super::{EmbeddingError, ErrorKind, Result};
use serde::Serialize;
use std::{
    panic::{catch_unwind, AssertUnwindSafe},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Condvar, Mutex,
    },
    time::{Duration, Instant},
};

struct Loaded<M> {
    key: String,
    model: M,
    last_used: Instant,
    ttl: Duration,
}
struct State<M> {
    loaded: Option<Loaded<M>>,
    worker_running: bool,
    loads: u64,
    evictions: u64,
    failures: u64,
    last_error: Option<EmbeddingError>,
}
pub(super) struct ModelCache<M> {
    state: Mutex<State<M>>,
    changed: Condvar,
    stopped: AtomicBool,
}

#[derive(Debug, Serialize)]
pub struct Diagnostics {
    pub compiled: bool,
    pub busy: bool,
    pub loaded: bool,
    pub session_key: Option<String>,
    pub successful_loads: u64,
    pub evictions: u64,
    pub failures: u64,
    pub eviction_worker_running: bool,
    pub last_error: Option<EmbeddingError>,
    pub fallback: &'static str,
}
pub(super) struct ModelRun<R> {
    pub value: R,
    pub reused: bool,
    pub load_ms: f64,
    pub infer_ms: f64,
}

impl<M: Send + 'static> ModelCache<M> {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(State {
                loaded: None,
                worker_running: false,
                loads: 0,
                evictions: 0,
                failures: 0,
                last_error: None,
            }),
            changed: Condvar::new(),
            stopped: AtomicBool::new(false),
        })
    }
    pub fn shutdown(&self) {
        self.stopped.store(true, Ordering::Release);
        self.changed.notify_all();
    }
    pub fn clear(&self) {
        if let Ok(mut state) = self.state.lock() {
            state.loaded = None;
            self.changed.notify_all();
        }
    }
    pub fn invalidate(&self, error: &EmbeddingError) {
        if let Ok(mut state) = self.state.lock() {
            state.loaded = None;
            state.last_error = Some(error.clone());
            state.failures += 1;
            self.changed.notify_all();
        }
    }
    pub fn diagnostics(&self) -> Diagnostics {
        let mut out = Diagnostics {
            compiled: cfg!(feature = "native-bekko"),
            busy: false,
            loaded: false,
            session_key: None,
            successful_loads: 0,
            evictions: 0,
            failures: 0,
            eviction_worker_running: false,
            last_error: None,
            fallback: "fts5+structured",
        };
        match self.state.try_lock() {
            Ok(state) => {
                out.loaded = state.loaded.is_some();
                out.session_key = state.loaded.as_ref().map(|m| m.key.clone());
                out.successful_loads = state.loads;
                out.evictions = state.evictions;
                out.failures = state.failures;
                out.eviction_worker_running = state.worker_running;
                out.last_error = state.last_error.clone();
            }
            Err(_) => out.busy = true,
        }
        out
    }
    pub fn with_model<R>(
        self: &Arc<Self>,
        key: &str,
        ttl: Duration,
        load: impl FnOnce() -> Result<M>,
        infer: impl FnOnce(&mut M) -> Result<R>,
    ) -> Result<ModelRun<R>> {
        let mut state = self.state.lock().map_err(|_| {
            EmbeddingError::new(ErrorKind::Inference, "embedding cache lock poisoned")
        })?;
        if self.stopped.load(Ordering::Acquire) {
            return Err(EmbeddingError::new(
                ErrorKind::Shutdown,
                "embedding service closed",
            ));
        }
        if state
            .loaded
            .as_ref()
            .is_some_and(|m| m.key != key || m.last_used.elapsed() >= m.ttl)
        {
            state.loaded = None;
            state.evictions += 1;
        }
        let reused = state.loaded.is_some();
        let started = Instant::now();
        // Catch third-party library panics inside the mutex boundary so failed
        // initialization/inference cannot poison the cache for future requests.
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            if state.loaded.is_none() {
                state.loaded = Some(Loaded {
                    key: key.into(),
                    model: load()?,
                    last_used: Instant::now(),
                    ttl,
                });
                state.loads += 1;
            }
            let load_ms = if reused {
                0.0
            } else {
                started.elapsed().as_secs_f64() * 1000.0
            };
            let current = state.loaded.as_mut().expect("initialized session");
            let infer_start = Instant::now();
            let value = infer(&mut current.model)?;
            current.last_used = Instant::now();
            current.ttl = ttl;
            Ok(ModelRun {
                value,
                reused,
                load_ms,
                infer_ms: infer_start.elapsed().as_secs_f64() * 1000.0,
            })
        }))
        .unwrap_or_else(|_| {
            Err(EmbeddingError::new(
                ErrorKind::Inference,
                "native embedding library panicked; session discarded",
            ))
        });
        if outcome.is_err() || ttl.is_zero() || self.stopped.load(Ordering::Acquire) {
            state.loaded = None;
        } else if !state.worker_running {
            state.worker_running = true;
            let cache = self.clone();
            if std::thread::Builder::new()
                .name("arline-bekko-idle".into())
                .spawn(move || cache.evict())
                .is_err()
            {
                state.worker_running = false;
                state.loaded = None;
                return Err(EmbeddingError::new(
                    ErrorKind::Inference,
                    "cannot start idle eviction worker",
                ));
            }
        }
        if outcome.is_ok() {
            state.last_error = None;
        }
        self.changed.notify_all();
        outcome
    }
    fn evict(&self) {
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        loop {
            if self.stopped.load(Ordering::Acquire) {
                state.loaded = None;
            }
            let Some(loaded) = state.loaded.as_ref() else {
                state.worker_running = false;
                return;
            };
            let remaining = loaded.ttl.saturating_sub(loaded.last_used.elapsed());
            if remaining.is_zero() {
                state.loaded = None;
                state.evictions += 1;
                continue;
            }
            // shutdown() intentionally never blocks an async caller on an
            // inference mutex. Bound the wait so a shutdown notification racing
            // this wait cannot retain an otherwise orphaned session for its TTL.
            let Ok((next, _)) = self
                .changed
                .wait_timeout(state, remaining.min(Duration::from_secs(1)))
            else {
                return;
            };
            state = next;
        }
    }
}
