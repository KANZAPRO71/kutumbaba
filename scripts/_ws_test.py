import asyncio, json, ssl
try:
    import websockets
except ImportError:
    print("no websockets module")
    raise SystemExit(0)

async def test(url):
    try:
        kw = {"ssl": ssl._create_unverified_context()} if url.startswith("wss") else {}
        async with websockets.connect(url, open_timeout=5, **kw) as ws:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            print(url, "OK", msg.get("type"), msg.get("state"))
    except Exception as e:
        print(url, "FAIL", e)

async def main():
    for url in ["ws://127.0.0.1:8765/api/live/ws", "wss://192.168.110.132:8766/api/live/ws"]:
        await test(url)

asyncio.run(main())
