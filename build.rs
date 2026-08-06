fn main() {
    // Build the React frontend before compiling
    let ui_dir = std::path::Path::new("ui");
    if ui_dir.exists() {
        let status = std::process::Command::new("npm")
            .args(["run", "build"])
            .current_dir(ui_dir)
            .status();

        match status {
            Ok(s) if s.success() => {
                println!("cargo:warning=UI built successfully");
            }
            Ok(s) => {
                println!("cargo:warning=UI build failed with status: {s}");
            }
            Err(e) => {
                println!("cargo:warning=UI build skipped (npm not available): {e}");
            }
        }
    }
}
