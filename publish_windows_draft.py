"""Upload verified Windows files to a draft release using the Actions job token."""
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request


def request(method, url, data=None, content_type="application/json"):
    if urllib.parse.urlparse(url).hostname not in ("api.github.com", "uploads.github.com"):
        raise ValueError("Unexpected GitHub API host")
    token = os.environ["QINGPIAN_RELEASE_TOKEN"]
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if isinstance(data, dict) else data
    call = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "Qingpian-release-builder",
        "Content-Type": content_type,
    })
    with urllib.request.urlopen(call, timeout=120) as response:
        return json.load(response)


def ensure_draft(repository, version, source_commit, notes):
    api = f"https://api.github.com/repos/{repository}"
    tag = f"v{version}"
    releases = request("GET", f"{api}/releases?per_page=100")
    matching = [release for release in releases if release["tag_name"] == tag]
    if len(matching)>1:
        raise RuntimeError("Multiple releases have this tag; review them manually.")
    if matching and not matching[0]["draft"]:
        print(f"{tag} is already published; its assets and notes are preserved.")
        return None
    payload = dict(tag_name=tag, target_commitish=source_commit,
                   name=f"晴片 {tag} · Windows 64 位与 Mac 版", body=notes, draft=True)
    if matching:
        release = matching[0]
        # Do not change a draft whose existing asset belongs to another source commit.
        if release["target_commitish"] != source_commit:
            raise RuntimeError("An existing draft uses another source commit; review it before replacing assets.")
        return release
    return request("POST", f"{api}/releases", payload)


def main():
    root = Path(__file__).resolve().parent
    version = (root/"VERSION").read_text(encoding="utf-8").strip()
    commit = os.environ["GITHUB_SHA"]
    directory = root/"dist/windows-x64"
    verification = json.loads((directory/"windows-verification.json").read_text(encoding="utf-8"))
    assert verification["source_commit"] == commit
    assert verification["native_gui_smoke_test"]["status"] == "passed"
    archive = directory/f"Qingpian-{version}-Windows-x64.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == verification["sha256"]
    release = ensure_draft(os.environ["GITHUB_REPOSITORY"], version, commit,
                           (root/"RELEASE_NOTES.md").read_text(encoding="utf-8"))
    if release is None:
        return
    files = [archive, directory/f"Qingpian-{version}-Windows-x64-SHA256SUMS.txt",
             directory/"windows-verification.json", directory/"windows-packaged-gui.png"]
    existing = {asset["name"]:asset for asset in release["assets"]}
    for path in files:
        data = path.read_bytes()
        digest = "sha256:"+hashlib.sha256(data).hexdigest()
        if path.name in existing:
            if existing[path.name].get("digest") != digest:
                raise RuntimeError(f"Draft already contains a different {path.name}; review it manually.")
            continue
        upload_url = release["upload_url"].split("{")[0]+"?name="+urllib.parse.quote(path.name)
        asset = request("POST", upload_url, data, "application/octet-stream")
        assert asset["state"] == "uploaded" and asset["size"] == len(data)
        if asset.get("digest"):
            assert asset["digest"] == digest
        print(f"Uploaded draft asset: {path.name} ({len(data)} bytes)")
    print(f"Draft release ready: {release['html_url']}")


if __name__ == "__main__":
    main()
