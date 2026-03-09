import asyncio
import json
from shared.proc_rpc import ProcClient

async def main():
    cli = ProcClient('sheriff-chat-proxy')
    stream, final = await cli.request(
        'chatproxy.send',
        {'channel': 'cli', 'principal_external_id': 'ssh-debug', 'text': 'hello from proxy test', 'model_ref': None},
        stream_events=True,
    )
    async for frame in stream:
        print(json.dumps(frame, ensure_ascii=False))
    print('FINAL', json.dumps(await final, ensure_ascii=False))
    await cli.close()

asyncio.run(main())
