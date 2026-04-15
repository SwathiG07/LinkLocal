import asyncio
from linklocal.config import set_app_dir
set_app_dir("dummy")
from linklocal.peer import Peer

async def main():
    peer = Peer("Alice")
    await peer.start()
    try:
        await peer.send("hello test", "some_id")
        print("Success")
    except Exception as e:
        print("Exception:", type(e).__name__, str(e))
        import traceback
        traceback.print_exc()
    await peer.stop()

asyncio.run(main())
