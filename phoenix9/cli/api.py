"""Commands for `phoenix api`: start the dashboard API server."""
import signal

from phoenix9.ops.common import OpsError

HOSTS = ("127.0.0.1", "localhost")


def add(sub, common) -> None:
    """Register the api group."""
    group = sub.add_parser("api", help="the dashboard API").add_subparsers(
        dest="action", metavar="ACTION", required=True)
    p = group.add_parser("serve", parents=[common], help="run the dashboard API until stopped")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost only")
    p.set_defaults(func=serve)


def serve(args) -> int:
    """Serve the API on this machine only; stop cleanly on Ctrl-C or SIGTERM."""
    import threading
    from phoenix9.api import server
    if args.host not in HOSTS:
        raise OpsError("The API only listens on this machine (127.0.0.1); other addresses are refused.")
    httpd = server.make_server(args.port, host=args.host)
    stop = httpd.stopping
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    print(f"Phoenix API listening on http://127.0.0.1:{httpd.server_address[1]}/", flush=True)
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()
    return 0
