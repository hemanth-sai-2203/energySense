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

from scripts.forecast_service import generate_forecast

def query_db(sql, params=(), as_dict=True, limit=None):
    """Executes a query safely with guaranteed connection cleanup."""
    conn = sqlite3.connect(DB_PATH)
    try:
        if as_dict:
            conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        if limit is not None:
            rows = cur.fetchmany(limit)
        else:
            rows = cur.fetchall()
        if as_dict:
            return [dict(r) for r in rows]
        columns = [desc[0] for desc in cur.description] if cur.description else []
        return columns, rows
    finally:
        conn.close()

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
        elif path == "/api/forecast":
            self.handle_forecast(query)
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

    def _send_payload(self, body, content_type="application/json; charset=utf-8", code=200, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, code=200):
        body = json.dumps(data).encode("utf-8")
        self._send_payload(body, code=code)

    def send_error_json(self, msg, code=400, extra=None):
        payload = {"error": msg}
        if extra and isinstance(extra, dict):
            payload.update(extra)
        body = json.dumps(payload).encode("utf-8")
        self._send_payload(body, code=code)

    def handle_forecast(self, query):
        target = query.get("target", ["energy_met_mu"])[0]
        origin = query.get("origin", [None])[0]
        horizon = query.get("horizon", ["7"])[0]
        
        try:
            status_code, response_data = generate_forecast(
                target=target,
                origin_str=origin,
                horizon=horizon,
                db_path=DB_PATH
            )
            if status_code == 200:
                self.send_json(response_data)
            else:
                self.send_error_json(
                    response_data.get("message", "Forecast request error"),
                    code=status_code,
                    extra=response_data
                )
        except Exception as e:
            self.send_error_json(f"Forecast engine internal error: {str(e)}", code=500)

    def send_json_file(self, filepath):
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                content = f.read()
            self._send_payload(content)
        else:
            self.send_error_json("File not found", 404)

    def handle_daily(self, query):
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
        rows = query_db(sql, params)
        self.send_json(rows)

    def handle_generation(self):
        rows = query_db("SELECT * FROM monthly_generation ORDER BY date ASC")
        self.send_json(rows)

    def handle_states(self, query):
        year = query.get("year", [None])[0]
        if year and year != "all":
            rows = query_db("SELECT * FROM state_annual_summary WHERE year = ? ORDER BY total_energy_mu DESC", (int(year),))
        else:
            rows = query_db("SELECT * FROM state_annual_summary ORDER BY state ASC, year ASC")
        self.send_json(rows)

    def handle_state_daily(self, query):
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
        
        rows = query_db(sql, params)
        self.send_json(rows)

    def handle_capacity(self):
        try:
            rows = query_db("SELECT * FROM state_capacity_latest ORDER BY total_mw DESC")
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
            columns, rows = query_db(clean_q, as_dict=False, limit=200)
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
                self._send_payload(
                    content,
                    content_type="application/octet-stream",
                    extra_headers={"Content-Disposition": f'attachment; filename="{fname}"'}
                )
                return
        self.send_error(404, "Downloadable file not found")

def run(port=PORT):
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    for p in [port, port + 1, port + 80, 5000, 8080]:
        try:
            server = socketserver.ThreadingTCPServer(("", p), EnergySenseHandler)
            print(f"EnergySense Server running at http://127.0.0.1:{p}", flush=True)
            server.serve_forever()
            break
        except OSError as e:
            print(f"Port {p} error ({e}), trying next...", flush=True)

if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run(p)

