#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;

#[tauri::command]
fn read_lockfile() -> Option<(u16, String)> {
  fn try_path(p: PathBuf) -> Option<(u16, String)> {
    if p.exists() {
      if let Ok(txt) = std::fs::read_to_string(&p) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) {
          let port = v.get("port").and_then(|x| x.as_u64()).unwrap_or(0) as u16;
          let tok = v.get("token").and_then(|x| x.as_str()).unwrap_or("").to_string();
          if port != 0 { return Some((port, tok)); }
        }
      }
    }
    None
  }

  if let Some(pd) = std::env::var_os("ProgramData") {
    let mut p = PathBuf::from(pd);
    p.push("NeuractLogger\\agent\\agent.lock.json");
    if let Some(t) = try_path(p) { return Some(t); }
  }

  if let Some(ld) = std::env::var_os("LOCALAPPDATA") {
    let mut p = PathBuf::from(ld);
    p.push("NeuractLogger\\agent\\agent.lock.json");
    if let Some(t) = try_path(p) { return Some(t); }
  }

  let mut p = std::env::current_dir().unwrap_or_default();
  p.push("agent.dev.lock.json");
  try_path(p)
}

#[tauri::command]
fn frontout_log(line: String) -> Result<(), String> {
  use std::io::Write;

  fn try_env() -> Option<PathBuf> {
    std::env::var("PLC_FRONTOUT_PATH").ok().map(PathBuf::from)
  }

  fn find_upwards(target: &str) -> Option<PathBuf> {
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
      if let Some(p) = exe.parent() { cands.push(p.to_path_buf()); }
    }
    if let Ok(cwd) = std::env::current_dir() { cands.push(cwd); }
    for mut base in cands {
      for _ in 0..6 {
        let mut f = base.clone();
        f.push(target);
        if f.exists() { return Some(f); }
        if !base.pop() { break; }
      }
    }
    None
  }

  fn default_data() -> PathBuf {
    if let Some(ld) = std::env::var_os("LOCALAPPDATA") {
      let mut d = PathBuf::from(ld);
      d.push("NeuractLogger");
      d.push("frontout.md");
      return d;
    }
    let mut d = std::env::current_exe()
      .ok()
      .and_then(|p| p.parent().map(|x| x.to_path_buf()))
      .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    d.push("frontout.md");
    d
  }

  let path = try_env()
    .or_else(|| find_upwards("frontout.md"))
    .unwrap_or_else(default_data);
  if let Some(parent) = path.parent() {
    let _ = std::fs::create_dir_all(parent);
  }
  match std::fs::OpenOptions::new().create(true).append(true).open(&path) {
    Ok(mut f) => {
      let _ = writeln!(f, "{}", line);
      Ok(())
    }
    Err(e) => Err(format!("open {:?} failed: {}", path, e)),
  }
}

fn main() {
  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![read_lockfile, frontout_log])
    .setup(|_| {
      let _ = frontout_log("tauri_setup".to_string());
      Ok(())
    })
    .on_page_load(|_window, payload| {
      let _ = frontout_log(format!("page_load url={}", payload.url()));
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri app");
}

