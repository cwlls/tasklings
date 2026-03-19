"""
Entry point for the Tasklings application.

Usage:
    python run.py [--host HOST] [--port PORT] [--debug]
    hypercorn run:app
"""
import argparse
import sys

from app import create_app

VERSION = "0.1.0"

app = create_app()


def _print_banner(host: str, port: int) -> None:
    print("=" * 50)
    print(f"  Tasklings v{VERSION}")
    print(f"  Running at http://{host}:{port}/")
    print("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Tasklings app server.")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    _print_banner(args.host if args.host != "0.0.0.0" else "localhost", args.port)
    app.run(debug=args.debug, host=args.host, port=args.port)
