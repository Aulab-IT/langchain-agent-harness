"""Step 19: mappa ed eventuale avvio del control plane completo."""

import argparse

import uvicorn

from agent_harness.server import app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help="Avvia API su 127.0.0.1:8000")
    args = parser.parse_args()
    if args.serve:
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
        return

    routes = sorted(
        (method, route.path)
        for route in app.routes
        for method in sorted(getattr(route, "methods", set()))
        if route.path.startswith("/api/")
    )
    groups: dict[str, int] = {}
    for _method, path in routes:
        group = path.split("/")[2]
        groups[group] = groups.get(group, 0) + 1
    print("Control plane completo:", len(routes), "operazioni API")
    print("Gruppi:", ", ".join(f"{name}={count}" for name, count in sorted(groups.items())))
    print("Usa --serve, poi avvia il client React con: cd client && npm run dev")


if __name__ == "__main__":
    main()
