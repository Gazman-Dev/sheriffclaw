from __future__ import annotations

from services.sheriff_updater.service import SheriffUpdaterService
from shared.protocol import VERSION
from shared.service_base import NDJSONService
from shared.service_boot import run_service


def main() -> None:
    svc = SheriffUpdaterService()
    app = NDJSONService(name="gw.updater", island="gw", kind="service", version=VERSION, ops=svc.ops())
    run_service(app)


if __name__ == "__main__":
    main()
