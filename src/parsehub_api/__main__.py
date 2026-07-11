from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("parsehub_api.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
