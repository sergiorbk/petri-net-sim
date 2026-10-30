"""Run a finite-model workflow through a real main:app process and HTTP MCP.

Build frontend/dist first. Requires Docker and the backend's installed dependencies.
The temporary database, API key and application process are isolated and cleaned up.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BACKEND = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def document_shape(xml: str) -> dict:
    root = ET.fromstring(xml)
    places = root.findall(".//{*}place")
    transitions = root.findall(".//{*}transition")
    nodes = {element.attrib["id"]: element.findtext("{*}name/{*}text") for element in places + transitions}
    return {
        "places": sorted((nodes[element.attrib["id"]], int(element.findtext("{*}initialMarking/{*}text", "0"))) for element in places),
        "transitions": sorted(nodes[element.attrib["id"]] for element in transitions),
        "arcs": sorted((nodes[element.attrib["source"]], nodes[element.attrib["target"]],
                        int(element.findtext("{*}inscription/{*}text", "1")))
                       for element in root.findall(".//{*}arc")),
    }


def markings(result: str) -> dict[str, int]:
    return {name: int(value) for name, value in re.findall(r"^  ([^:\n]+): marking=(\d+),", result, re.MULTILINE)}


async def workflow(base_url: str, output: Path) -> dict:
    transcript: list[dict] = []
    with httpx.Client(base_url=base_url, timeout=10) as http:
        response = http.post("/api/v1/auth/api-keys", json={"name": "isolated MCP workflow"})
        response.raise_for_status()
        token = response.json()["data"]["key"]
        home = http.get("/")
        home.raise_for_status()
        assert "<html" in home.text.lower(), "Built frontend was not served by main:app"

    try:
        async with streamablehttp_client(base_url + "/mcp", headers={"Authorization": "Bearer " + token}) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                available = {tool.name for tool in (await client.list_tools()).tools}
                required = {"create_network", "add_place", "add_transition", "add_arc", "validate_net",
                            "run_simulation", "get_simulation_results", "export_pnml", "import_pnml"}
                assert required <= available, f"Missing tools: {required - available}"
                resources = []
                for resource in (await client.list_resources()).resources:
                    uri = str(resource.uri)
                    if uri.startswith("petri://skills/"):
                        content = await client.read_resource(uri)
                        text = "\n".join(item.text for item in content.contents)
                        resources.append({"uri": uri, "bytes": len(text.encode()),
                                          "sha256": hashlib.sha256(text.encode()).hexdigest()})
                assert len(resources) == 5, "Expected four shared guides and the application adapter"
                prompt = await client.get_prompt("build_queueing_system", {"description": "Finite six-token service"})
                assert prompt.messages, "Shared task prompt was empty"

                async def call(tool_name: str, **arguments) -> str:
                    print("MCP_TOOL " + tool_name, flush=True)
                    result = await client.call_tool(tool_name, arguments)
                    text = "\n".join(item.text for item in result.content if item.type == "text")
                    transcript.append({"tool": tool_name, "arguments": arguments, "result": text, "isError": result.isError})
                    if result.isError or text.startswith(("Error:", "ERROR:")):
                        raise AssertionError(f"{tool_name}: {text}")
                    return text

                await call("create_network", name="FiniteMcpWorkflow")
                source = await call("add_place", name="Source", tokens=6, x=100, y=100)
                completed = await call("add_place", name="Completed", tokens=0, tag="throughput", x=340, y=100)
                service = await call("add_transition", name="Service", distribution="det", mean_delay=1, time_unit="s", x=220, y=100)
                source_id = re.search(r"id=([^,\s)]+)", source).group(1)
                completed_id = re.search(r"id=([^,\s)]+)", completed).group(1)
                service_id = re.search(r"id=([^,\s)]+)", service).group(1)
                await call("add_arc", source_id=source_id, target_id=service_id)
                await call("add_arc", source_id=service_id, target_id=completed_id)
                await call("validate_net")

                first_result = await call("run_simulation", simulation_time=10, time_unit="s")
                first_markings = markings(first_result)
                assert first_markings == {"Source": 0, "Completed": 6}, first_result
                assert "Service: buffer=0," in first_result, first_result
                assert "Completed: total_consumed=6" in first_result, first_result
                stored_result = await call("get_simulation_results")
                assert markings(stored_result) == first_markings

                saved_xml = await call("export_pnml")
                shape = document_shape(saved_xml)
                assert shape == {"places": [("Completed", 0), ("Source", 6)],
                                 "transitions": ["Service"],
                                 "arcs": [("Service", "Completed", 1), ("Source", "Service", 1)]}, shape
                model_file = output / "finite-workflow.pnml"
                model_file.write_text(saved_xml, encoding="utf-8")

                await call("create_network", name="EmptyBeforeReopen")
                empty_xml = await call("export_pnml")
                assert "No network to export" in empty_xml, "The original session did not clear"
                await call("import_pnml", xml=model_file.read_text(encoding="utf-8"), replace=True)
                await call("validate_net")
                reopened_xml = await call("export_pnml")
                assert document_shape(reopened_xml) == shape, "Saved model structure changed after reopening"
                (output / "reopened-workflow.pnml").write_text(reopened_xml, encoding="utf-8")
                second_result = await call("run_simulation", simulation_time=10, time_unit="s")
                second_markings = markings(second_result)
                assert second_markings == first_markings, second_result
                assert "Service: buffer=0," in second_result, second_result
                assert "Completed: total_consumed=6" in second_result, second_result

                return {"endpoint": base_url + "/mcp", "frontendStatus": home.status_code,
                        "initialTokens": 6, "places": 2, "transitions": 1, "arcs": 2,
                        "firstFinalMarkings": first_markings, "reopenedFinalMarkings": second_markings,
                        "firstThroughput": int(re.search(r"Completed: total_consumed=(\d+)", first_result).group(1)),
                        "reopenedThroughput": int(re.search(r"Completed: total_consumed=(\d+)", second_result).group(1)),
                        "savedModel": str(model_file), "savedSha256": hashlib.sha256(saved_xml.encode()).hexdigest(),
                        "resources": resources, "mcpCalls": len(transcript)}
    finally:
        (output / "mcp-transcript.json").write_text(json.dumps(transcript, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--frontend-dir", type=Path, default=BACKEND.parent / "frontend" / "dist")
    args = parser.parse_args()
    output = (args.output or Path(tempfile.mkdtemp(prefix="petri-mcp-workflow-"))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not (args.frontend_dir / "index.html").is_file():
        raise SystemExit("Build frontend/dist with npm run build before running this scenario")

    container = "petri-mcp-smoke-" + uuid.uuid4().hex[:10]
    db_port, app_port = free_port(), free_port()
    while app_port == db_port:
        app_port = free_port()
    base_url = f"http://127.0.0.1:{app_port}"
    environment = os.environ.copy()
    environment.update({"POSTGRES_PASSWORD": secrets.token_hex(20), "DB_HOST": "127.0.0.1",
                        "DB_PORT": str(db_port), "DB_NAME": "petri_mcp_smoke", "DB_USER": "petri_smoke",
                        "AUTH_MODE": "single_user", "APP_ENV": "local", "APP_DEBUG": "false",
                        "AUTH_JWT_SECRET_KEY": secrets.token_hex(32), "SIMULATION_ENGINE": "builtin",
                        "CREDENTIALS_CIPHER": "fernet", "CREDENTIALS_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
                        "CORS_ORIGINS": base_url, "CORS_ALLOW_CREDENTIALS": "false",
                        "SERVER_HOST": "127.0.0.1", "SERVER_PORT": str(app_port), "MCP_ENABLED": "true",
                        "OPENAI_ENABLED": "true", "APP_PUBLIC_URL": base_url,
                        "FRONTEND_STATIC_DIR": str(args.frontend_dir.resolve()), "LOGGING_LEVEL": "WARNING",
                        "LOGGING_FILE": str(output / "application.log")})
    environment["DB_PASSWORD"] = environment["POSTGRES_PASSWORD"]
    process = None
    started_container = False
    try:
        subprocess.run(["docker", "run", "--detach", "--rm", "--name", container,
                        "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=petri_smoke",
                        "--env", "POSTGRES_DB=petri_mcp_smoke", "--publish", f"127.0.0.1:{db_port}:5432",
                        args.postgres_image], check=True, env=environment, capture_output=True, text=True)
        started_container = True
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "petri_smoke", "-d", "petri_mcp_smoke"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Isolated PostgreSQL did not become ready")

        with (output / "migrations.log").open("w", encoding="utf-8") as log:
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
                           env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (output / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                                        "--port", str(app_port), "--loop", "src.core.event_loop:new_event_loop", "--no-access-log"], cwd=BACKEND,
                                       env=environment, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("main:app exited during startup; see server.log")
                try:
                    response = httpx.get(base_url + "/api/v1/config", timeout=1)
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("main:app did not become ready; see server.log")
            print("APP_READY " + base_url, flush=True)
            checkpoint_schema = subprocess.run(["docker", "exec", container, "psql", "-U", "petri_smoke",
                                                "-d", "petri_mcp_smoke", "-Atc", "SELECT COUNT(*) FROM checkpoint_migrations"],
                                               capture_output=True, text=True, check=True)
            assert int(checkpoint_schema.stdout.strip()) > 0, "PostgreSQL checkpointer did not initialize"
            result = asyncio.run(workflow(base_url, output))
            result["checkpointSchemaReady"] = True
            (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if started_container:
            subprocess.run(["docker", "stop", container], check=False, capture_output=True)
        print("EVIDENCE " + str(output), flush=True)


if __name__ == "__main__":
    main()
