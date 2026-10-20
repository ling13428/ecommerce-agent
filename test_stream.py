import httpx

url = "http://127.0.0.1:8000/api/chat/stream"

with httpx.stream("POST", url, json={"message": "你好，我想查订单"}) as resp:
    print("status:", resp.status_code)
    for line in resp.iter_lines():
        if line:
            print(line)