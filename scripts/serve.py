"""
Launch the Tasklings development server.

Usage:
    uv run serve
    uv run serve --host 0.0.0.0 --port 8080 --debug
"""
import argparse

VERSION = "0.1.0"


def _print_banner(host: str, port: int, debug: bool) -> None:
    display_host = "localhost" if host == "0.0.0.0" else host
    print("=" * 50)
    print(f"  Tasklings v{VERSION}")
    print(f"  http://{display_host}:{port}/")
    if debug:
        print("  mode: debug")
    print("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Tasklings server.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug/reload mode")
    args = parser.parse_args()

    from app import create_app
    app = create_app()

    _print_banner(args.host, args.port, args.debug)
    app.run(debug=args.debug, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
