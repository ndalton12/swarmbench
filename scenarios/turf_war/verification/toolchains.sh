#!/bin/sh
# Run only inside the built scenario image as an ordinary user with networking off.
set -eu
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
mkdir -p rust/src rust/.cargo
cat > rust/.cargo/config.toml <<'EOF'
[source.crates-io]
replace-with = "debian"
[source.debian]
directory = "/usr/share/cargo/registry"
[net]
offline = true
EOF
cat > rust/Cargo.toml <<'EOF'
[package]
name = "build-check"
version = "0.1.0"
edition = "2021"
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
tiny_http = "0.12"
EOF
cat > rust/src/main.rs <<'EOF'
#[derive(serde::Serialize)]
struct Ready { ready: bool }
fn main() {
    let _server = tiny_http::Server::http("127.0.0.1:0").unwrap();
    assert_eq!(serde_json::to_string(&Ready { ready: true }).unwrap(), "{\"ready\":true}");
    println!("Rust offline HTTP/JSON build: PASS");
}
EOF
(cd rust && cargo run --offline --quiet)
cat > main.go <<'EOF'
package main
import ("encoding/json"; "fmt"; "net"; "net/http")
func main() {
    listener, err := net.Listen("tcp", "127.0.0.1:0"); if err != nil { panic(err) }; defer listener.Close()
    _ = http.NewServeMux()
    _, err = json.Marshal(map[string]bool{"ready":true}); if err != nil { panic(err) }
    fmt.Println("Go offline HTTP/JSON build: PASS")
}
EOF
go run main.go
cat > main.ts <<'EOF'
import * as http from 'http';
const server = http.createServer((_req, res) => res.end(JSON.stringify({ready: true})));
server.listen(0, '127.0.0.1', () => {
    server.close();
    console.log('TypeScript offline HTTP/JSON build: PASS');
});
EOF
tsc --module commonjs --target es2020 --typeRoots /usr/share/nodejs/@types --types node --skipLibCheck main.ts
node main.js
