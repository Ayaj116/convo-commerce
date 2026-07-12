"""Google Gemini adapter — using google-genai SDK (AI Studio compatible)."""
from __future__ import annotations

from config import settings
from src.ai.base import AIProvider, AIResponse, ToolCall

_TYPE_MAP = {"string": "STRING", "integer": "INTEGER", "number": "NUMBER",
             "boolean": "BOOLEAN", "object": "OBJECT", "array": "ARRAY"}


def _convert_schema(schema: dict) -> dict:
    out = {"type": _TYPE_MAP.get(schema.get("type", "object"), "OBJECT")}
    if "properties" in schema:
        out["properties"] = {k: _convert_schema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = _convert_schema(schema["items"])
    if "required" in schema:
        out["required"] = schema["required"]
    if "description" in schema:
        out["description"] = schema["description"]
    return out


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("pip install google-genai to use the Gemini provider") from exc

        self._client = genai.Client(api_key=settings.ai.google_api_key)
        self._types = types
        self._model_name = settings.ai.gemini_model

    def _build_tools(self, tools: list[dict]):
        declarations = [
            self._types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=_convert_schema(t["input_schema"]),
            )
            for t in tools
        ]
        return [self._types.Tool(function_declarations=declarations)]

    def _build_contents(self, messages: list[dict]) -> list:
        contents = []
        i = 0
        while i < len(messages):
            m = messages[i]
            role = m["role"]

            if role == "user" and "tool_call_id" not in m:
                # Plain user message
                contents.append(self._types.Content(
                    role="user",
                    parts=[self._types.Part(text=m["content"])]))
                i += 1

            elif role == "assistant":
                if "_raw_content" in m:
                    # Use preserved raw content (has thought_signature)
                    contents.append(m["_raw_content"])
                elif m.get("tool_calls"):
                    # Reconstruct function call parts
                    parts = [
                        self._types.Part(
                            function_call=self._types.FunctionCall(
                                name=tc["name"], args=tc["input"]))
                        for tc in m["tool_calls"]
                    ]
                    contents.append(self._types.Content(role="model", parts=parts))
                else:
                    contents.append(self._types.Content(
                        role="model",
                        parts=[self._types.Part(text=m.get("content", ""))]))
                i += 1

            elif role == "tool":
                # Collect all consecutive tool results into one user Content
                tool_parts = []
                while i < len(messages) and messages[i]["role"] == "tool":
                    tm = messages[i]
                    tool_parts.append(self._types.Part(
                        function_response=self._types.FunctionResponse(
                            name=tm["name"],
                            response={"result": tm["content"]})))
                    i += 1
                contents.append(self._types.Content(role="user", parts=tool_parts))

            else:
                i += 1

        return contents

    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> AIResponse:
        import time

        config = self._types.GenerateContentConfig(
            system_instruction=system,
            tools=self._build_tools(tools),
            temperature=settings.ai.temperature,
        )

        for attempt in range(3):
            try:
                resp = self._client.models.generate_content(
                    model=self._model_name,
                    contents=self._build_contents(messages),
                    config=config,
                )
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(20 * (attempt + 1))
                else:
                    raise

        raw_content = resp.candidates[0].content
        text_parts, calls = [], []
        for i, part in enumerate(raw_content.parts):
            fc = getattr(part, "function_call", None)
            if fc and fc.name:
                calls.append(ToolCall(id=f"gemini_{i}", name=fc.name, input=dict(fc.args)))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        result = AIResponse(text="\n".join(text_parts) or None, tool_calls=calls)
        result._raw_content = raw_content  # type: ignore[attr-defined]
        return result
