from yahoo_shopping_mcp import server


class _FakeMcp:
    def __init__(self) -> None:
        self.transports: list[str] = []

    def run(self, *, transport: str) -> None:
        self.transports.append(transport)


def test_http_entrypoint_keeps_streamable_http(monkeypatch) -> None:
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(server, "create_mcp_server", lambda: fake_mcp)

    server.main()

    assert fake_mcp.transports == ["streamable-http"]


def test_stdio_entrypoint_uses_stdio(monkeypatch) -> None:
    fake_mcp = _FakeMcp()
    monkeypatch.setattr(server, "create_mcp_server", lambda: fake_mcp)

    server.main_stdio()

    assert fake_mcp.transports == ["stdio"]
