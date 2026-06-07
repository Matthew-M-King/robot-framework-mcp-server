from uvicorn import run


def main() -> None:
    run("robot_mcp_server.http_server:app", host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
