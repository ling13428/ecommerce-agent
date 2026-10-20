import httpx

BASE_URL = "http://127.0.0.1:8000"


def test_product_tool():
    response = httpx.get(f"{BASE_URL}/api/tools/products/P1001")
    response.raise_for_status()
    data = response.json()

    assert data["found"] is True
    assert data["product"]["name"] == "无线蓝牙耳机"
    print("工具直连测试通过：", data["product"]["name"])


def test_chat_stream():
    with httpx.stream(
        "POST",
        f"{BASE_URL}/api/chat/stream",
        json={"message": "P1001 多少钱，还有货吗？"},
    ) as response:
        response.raise_for_status()
        events = []

        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(line[6:])

        assert any('"type": "tool_call"' in event for event in events)
        assert any('"type": "done"' in event for event in events)
        print("流式工具调用测试通过，共收到", len(events), "个事件")


if __name__ == "__main__":
    test_product_tool()
    test_chat_stream()
