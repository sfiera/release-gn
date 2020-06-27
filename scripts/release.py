#!/usr/bin/env python3

import base64
import os
import re
import requests
import shutil
import subprocess
import tarfile

REPO = os.getenv("PLUGIN_REPO")
TOKEN = os.getenv("PLUGIN_TOKEN")

DEPS_URL = "https://chromium.googlesource.com/chromium/src/+/master/DEPS?format=TEXT"
GN_RE = re.compile(r"gn_version.*git_revision:([0-9A-Za-z]+)")
DESCRIBE_RE = re.compile(
    r"""
    subprocess.check_output\(\s*
        \['git',\s*'describe',\s*'HEAD',\s*'--match',\s*ROOT_TAG\],\s*
        shell=host.is_windows\(\),\s*
        cwd=REPO_ROOT\s*
    \)
    """, re.VERBOSE | re.DOTALL)


def main():
    name = create_release()


def create_release():
    "Creates a GitHub release for $PLUGIN_REPO"
    os.chdir("gn")
    #ref = deps_ref()
    ref = "7d7e8deea36d126397bda2cf924682504271f0e1"
    print("Chromium DEPS uses gn@%s" % ref)
    subprocess.check_call(["git", "checkout", "master"])
    subprocess.check_call(["git", "reset", "--hard", ref])

    tag = existing_tag()
    if tag is not None:
        print("Already tagged as %s" % tag)
        return tag

    name, described = describe()
    os.chdir("..")
    distfile = dist(name, described)
    print("Generated %s" % distfile)

    url = release(name, ref, distfile)
    print("Created %s" % url)
    return name


def deps_ref():
    "Returns the git revision for gn at HEAD in Chromium’s DEPS."
    resp = requests.get(DEPS_URL)
    resp.raise_for_status()
    content = base64.b64decode(resp.content).decode("utf-8")
    return GN_RE.search(content).group(1)


def existing_tag():
    "Returns the existing tag referencing HEAD, if any"
    try:
        return subprocess.check_output(["git", "describe", "--tags", "--exact"],
                                       stderr=subprocess.DEVNULL).strip().decode("utf-8")
    except subprocess.CalledProcessError:
        return None


def describe():
    "Tags HEAD with an appropriate name and returns the name"
    described = subprocess.check_output(["git", "describe",
                                         "--match=initial-commit"]).strip().decode("utf-8")
    name = "0.0." + described.split("-")[2]
    return name, described


def dist(name, described):
    "Creates a distfile for HEAD and returns path"
    url = "file://%s" % os.getcwd()
    tar_gz = "gn-%s.tar.gz" % name

    if os.path.isdir("gn/out"):
        shutil.rmtree("gn/out")
    patch("gn/build/gen.py", described)

    with tarfile.open(tar_gz, "w:gz") as tar:
        for real_path, archive_path in walk("gn-%s" % name, "gn"):
            tar.add(real_path, arcname=archive_path)
    return tar_gz


def patch(gen, described):
    "Inline result of git describe so that .git is not needed in distfile"
    with open("gn/build/gen.py") as f:
        data = f.read()
    patched = DESCRIBE_RE.sub(repr(described.encode("utf-8")), data)
    assert data != patched
    with open("gn/build/gen.py", "w") as f:
        f.write(patched)


def walk(archive_root, walk_root):
    "Walk walk_root, yielding (in, out) path pairs"
    for root, dirs, files in os.walk(walk_root):
        root = root[1 + len(walk_root):]
        files[:] = [f for f in files if not f.startswith(".git")]
        dirs[:] = [d for d in dirs if not d.startswith(".git")]
        for f in files:
            real_path = os.path.join(walk_root, root, f)
            archive_path = os.path.join(archive_root, root, f)
            yield real_path, archive_path


def release(name, ref, distfile):
    "POST /repos/:owner/:repo/releases"
    release_url = "https://api.github.com/repos/%s/releases" % REPO
    resp = requests.post(release_url,
                         headers={"Authorization": "token %s" % TOKEN},
                         json={
                             "tag_name": name,
                             "target_commitish": ref,
                             "name": name,
                             "draft": True,
                         })
    resp.raise_for_status()
    release_url = resp.json()["url"]
    upload_url = resp.json()["upload_url"].split("{")[0]

    with open(distfile, "rb") as f:
        resp = requests.post("%s?name=%s" % (upload_url, distfile),
                             headers={
                                 "Authorization": "token %s" % TOKEN,
                                 "Content-Type": "application/x-gzip"
                             },
                             data=f)
    resp.raise_for_status()

    resp = requests.patch(release_url,
                          headers={"Authorization": "token %s" % TOKEN},
                          json={"draft": False})
    resp.raise_for_status()
    html_url = resp.json()["html_url"]
    return html_url


if __name__ == "__main__":
    main()
