import http.server
import socketserver
import os
import sys
import json
import sqlite3
import urllib.parse

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DATA_DIR = os.path.join(BASE_DIR, "data", "clean")
DB_PATH = os.path.join(DATA_DIR, "energysense.db")

class EnergySenseHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # API routes
        if path == "/api/analytics":
            self.send_json_file(os.path.join(DATA_DIR, "insights_analytics.json"))
        elif path == "/api/audit":
            self.send_json_file(os.path.join(DATA_DIR, "data_audit_results.json"))
        elif path == "/api/daily":
            self.handle_daily(query)
        elif path == "/api/generation":
            self.handle_generation()
        elif path == "/api/states":
            self.handle_states(query)
        elif path == "/api/state_daily":
            self.handle_state_daily(query)
        elif path == "/api/capacity":
            self.handle_capacity()
        elif path == "/api/download":
            self.handle_download(query)
        else:
            # Fallback to static files
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/sql":
            content_length = int(self.headers.get('Content-Length', 0))
            post_body = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_body)
                query_sql = data.get("query", "").strip()
                self.handle_sql(query_sql)
            except Exception as e:
                self.send_error_json(str(e))
        else:
            self.send_error(404, "Endpoint not found")

    def send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, msg, code=400):
        body = json.dumps({"error": msg}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_json_file(self, filepath):
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error_json("File not found", 404)

    def handle_daily(self, query):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        year = query.get("year", [None])[0]
        start_date = query.get("start", [None])[0]
        end_date = query.get("end", [None])[0]
        
        sql = "SELECT * FROM daily_india_demand WHERE 1=1"
        params = []
        if year and year != "all":
            sql += " AND year = ?"
            params.append(int(year))
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
            
        sql += " ORDER BY date ASC"
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.send_json(rows)

    def handle_generation(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM monthly_generation ORDER BY date ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.send_json(rows)

    def handle_states(self, query):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        year = query.get("year", [None])[0]
        
        if year and year != "all":
            cur.execute("SELECT * FROM state_annual_summary WHERE year = ? ORDER BY total_energy_mu DESC", (int(year),))
        else:
            cur.execute("SELECT * FROM state_annual_summary ORDER BY state ASC, year ASC")
            
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.send_json(rows)

    def handle_state_daily(self, query):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        state = query.get("state", [None])[0]
        year = query.get("year", [None])[0]
        
        sql = "SELECT * FROM state_daily_demand WHERE 1=1"
        params = []
        if state:
            sql += " AND state = ?"
            params.append(state)
        if year and year != "all":
            sql += " AND year = ?"
            params.append(int(year))
        sql += " ORDER BY date ASC"
        
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.send_json(rows)

    def handle_capacity(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM state_capacity_latest ORDER BY total_mw DESC")
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            if rows:
                self.send_json(rows)
                return
        except Exception:
            pass
        self.send_json_file(os.path.join(DATA_DIR, "state_capacity_latest.json"))

    def handle_sql(self, query_sql):
        # Security check: only allow SELECT statements
        clean_q = query_sql.strip()
        if not clean_q.upper().startswith("SELECT"):
            self.send_error_json("Only SELECT queries are permitted in this sandbox.")
            return

        for forbidden in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "ATTACH", "DETACH", "PRAGMA"]:
            if f" {forbidden} " in f" {clean_q.upper()} ":
                self.send_error_json(f"Disallowed SQL keyword detected: {forbidden}")
                return

        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(clean_q)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = cur.fetchmany(200) # limit to 200 rows for response size
            conn.close()
            self.send_json({"columns": columns, "rows": rows, "count": len(rows)})
        except Exception as e:
            self.send_error_json(f"SQL Execution Error: {str(e)}")

    def handle_download(self, query):
        target = query.get("file", [""])[0]
        safe_files = {
            "daily_demand": "daily_demand_india.csv",
            "monthly_generation": "monthly_generation_india.csv",
            "state_annual": "state_annual_summary.csv",
            "state_daily": "state_daily_demand.csv",
            "insights": "insights_analytics.json",
            "audit": "data_audit_results.json"
        }
        if target in safe_files:
            fname = safe_files[target]
            fpath = os.path.join(DATA_DIR, fname)
            if os.path.exists(fpath):
                with open(fpath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
        self.send_error(404, "Downloadable file not found")

def run(port=PORT):
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    for p in [port, port + 1, port + 80, 5000, 8080]:
        try:
            server = socketserver.ThreadingTCPServer(("127.0.0.1", p), EnergySenseHandler)
            print(f"EnergySense Server running at http://127.0.0.1:{p}", flush=True)
            server.serve_forever()
            break
        except OSError as e:
            print(f"Port {p} error ({e}), trying next...", flush=True)

if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run(p)

