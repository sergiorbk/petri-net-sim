"""Binary tool results use the same owner-bound signed file route as PNML."""
import base64
import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.openai_api.v1.routers.chat import download_file
from src.services.agent.nodes.tool_node import tool_node
from src.services.chat.file_service import FileService
from src.services.chat.openai_chat_service import OpenAIChatService
from src.services.petri.session import PetriNetSession


async def test_chat_export_becomes_signed_binary_download_without_llm_payload():
    live = PetriNetSession(auto_optimize=False)
    live.builder.net.add_place("Source", tokens=6)
    result = await tool_node({
        "messages": [SystemMessage(content="Do not export system instructions"),
                     HumanMessage(content="Export the six-token task"),
                     AIMessage(content="", tool_calls=[{"name": "export_training_data", "args": {"title": "Six-token task"}, "id": "export"}])],
        "net_data": live.to_net_data(), "conversation_id": "session",
    })
    assert "base64" not in result["messages"][0].content
    assert "Export ready" in result["messages"][0].content
    download = result["net_data"]["_pending_downloads"][0]
    binary = base64.b64decode(download["data_base64"])
    archive = zipfile.ZipFile(io.BytesIO(binary))
    assert json.loads(archive.read("manifest.json"))["capture_scope"]["conversation"] == "application"
    assert b"Export the six-token task" in archive.read("conversation.jsonl")
    assert b"system instructions" not in archive.read("conversation.jsonl")

    file_id, owner = uuid4(), uuid4()
    stored = SimpleNamespace(id=file_id, content=download["data_base64"], content_type="application/zip", filename=download["filename"])
    db = SimpleNamespace(commit=AsyncMock())
    repository = SimpleNamespace(create=AsyncMock(return_value=stored))
    with patch("src.services.chat.file_service.FileRepository", return_value=repository):
        files = FileService(db)
        assert await files.store_download("session", owner, download) == str(file_id)
        assert repository.create.call_args.kwargs["content_type"] == "application/zip"
    service = OpenAIChatService.__new__(OpenAIChatService)
    service._file_service = SimpleNamespace(store_download=AsyncMock(return_value=str(file_id)))
    jwt = SimpleNamespace(create_download_token=lambda **kwargs: "signed-download-token", verify_download_token=lambda token: (file_id, owner))
    with patch("src.services.chat.openai_chat_service.get_jwt_service", return_value=jwt):
        link = await service._binary_download_link(download, "session", owner)
        assert f"/api/v1/files/{file_id}?token=signed-download-token" in link
        assert "data_base64" not in link
    with patch("src.services.auth.jwt_service.get_jwt_service", return_value=jwt), patch(
        "src.openai_api.v1.routers.chat.FileService.get_file", new=AsyncMock(return_value=stored)
    ):
        response = await download_file(str(file_id), "signed-download-token", None)
        assert response.body == binary
        assert response.media_type == "application/zip"
