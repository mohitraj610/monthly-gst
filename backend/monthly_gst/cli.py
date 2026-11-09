import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run the local Monthly GST filing preparation workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if args.data_dir:
        os.environ["MONTHLY_GST_DATA"] = str(args.data_dir.resolve())
    import uvicorn
    from .api import create_app
    print(f"Monthly GST: http://127.0.0.1:{args.port} — local filing preparation", flush=True)
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
