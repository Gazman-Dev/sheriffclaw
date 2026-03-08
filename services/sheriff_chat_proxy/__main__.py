from __future__ import annotations

from services.sheriff_chat_proxy.service import SheriffChatProxyService
from shared.protocol import VERSION
from shared.service_base import NDJSONService
from shared.service_boot import run_service


def main() -> None:
    svc = SheriffChatProxyService()
    app = NDJSONService(name="gw.chat_proxy", island="gw", kind="service", version=VERSION, ops=svc.ops())
    run_service(app)


if __name__ == "__main__":
    main()
