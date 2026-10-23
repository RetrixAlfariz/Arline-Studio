use std::{env, fs, path::Path};

fn collect(dir: &Path, base: &Path, prefix: &str, output: &mut String) {
    if !dir.is_dir() {
        return;
    }
    let mut files: Vec<_> = fs::read_dir(dir)
        .expect("read UI assets")
        .flatten()
        .collect();
    files.sort_by_key(|entry| entry.path());
    for entry in files {
        let path = entry.path();
        if path.is_dir() {
            collect(&path, base, prefix, output);
        } else if path.extension().is_none_or(|ext| ext != "map") {
            let relative = path.strip_prefix(base).expect("asset relative path");
            let route = format!("{prefix}/{}", relative.to_string_lossy().replace('\\', "/"));
            output.push_str(&format!(
                "({route:?}, include_bytes!({:?})),\n",
                path.canonicalize()
                    .expect("canonical asset")
                    .to_string_lossy()
            ));
            println!("cargo:rerun-if-changed={}", path.display());
        }
    }
}

fn main() {
    let manifest = env::var("CARGO_MANIFEST_DIR").expect("manifest directory");
    let root = Path::new(&manifest)
        .join("../..")
        .canonicalize()
        .expect("repository root");
    let mut output = String::from("pub static EMBEDDED_ASSETS: &[(&str, &[u8])] = &[\n");
    collect(
        &root.join("frontend/dist"),
        &root.join("frontend/dist"),
        "",
        &mut output,
    );
    collect(
        &root.join("src/interface/web/static/assets"),
        &root.join("src/interface/web/static/assets"),
        "/static/assets",
        &mut output,
    );
    output.push_str("];\n");
    fs::write(
        Path::new(&env::var("OUT_DIR").unwrap()).join("assets.rs"),
        output,
    )
    .expect("write embedded asset map");
    println!(
        "cargo:rerun-if-changed={}",
        root.join("frontend/dist").display()
    );
    #[cfg(feature = "desktop")]
    tauri_build::build();
}
