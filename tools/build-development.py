#!/usr/bin/env python3
"""Build private development artifacts and a source-to-wheel receipt from clean HEAD."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEWED = "486be3cef2a29e7163d362bd5cb3a89ef01f421a"
PROVENANCE = "src/twincat_knowledge/domain/provenance.py"
EXPECTED_TOOLS = {
    "tc_browse_topics",
    "tc_get_corpus_status",
    "tc_get_topic",
    "tc_search",
    "tc_find_symbols",
    "tc_get_symbol",
    "tc_find_libraries",
    "tc_get_library",
    "tc_lookup_error",
}


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact(
    path: Path, output: Path, release_tag: str | None = None
) -> dict[str, object]:
    data = path.read_bytes()
    result = {
        "path": path.relative_to(output).as_posix(),
        "sha256": digest(data),
        "size_bytes": len(data),
    }
    if release_tag:
        result["url"] = (
            "https://github.com/Auda29/twincat-knowledge-mcp/releases/download/"
            f"{release_tag}/{path.name}"
        )
    else:
        result["absolute_path"] = str(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--release", action="store_true", help="build stable release assets"
    )
    args = parser.parse_args()
    output = args.out_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output directory must not exist or must be empty")
    if run("git", "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("tracked working tree and index must be clean")
    commit = run("git", "rev-parse", "HEAD")
    tree = run("git", "rev-parse", "HEAD^{tree}")
    if args.release:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", REVIEWED, commit],
            cwd=ROOT,
            check=True,
        )
    delta = run("git", "diff", "--name-only", REVIEWED, commit, "--", "src")
    if set(delta.splitlines()) - {"src/twincat_knowledge/__init__.py"}:
        raise ValueError("functional source differs from reviewed commit")
    epoch = run("git", "show", "-s", "--format=%ct", commit)
    files = run("git", "ls-files", "-z").split("\0")
    files = sorted(p for p in files if p)
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="knowledge-development-") as tmp:
        temp = Path(tmp)
        archive = temp / "head.tar"
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.eol=lf",
                "archive",
                "--format=tar",
                "-o",
                str(archive),
                commit,
            ],
            cwd=ROOT,
            check=True,
        )
        source = temp / "source"
        source.mkdir()
        with tarfile.open(archive) as tar:
            # git archive contains only repository-owned, relative paths.
            tar.extractall(source, filter="data")
        if (source / "tools/build-development.py").read_bytes() != Path(
            __file__
        ).read_bytes():
            raise ValueError("executing builder differs from committed HEAD")
        modes = {}
        for entry in run("git", "ls-files", "--stage", "-z").split("\0"):
            if entry:
                details, name = entry.split("\t", 1)
                modes[name] = details.split()[0]
        inputs = []
        aggregate = hashlib.sha256()
        for name in files:
            data = (source / name).read_bytes()
            committed = subprocess.check_output(
                ["git", "cat-file", "blob", f"{commit}:{name}"], cwd=ROOT
            )
            if data != committed:
                raise ValueError(f"archive input differs from committed bytes: {name}")
            encoded = name.encode("utf-8")
            mode = modes[name].encode("ascii")
            aggregate.update(mode)
            aggregate.update(len(encoded).to_bytes(8, "big"))
            aggregate.update(encoded)
            aggregate.update(len(data).to_bytes(8, "big"))
            aggregate.update(data)
            inputs.append(
                {
                    "path": name,
                    "mode": modes[name],
                    "sha256": digest(data),
                    "size_bytes": len(data),
                }
            )
        env = os.environ.copy()
        env["SOURCE_DATE_EPOCH"] = epoch
        requirements = output / "requirements-runtime.txt"
        exported = run(
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            cwd=source,
            env=env,
        )
        requirements.write_text(exported + "\n", encoding="utf-8")
        build_env = temp / "build-env"
        runtime_env = temp / "runtime-env"
        for venv in (build_env, runtime_env):
            run("uv", "venv", "--python", sys.executable, str(venv), cwd=temp)
        python_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
        build_python = build_env / python_name
        runtime_python = runtime_env / python_name
        run(
            "uv",
            "pip",
            "sync",
            "--require-hashes",
            "--python",
            str(build_python),
            str(source / "tools/build-requirements.txt"),
            cwd=temp,
        )
        run(
            "uv",
            "pip",
            "sync",
            "--require-hashes",
            "--python",
            str(runtime_python),
            str(requirements),
            cwd=temp,
        )
        backend_version = run(
            str(build_python),
            "-c",
            "import importlib.metadata as m; print(m.version('hatchling'))",
            cwd=temp,
        )
        subprocess.run(
            [
                "uv",
                "build",
                "--no-build-isolation",
                "--python",
                str(build_python),
                "--out-dir",
                str(output),
            ],
            cwd=source,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        wheels = list(output.glob("*.whl"))
        sdists = list(output.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ValueError("expected exactly one wheel and one sdist")
        wheel = wheels[0]
        extracted = temp / "wheel"
        with zipfile.ZipFile(wheel) as z:
            names = z.namelist()
            if len(names) != len(set(names)):
                raise ValueError("wheel contains duplicate entries")
            for info in z.infolist():
                path = Path(info.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in info.filename
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("wheel contains an unsafe entry")
            records = [n for n in names if n.endswith(".dist-info/RECORD")]
            metadata = [n for n in names if n.endswith(".dist-info/METADATA")]
            prov = "twincat_knowledge/domain/provenance.py"
            if len(records) != 1 or len(metadata) != 1 or prov not in names:
                raise ValueError(
                    "wheel does not contain unique metadata and provenance"
                )
            provenance_bytes = z.read(prov)
            if provenance_bytes != (source / PROVENANCE).read_bytes():
                raise ValueError("wheel provenance differs from tracked source")
            source_python = {
                p.relative_to(source / "src").as_posix(): p.read_bytes()
                for p in (source / "src/twincat_knowledge").rglob("*.py")
            }
            wheel_python = {n: z.read(n) for n in names if n.endswith(".py")}
            if wheel_python != source_python:
                raise ValueError("wheel Python files differ from tracked source")
            rows = list(csv.reader(io.StringIO(z.read(records[0]).decode("utf-8"))))
            if {row[0] for row in rows} != set(names) or len(rows) != len(names):
                raise ValueError("wheel RECORD does not enumerate wheel files")
            for name, recorded_hash, size in rows:
                if name == records[0]:
                    if recorded_hash or size:
                        raise ValueError("invalid RECORD self-entry")
                    continue
                content = z.read(name)
                encoded_hash = base64.urlsafe_b64encode(
                    hashlib.sha256(content).digest()
                )
                expected = "sha256=" + encoded_hash.rstrip(b"=").decode("ascii")
                if recorded_hash != expected or size != str(len(content)):
                    raise ValueError("wheel RECORD hash or size mismatch")
            z.extractall(extracted)
        # -I ignores cwd/PYTHONPATH; add the wheel ahead of installed dependencies.
        inspect = r"""import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import twincat_knowledge
from twincat_knowledge.mcp_api.topic_server import create_topic_server
from twincat_knowledge.services.topic_queries import TopicQueryService
package = pathlib.Path(twincat_knowledge.__file__).resolve()
if not package.is_relative_to(pathlib.Path(sys.argv[1]).resolve()):
    raise RuntimeError("package was not imported from built wheel")
server = create_topic_server(TopicQueryService(None))
print(json.dumps({"version": twincat_knowledge.__version__, "module": str(package),
                  "tools": [t.model_dump(mode="json", by_alias=True, exclude_none=True)
                            for t in server._topic_tools]}, sort_keys=True))
"""
        data = json.loads(
            run(str(runtime_python), "-I", "-c", inspect, str(extracted), cwd=temp)
        )
        from email.parser import BytesParser

        with zipfile.ZipFile(wheel) as z:
            meta = BytesParser().parsebytes(z.read(metadata[0]))
        if meta["Name"] != "twincat-knowledge" or meta["Version"] != data["version"]:
            raise ValueError("wheel metadata and imported package version disagree")
        source_version = tomllib.loads(
            (source / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        version_pattern = (
            r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
            if args.release
            else r".*\.dev\d+"
        )
        if meta["Version"] != source_version or not re.fullmatch(
            version_pattern, source_version
        ):
            raise ValueError(
                "wheel version must match the committed "
                + ("stable" if args.release else "development")
                + " version"
            )
        release_tag = f"v{source_version}" if args.release else None
        if {t["name"] for t in data["tools"]} != EXPECTED_TOOLS or len(
            data["tools"]
        ) != 9:
            raise ValueError("built wheel does not expose the expected nine tools")
        tools_path = output / "nine-tools.json"
        tools_path.write_text(
            json.dumps(data["tools"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        install_requirement = (
            f"twincat-knowledge=={meta['Version']} "
            f"--hash=sha256:{digest(wheel.read_bytes())}"
        )
        candidate_requirements = output / "requirements-candidate.txt"
        candidate_requirements.write_text(
            exported + "\n" + install_requirement + "\n", encoding="utf-8"
        )
        receipt = {
            "development_only": not args.release,
            "real_extraction_acceptance": "open",
            "identity": "release candidate"
            if args.release
            else "private development artifact; not a shipping release",
            "source": {
                "commit": commit,
                "tree": tree,
                "reviewed_functional_commit": REVIEWED,
                "source_date_epoch": int(epoch),
                "archive_git_config": {"core.autocrlf": False, "core.eol": "lf"},
                "tracked_inputs": inputs,
                "aggregate_sha256": aggregate.hexdigest(),
                "aggregate_encoding": (
                    "sorted UTF-8 paths: six ASCII mode bytes, "
                    "8-byte big-endian path length, path bytes, "
                    "8-byte big-endian content length, raw content bytes"
                ),
                "uv_lock_sha256": digest((source / "uv.lock").read_bytes()),
            },
            "tooling": {
                "python": sys.version,
                "uv": run("uv", "--version"),
                "hatchling": backend_version,
                "build_requirements_sha256": digest(
                    (source / "tools/build-requirements.txt").read_bytes()
                ),
            },
            "wheel": {
                **artifact(wheel, output, release_tag),
                "name": meta["Name"],
                "version": meta["Version"],
                "install_requirement": install_requirement,
                "provenance_path": prov,
                "provenance_sha256": digest(provenance_bytes),
                "record_path": records[0],
            },
            "sdist": artifact(sdists[0], output, release_tag),
            "runtime_requirements": artifact(requirements, output, release_tag),
            "candidate_requirements": artifact(
                candidate_requirements, output, release_tag
            ),
            "tool_schema": {
                **artifact(tools_path, output, release_tag),
                "names": sorted(EXPECTED_TOOLS),
            },
        }
        if args.release:
            lock = output / "uv.lock"
            build_requirements = output / "build-requirements.txt"
            lock.write_bytes((source / "uv.lock").read_bytes())
            build_requirements.write_bytes(
                (source / "tools/build-requirements.txt").read_bytes()
            )
            receipt["release_version"] = source_version
            receipt["release_tag"] = release_tag
            receipt["uv_lock"] = artifact(lock, output, release_tag)
            receipt["build_requirements"] = artifact(
                build_requirements, output, release_tag
            )
            asset_names = [
                wheel.name,
                sdists[0].name,
                requirements.name,
                candidate_requirements.name,
                tools_path.name,
                lock.name,
                build_requirements.name,
                "release-receipt.json",
                "SHA256SUMS.txt",
            ]
            receipt["asset_urls"] = {
                name: f"https://github.com/Auda29/twincat-knowledge-mcp/releases/download/{release_tag}/{name}"
                for name in sorted(asset_names)
            }
        receipt_path = output / (
            "release-receipt.json" if args.release else "development-receipt.json"
        )
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.release:
            assets = [
                wheel,
                sdists[0],
                requirements,
                candidate_requirements,
                tools_path,
                lock,
                build_requirements,
                receipt_path,
            ]
            (output / "SHA256SUMS.txt").write_text(
                "".join(
                    f"{digest(path.read_bytes())}  {path.name}\n"
                    for path in sorted(assets)
                ),
                encoding="utf-8",
            )
    print(f"{'Release' if args.release else 'Development'} receipt written to {output}")


if __name__ == "__main__":
    main()
