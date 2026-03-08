from __future__ import annotations

from services.sheriff_secrets.service import SheriffSecretsService
from shared.protocol import VERSION
from shared.service_base import NDJSONService
from shared.service_boot import run_service


def main() -> None:
    svc = SheriffSecretsService()
    app = NDJSONService(name="gw.secrets", island="gw", kind="service", version=VERSION, ops=svc.ops())
    run_service(app)


if __name__ == "__main__":
    main()
