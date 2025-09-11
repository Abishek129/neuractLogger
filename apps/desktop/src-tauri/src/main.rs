#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;
use tauri::{Manager, AppHandle, Wry};
use tauri::tray::TrayIconBuilder;
use tauri::menu::{MenuBuilder, MenuItemBuilder};
use tauri_plugin_dialog::DialogExt;

fn open_logs() {
  if let Some(pd) = std::env::var_os("ProgramData") {
    let mut p = std::path::PathBuf::from(pd); p.push("PLCLogger\\agent\\logs");
    let _ = Command::new("explorer.exe").arg(p).spawn();
  }
}

fn open_data() {
  if let Some(pd) = std::env::var_os("ProgramData") {
    let mut p = std::path::PathBuf::from(pd); p.push("PLCLogger\\agent");
    let _ = Command::new("explorer.exe").arg(p).spawn();
  }
}

// Elevate to control the Windows service installed by MSI (PLCLoggerSvc)
fn start_service() { let _ = Command::new("powershell.exe").args(["-NoProfile","-Command", "Start-Process sc.exe -Verb runAs -ArgumentList 'start PLCLoggerSvc'"]).spawn(); }
fn stop_service()  { let _ = Command::new("powershell.exe").args(["-NoProfile","-Command", "Start-Process sc.exe -Verb runAs -ArgumentList 'stop PLCLoggerSvc'"]).spawn(); }

fn show_main(app: &AppHandle<Wry>) { if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.set_focus(); } }

#[tauri::command]
fn read_lockfile() -> Option<(u16, String)> {
  if let Some(pd) = std::env::var_os("ProgramData") {
    let mut p = std::path::PathBuf::from(pd);
    p.push("PLCLogger\\agent\\agent.lock.json");
    if p.exists() {
      if let Ok(txt) = std::fs::read_to_string(&p) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) {
          let port = v.get("port").and_then(|x| x.as_u64()).unwrap_or(0) as u16;
          let tok = v.get("token").and_then(|x| x.as_str()).unwrap_or("").to_string();
          if port != 0 { return Some((port, tok)); }
        }
      }
    }
  }
  None
}

fn main() {
  tauri::Builder::default()
    .plugin(tauri_plugin_dialog::init())
    .invoke_handler(tauri::generate_handler![read_lockfile])
    .setup(|app| {
      // Build tray menu
      let open = MenuItemBuilder::with_id("open", "Open PLC Logger").build(app)?;
      let status = MenuItemBuilder::with_id("status", "Status").build(app)?;
      let start = MenuItemBuilder::with_id("start", "Start Agent Service").build(app)?;
      let stop = MenuItemBuilder::with_id("stop", "Stop Agent Service").build(app)?;
      let logs = MenuItemBuilder::with_id("logs", "Open Logs Folder").build(app)?;
      let data = MenuItemBuilder::with_id("data", "Open Data Folder").build(app)?;
      let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
      let menu = MenuBuilder::new(app).items(&[&open,&status,&start,&stop,&logs,&data,&quit]).build()?;
      TrayIconBuilder::new()
        .menu(&menu)
        .on_menu_event(|app, event| {
          match event.id.as_ref() {
            "open" => show_main(app),
            "status" => {
              // Read summary from agent and show in a native dialog
              let ps = r#"
                try {
                  $lf = Join-Path $env:ProgramData "PLCLogger\agent\agent.lock.json";
                  $d = Get-Content $lf | ConvertFrom-Json;
                  $u = "http://127.0.0.1:" + $d.port + "/system/summary";
                  $h = @{}; if ($d.token) { $h["X-Agent-Token"] = $d.token };
                  $r = Invoke-RestMethod -Uri $u -Headers $h -Method GET;
                  "Devices: $($r.devicesConnected)`nDefault DB: $((if($r.defaultDbOk){"OK"}else{"Not OK"}))`nJobs running: $($r.jobsRunning)"
                } catch { "Status unavailable" }
              "#;
              match Command::new("powershell.exe").args(["-NoProfile","-Command", ps]).output() {
                Ok(out) => { let msg = String::from_utf8_lossy(&out.stdout).to_string(); app.dialog().message(msg).show(|_|{}); },
                Err(_) => { app.dialog().message("Status unavailable").show(|_|{}); }
              }
            },
            "start" => start_service(),
            "stop" => stop_service(),
            "logs" => open_logs(),
            "data" => open_data(),
            "quit" => { app.exit(0); },
            _ => {}
          }
        })
        .build(app)?;
      Ok(())
    })
    .on_window_event(|window, event| {
      // Close to tray
      if let tauri::WindowEvent::CloseRequested { api, .. } = event { api.prevent_close(); let _ = window.hide(); }
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri app");
}
