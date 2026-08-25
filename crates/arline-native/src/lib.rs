use pyo3::exceptions::{PyIOError, PyValueError};
use pyo3::prelude::*;
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const STORAGE_VERSION: &str = "0.1.0";

fn io_error(context: &str, error: std::io::Error) -> PyErr {
    PyIOError::new_err(format!("{context}: {error}"))
}

fn digest_hex(data: &[u8]) -> String {
    let digest = Sha256::digest(data);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

fn validate_digest(digest: &str) -> PyResult<()> {
    if digest.len() != 64 || !digest.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(PyValueError::new_err(
            "Blob digest must be a 64-character SHA-256 hex string",
        ));
    }
    Ok(())
}

fn object_path(root: &Path, digest: &str) -> PyResult<PathBuf> {
    validate_digest(digest)?;
    let digest = digest.to_ascii_lowercase();
    Ok(root.join(&digest[0..2]).join(&digest[2..4]).join(digest))
}

fn atomic_put(root: &Path, data: &[u8]) -> PyResult<(String, PathBuf, bool, usize)> {
    if data.is_empty() {
        return Err(PyValueError::new_err("Cannot store an empty blob"));
    }
    let digest = digest_hex(data);
    let target = object_path(root, &digest)?;
    let parent = target
        .parent()
        .ok_or_else(|| PyIOError::new_err("Blob target has no parent directory"))?;
    fs::create_dir_all(parent).map_err(|error| io_error("creating blob directory", error))?;
    if target.is_file() {
        return Ok((digest, target, false, data.len()));
    }

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let temp = parent.join(format!(
        ".{digest}.{}.{}.tmp",
        std::process::id(),
        nonce
    ));

    let result = (|| -> PyResult<()> {
        let mut handle = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)
            .map_err(|error| io_error("creating temporary blob", error))?;
        handle
            .write_all(data)
            .map_err(|error| io_error("writing temporary blob", error))?;
        handle
            .sync_all()
            .map_err(|error| io_error("syncing temporary blob", error))?;
        match fs::rename(&temp, &target) {
            Ok(()) => Ok(()),
            Err(error) if target.is_file() => {
                let _ = fs::remove_file(&temp);
                let _ = error;
                Ok(())
            }
            Err(error) => Err(io_error("committing blob", error)),
        }
    })();

    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result?;
    Ok((digest, target, true, data.len()))
}

#[pyfunction]
fn sha256_hex(data: &[u8]) -> String {
    digest_hex(data)
}

#[pyfunction]
fn storage_version() -> &'static str {
    STORAGE_VERSION
}

#[pyclass(module = "_arline_native")]
struct BlobStore {
    root: PathBuf,
}

#[pymethods]
impl BlobStore {
    #[new]
    fn new(root: String) -> PyResult<Self> {
        let root = PathBuf::from(root);
        fs::create_dir_all(&root).map_err(|error| io_error("creating blob root", error))?;
        Ok(Self { root })
    }

    #[getter]
    fn backend(&self) -> &'static str {
        "rust"
    }

    #[getter]
    fn root(&self) -> String {
        self.root.to_string_lossy().into_owned()
    }

    fn resolve(&self, digest: String) -> PyResult<String> {
        Ok(object_path(&self.root, &digest)?
            .to_string_lossy()
            .into_owned())
    }

    fn exists(&self, digest: String) -> PyResult<bool> {
        Ok(object_path(&self.root, &digest)?.is_file())
    }

    fn put_bytes(&self, data: &[u8]) -> PyResult<(String, String, bool, usize)> {
        let (digest, path, created, size) = atomic_put(&self.root, data)?;
        Ok((digest, path.to_string_lossy().into_owned(), created, size))
    }

    fn put_file(&self, path: String) -> PyResult<(String, String, bool, usize)> {
        let source = PathBuf::from(path);
        let data = fs::read(&source).map_err(|error| io_error("reading source blob", error))?;
        self.put_bytes(&data)
    }

    fn remove(&self, digest: String) -> PyResult<bool> {
        let path = object_path(&self.root, &digest)?;
        match fs::remove_file(&path) {
            Ok(()) => {
                if let Some(parent) = path.parent() {
                    let _ = fs::remove_dir(parent);
                    if let Some(grandparent) = parent.parent() {
                        if grandparent != self.root {
                            let _ = fs::remove_dir(grandparent);
                        }
                    }
                }
                Ok(true)
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(io_error("removing blob", error)),
        }
    }
}

#[pymodule]
fn _arline_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<BlobStore>()?;
    module.add_function(wrap_pyfunction!(sha256_hex, module)?)?;
    module.add_function(wrap_pyfunction!(storage_version, module)?)?;
    module.add("STORAGE_VERSION", STORAGE_VERSION)?;
    Ok(())
}
