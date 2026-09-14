"""Record a successful check at most once per 30 days to keep schedules active."""

import base64
import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def api(path, method="GET", payload=None):
    request = Request(
        "https://api.github.com/repos/" + os.environ["GITHUB_REPOSITORY"] + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    branch = os.environ["DEFAULT_BRANCH"]
    now = datetime.now(timezone.utc)
    latest = api("/commits?sha=" + quote(branch, safe="") + "&per_page=1")[0]
    last_commit = datetime.fromisoformat(latest["commit"]["committer"]["date"].replace("Z", "+00:00"))
    if (now - last_commit).days < 30:
        print("Recent repository activity exists; no maintenance commit needed.")
        return

    path = "/contents/.github/last-healthcheck.txt"
    payload = {
        "message": "chore: record successful monthly app health check",
        "branch": branch,
        "content": base64.b64encode((now.date().isoformat() + "\n").encode()).decode(),
    }
    try:
        existing = api(path + "?ref=" + quote(branch, safe=""))
    except HTTPError as error:
        if error.code != 404:
            raise
    else:
        payload["sha"] = existing["sha"]
    api(path, method="PUT", payload=payload)
    print("Recorded successful check date; property data and app code were not changed.")


if __name__ == "__main__":
    main()
