import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0" if os.environ.get("RADAR_MODE") == "server" else "127.0.0.1",
        port=int(os.environ.get("RADAR_PORT", "8877")),
        access_log=False,
        forwarded_allow_ips=os.environ.get("RADAR_TRUSTED_PROXIES", "127.0.0.1"),
    )
