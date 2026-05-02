#!/usr/bin/env python3
"""
lit-critic — API Server

Starts the local REST API server consumed by the VS Code extension.

Usage:
    python lit-critic-server.py [--port 8000] [--host 127.0.0.1]
"""

import argparse
import logging

import uvicorn


def main():
    parser = argparse.ArgumentParser(
        description="lit-critic — API Server"
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port to serve on (default: 8000)"
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--reload", action="store_true",
        help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # Keep noisy third-party loggers quiet
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    print(f"\n  lit-critic — API Server", flush=True)
    print(f"  Listening on http://{args.host}:{args.port}\n", flush=True)

    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=False,
    )


if __name__ == "__main__":
    main()
