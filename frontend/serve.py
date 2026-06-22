"""Frontend static server — no-cache (ბრაუზერი ყოველთვის ახ ალ ფაილს იღებს).
გაშვება: python serve.py   (პორტი 5500)
"""
import http.server
import socketserver

PORT = 5500


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("127.0.0.1", PORT), NoCacheHandler) as httpd:
        print(f"Frontend (no-cache) -> http://localhost:{PORT}")
        httpd.serve_forever()
