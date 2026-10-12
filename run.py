"""Start the tool: runs a small web server on this computer only and opens it in the browser."""
import socket
import threading
import webbrowser

from hosts.standalone import create_app


def free_port(start: int = 5050) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free port found")


if __name__ == "__main__":
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"NMC Tools running at {url}  (close this window to stop)")
    create_app().run(host="127.0.0.1", port=port, debug=False, use_reloader=False)