import requests
import json
import os
import re
from openai import OpenAI

CONFIG_FILE = "llm_config.json"

# Provider registry — base_url=None means use the SDK's default (OpenAI official)
PROVIDERS = {
    "openai":     {"base_url": None,                                          "default_model": "gpt-4o"},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",                 "default_model": "deepseek-chat"},
    "nvidia":     {"base_url": "https://integrate.api.nvidia.com/v1",         "default_model": "meta/llama-3.1-70b-instruct"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",                "default_model": "openai/gpt-4o"},
    "gemini":     {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "default_model": "gemini-2.0-flash"},
    "claude":     {"base_url": None,                                          "default_model": "claude-3-5-sonnet-20241022"},
    "custom":     {"base_url": None,                                          "default_model": "qwen-vision"},
}

class LLMClient:
    def __init__(self):
        self.custom_server_url = "http://95.217.115.227:8098/v1/chat/completions"
        self.client = None          # OpenAI-compatible client
        self.anthropic_client = None
        self.load_config()

    def load_config(self):
        """Loads settings from llm_config.json and initialises the right SDK client."""
        self.config = {
            "provider": "custom",
            "model": "",
            "api_key": "",
            # Legacy key names kept for backward compat
            "openai_model": "gpt-4o",
            "openai_api_key": "",
        }

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    saved = json.load(f)
                self.config.update(saved)
            except (json.JSONDecodeError, OSError):
                pass

        # Normalise: if old config used openai_model/openai_api_key, migrate
        if not self.config.get("model"):
            self.config["model"] = self.config.get("openai_model") or ""
        if not self.config.get("api_key"):
            self.config["api_key"] = self.config.get("openai_api_key") or ""

        self._init_client()

    def _init_client(self):
        provider = self.config.get("provider", "custom")
        api_key  = self.config.get("api_key", "").strip()
        model    = self.config.get("model", "").strip()

        if not model:
            self.config["model"] = PROVIDERS.get(provider, {}).get("default_model", "")

        self.client = None
        self.anthropic_client = None

        if provider == "custom":
            # Use saved custom URL if provided, otherwise fall back to default
            saved_url = self.config.get("custom_server_url", "").strip()
            if saved_url:
                self.custom_server_url = saved_url
            print(f"🧠 Custom LLM → {self.custom_server_url}")
            return

        if not api_key:
            print(f"⚠️  Provider '{provider}' selected but no API key saved — falling back to custom.")
            self.config["provider"] = "custom"
            return

        if provider == "claude":
            try:
                import anthropic
                self.anthropic_client = anthropic.Anthropic(api_key=api_key)
                print(f"🧠 Claude → {self.config['model']}")
            except ImportError:
                print("⚠️  anthropic package not installed. Run: pip install anthropic")
                self.config["provider"] = "custom"
            return

        # All other providers are OpenAI-compatible
        base_url = PROVIDERS.get(provider, {}).get("base_url")
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        print(f"🧠 {provider.title()} → {self.config['model']}")

    def update_config(self, new_config: dict):
        """Merges new settings, persists to disk, reinitialises client."""
        for key in ("provider", "model", "api_key", "openai_model", "openai_api_key", "custom_server_url"):
            if key in new_config and new_config[key]:
                self.config[key] = new_config[key]

        save_data = {k: v for k, v in self.config.items() if v}
        with open(CONFIG_FILE, "w") as f:
            json.dump(save_data, f, indent=4)
        self.load_config()

    # ------------------------------------------------------------------
    # Public generate — routes to the right backend
    # ------------------------------------------------------------------
    def generate(self, system_message: str, user_message: str,
                 images: list = None, tools: list = None):
        provider = self.config.get("provider", "custom")
        model    = self.config.get("model", "")
        print(f"    📡 {provider.title()} → {model}")

        if provider == "claude" and self.anthropic_client:
            return self._generate_claude(system_message, user_message, tools)

        if provider != "custom" and self.client:
            return self._generate_openai_compat(system_message, user_message, images, tools)

        # Fallback: custom streaming server
        return self._generate_custom(system_message, user_message, images, tools)

    def generate_stream(self, system_message: str, user_message: str,
                        images: list = None, tools: list = None):
        """
        Generator that yields token strings as they arrive from the LLM.
        Yields strings for text tokens, and a final dict for tool calls.
        {"type": "token", "text": "..."} — incremental text
        {"type": "tool_call", "name": "...", "arguments": {...}, "content": "..."} — tool decision
        {"type": "done"} — stream finished
        """
        provider = self.config.get("provider", "custom")
        model    = self.config.get("model", "")
        print(f"    📡 Streaming: {provider.title()} → {model}")

        if provider == "claude" and self.anthropic_client:
            yield from self._stream_claude(system_message, user_message, tools)
        elif provider != "custom" and self.client:
            yield from self._stream_openai_compat(system_message, user_message, images, tools)
        else:
            yield from self._stream_custom(system_message, user_message, images, tools)

    def _stream_openai_compat(self, system_message, user_message, images=None, tools=None):
        """Stream tokens from OpenAI-compatible providers."""
        model = self.config.get("model") or "gpt-4o"
        messages = [{"role": "system", "content": system_message}]

        if images:
            content = [{"type": "text", "text": user_message}]
            for img in images:
                if not img.startswith("data:image"):
                    img = f"data:image/jpeg;base64,{img}"
                content.append({"type": "image_url", "image_url": {"url": img}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": self.config.get("max_tokens", 3000),
                "stream": True,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            stream = self.client.chat.completions.create(**kwargs)

            tool_calls_acc = {}
            accumulated_content = ""

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta:
                    continue

                # Stream text content
                if delta.content:
                    accumulated_content += delta.content
                    yield {"type": "token", "text": delta.content}

                # Accumulate tool calls (not streamed token by token)
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "name": tc.function.name or "",
                                "arguments": tc.function.arguments or ""
                            }
                        else:
                            if tc.function.arguments:
                                tool_calls_acc[idx]["arguments"] += tc.function.arguments

            # After stream ends, emit tool call if any
            if tool_calls_acc:
                for call in tool_calls_acc.values():
                    args = call["arguments"]
                    try: args = json.loads(args)
                    except: pass
                    yield {"type": "tool_call", "name": call["name"],
                           "arguments": args, "content": accumulated_content}
            yield {"type": "done"}

        except Exception as e:
            err_str = str(e)
            if "image_url" in err_str or "unknown variant" in err_str or "multimodal" in err_str.lower():
                msg = "⚠️ This model does not support images. Please switch to a vision-capable model in AI Settings or remove the image from your message."
            else:
                msg = f"\n\nError: {e}"
            yield {"type": "token", "text": msg}
            yield {"type": "done"}

    def _stream_claude(self, system_message, user_message, tools=None):
        """Stream tokens from Claude (Anthropic SDK)."""
        model = self.config.get("model") or "claude-3-5-sonnet-20241022"
        try:
            kwargs = {
                "model": model,
                "max_tokens": self.config.get("max_tokens", 3000),
                "system": system_message,
                "messages": [{"role": "user", "content": user_message}],
            }
            if tools:
                claude_tools = []
                for t in tools:
                    fn = t["function"]
                    claude_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
                kwargs["tools"] = claude_tools

            accumulated_content = ""
            tool_uses = []

            with self.anthropic_client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    accumulated_content += text
                    yield {"type": "token", "text": text}

            # Get final message for tool use blocks
            final_msg = stream.get_final_message()
            tool_uses = [b for b in final_msg.content if b.type == "tool_use"]
            if tool_uses:
                for b in tool_uses:
                    yield {"type": "tool_call", "name": b.name,
                           "arguments": b.input, "content": accumulated_content}

            yield {"type": "done"}

        except Exception as e:
            yield {"type": "token", "text": f"\n\nError (Claude): {e}"}
            yield {"type": "done"}

    def _custom_headers(self) -> dict:
        """Build headers for custom server requests, including Bearer token if configured."""
        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("api_key", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _stream_custom(self, system_message, user_message, images=None, tools=None):
        """Stream tokens from the custom server (already streams via SSE)."""
        messages = [{"role": "system", "content": system_message}]
        if images:
            content = [{"type": "text", "text": user_message}]
            for img in images:
                if not img.startswith("data:image"):
                    img = f"data:image/jpeg;base64,{img}"
                content.append({"type": "image_url", "image_url": {"url": img}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        payload = {
            "model": "qwen-vision",
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.1,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = requests.post(
                self.custom_server_url,
                headers=self._custom_headers(),
                json=payload, stream=True, timeout=60
            )
            resp.raise_for_status()

            accumulated_content = ""
            tool_calls_acc = {}

            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data:"):
                    continue
                data_str = decoded[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    if delta.get("content"):
                        token = delta["content"]
                        accumulated_content += token
                        yield {"type": "token", "text": token}

                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        fn  = tc.get("function", {})
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")}
                        elif "arguments" in fn:
                            tool_calls_acc[idx]["arguments"] += fn["arguments"]
                except json.JSONDecodeError:
                    pass

            # Strip think tags from accumulated content
            accumulated_content = re.sub(r"<think>.*?</think>", "", accumulated_content, flags=re.DOTALL).strip()

            if tool_calls_acc:
                for call in tool_calls_acc.values():
                    args = call["arguments"]
                    try: args = json.loads(args)
                    except: pass
                    yield {"type": "tool_call", "name": call["name"],
                           "arguments": args, "content": accumulated_content}

            yield {"type": "done"}

        except Exception as e:
            err_str = str(e)
            if "image_url" in err_str or "unknown variant" in err_str or "multimodal" in err_str.lower():
                msg = "⚠️ This model does not support images. Please switch to a vision-capable model in AI Settings or remove the image from your message."
            else:
                msg = f"\n\nError: {e}"
            yield {"type": "token", "text": msg}
            yield {"type": "done"}

    # ------------------------------------------------------------------
    # OpenAI-compatible (OpenAI / DeepSeek / Nvidia / OpenRouter / Gemini)
    # ------------------------------------------------------------------
    def _generate_openai_compat(self, system_message, user_message, images=None, tools=None):
        model = self.config.get("model") or "gpt-4o"
        messages = [{"role": "system", "content": system_message}]

        if images:
            content = [{"type": "text", "text": user_message}]
            for img in images:
                if not img.startswith("data:image"):
                    img = f"data:image/jpeg;base64,{img}"
                content.append({"type": "image_url", "image_url": {"url": img}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": self.config.get("max_tokens", 3000),
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            resp = self.client.chat.completions.create(**kwargs)
            msg  = resp.choices[0].message

            if tools:
                if msg.tool_calls:
                    calls = []
                    for tc in msg.tool_calls:
                        args = tc.function.arguments
                        try: args = json.loads(args)
                        except: pass
                        calls.append({"name": tc.function.name, "arguments": args})
                    return {"type": "tool_calls", "tool_calls": calls, "content": msg.content or ""}
                return {"type": "text", "content": msg.content or ""}
            return msg.content.strip() if msg.content else ""

        except Exception as e:
            err_str = str(e)
            # Detect image_url not supported error
            if "image_url" in err_str or "unknown variant" in err_str or "multimodal" in err_str.lower():
                err = "⚠️ This model does not support images. Please switch to a vision-capable model in AI Settings or remove the image from your message."
            else:
                err = f"Error ({self.config['provider']}): {e}"
            return {"type": "text", "content": err} if tools else err

    # ------------------------------------------------------------------
    # Claude (Anthropic SDK)
    # ------------------------------------------------------------------
    def _generate_claude(self, system_message, user_message, tools=None):
        model = self.config.get("model") or "claude-3-5-sonnet-20241022"
        try:
            kwargs = {
                "model": model,
                "max_tokens": self.config.get("max_tokens", 3000),
                "system": system_message,
                "messages": [{"role": "user", "content": user_message}],
            }

            if tools:
                # Convert OpenAI tool schema → Anthropic tool schema
                claude_tools = []
                for t in tools:
                    fn = t["function"]
                    claude_tools.append({
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
                kwargs["tools"] = claude_tools

            resp = self.anthropic_client.messages.create(**kwargs)

            if tools:
                tool_uses = [b for b in resp.content if b.type == "tool_use"]
                if tool_uses:
                    calls = [{"name": b.name, "arguments": b.input} for b in tool_uses]
                    text  = next((b.text for b in resp.content if b.type == "text"), "")
                    return {"type": "tool_calls", "tool_calls": calls, "content": text}
                text = next((b.text for b in resp.content if b.type == "text"), "")
                return {"type": "text", "content": text}

            return next((b.text for b in resp.content if b.type == "text"), "").strip()

        except Exception as e:
            err = f"Error (Claude): {e}"
            return {"type": "text", "content": err} if tools else err

    # ------------------------------------------------------------------
    # Custom streaming server (unchanged)
    # ------------------------------------------------------------------
    def _generate_custom(self, system_message, user_message, images=None, tools=None):
        messages = [{"role": "system", "content": system_message}]

        if images:
            content = [{"type": "text", "text": user_message}]
            for img in images:
                if not img.startswith("data:image"):
                    img = f"data:image/jpeg;base64,{img}"
                content.append({"type": "image_url", "image_url": {"url": img}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user_message})

        payload = {
            "model": "qwen-vision",
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.1,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            print(f"    🛠️  Tools: {[t['function']['name'] for t in tools]}")

        try:
            resp = requests.post(
                self.custom_server_url,
                headers=self._custom_headers(),
                json=payload, stream=True, timeout=60
            )
            resp.raise_for_status()

            final_text = ""
            thinking_text = ""
            tool_calls_acc = {}

            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data:"):
                    continue
                data_str = decoded[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("reasoning_content"):
                        thinking_text += delta["reasoning_content"]
                    if delta.get("content"):
                        final_text += delta["content"]
                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        fn  = tc.get("function", {})
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")}
                        elif "arguments" in fn:
                            tool_calls_acc[idx]["arguments"] += fn["arguments"]
                except json.JSONDecodeError:
                    pass

            if thinking_text:
                print(f"--- THINKING ---\n{thinking_text}\n----------------")
            final_text = re.sub(r"<think>.*?</think>", "", final_text, flags=re.DOTALL).strip()

            if tools:
                if tool_calls_acc:
                    calls = []
                    for call in tool_calls_acc.values():
                        args = call["arguments"]
                        try: args = json.loads(args)
                        except: pass
                        calls.append({"name": call["name"], "arguments": args})
                    return {"type": "tool_calls", "tool_calls": calls, "content": final_text}
                return {"type": "text", "content": final_text}
            return final_text

        except requests.exceptions.Timeout:
            err = "Error: Custom LLM timed out."
        except requests.exceptions.HTTPError as e:
            err = f"HTTP Error (custom): {e.response.text}"
        except Exception as e:
            err = f"Error (custom): {e}"
        return {"type": "text", "content": err} if tools else err


# Singleton
llm_instance = LLMClient()
