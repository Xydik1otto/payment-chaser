"""Console entry point: `payment-chaser` starts the web UI on 127.0.0.1:8000."""
import os

import uvicorn


def main() -> None:
    host = os.environ.get("CHASER_HOST", "127.0.0.1")
    port = int(os.environ.get("CHASER_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
