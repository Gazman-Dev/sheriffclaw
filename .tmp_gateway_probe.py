import asyncio
import json
from shared.proc_rpc import ProcClient

async def main():
    cli = ProcClient('sheriff-gateway')
    stream, final = await cli.request(
        'gateway.handle_user_message',
        {'channel': 'cli', 'principal_external_id': 'ssh-cli', 'text': 'hello from gateway probe', 'model_ref': None},
        stream_events=True,
    )
    async for frame in stream:
        print(json.dumps(frame, ensure_ascii=False))
    print('FINAL', json.dumps(await final, ensure_ascii=False))
    await cli.close()

asyncio.run(main())
