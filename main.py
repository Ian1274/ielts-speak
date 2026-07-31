import http.server
import os
import socketserver

PORT = int(os.getenv("PORT", "8127"))
DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)


def main():
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"WordPlayer serving on http://0.0.0.0:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
