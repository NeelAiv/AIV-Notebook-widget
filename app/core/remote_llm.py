import requests
import json
import os
import re
from openai import OpenAI

CONFIG_FILE = "llm_config.json"

# 👉 Define your OpenAI API key here
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

class LLMClient:
    def __init__(self):
        # FIXED: Updated to the correct OpenAI-compatible completions endpoint
        self.custom_server_url = "http://95.217.115.227:8098/v1/chat/completions"
        self.load_config()

    def load_config(self):
        """Loads LLM settings from JSON file and initializes the active client."""
        self.config = {
            "provider": "custom", 
            "openai_model": "gpt-4o"
        }
        
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    file_config = json.load(f)
                    if "provider" in file_config:
                        self.config["provider"] = file_config["provider"]
                    if "openai_model" in file_config:
                        self.config["openai_model"] = file_config["openai_model"]
            except json.JSONDecodeError:
                pass

        if self.config["provider"] == "openai" and OPENAI_API_KEY and OPENAI_API_KEY != "OPENAI_API_KEY":
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
            print(f"🧠 Using OpenAI Provider (Model: {self.config['openai_model']})")
        else:
            if self.config["provider"] == "openai":
                print("⚠️ OpenAI selected but OPENAI_API_KEY is missing/invalid. Falling back to custom.")
            self.config["provider"] = "custom"
            self.openai_client = None
            print(f"🧠 Using Custom Remote LLM Server: {self.custom_server_url}")

    def update_config(self, new_config: dict):
        """Updates and saves the configuration."""
        if "provider" in new_config:
            self.config["provider"] = new_config["provider"]
        if "openai_model" in new_config:
            self.config["openai_model"] = new_config["openai_model"]
            
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=4)
        self.load_config()

    def generate(self, system_message: str, user_message: str, images: list = None, tools: list = None):
        """Routes the prompt to the active provider and handles Native Tool Calling."""
        if self.config["provider"] == "openai" and self.openai_client:
            print(f"    📡 Routing to OpenAI ({self.config.get('openai_model')})")
            return self._generate_openai(system_message, user_message, images, tools)
        print(f"    📡 Routing to Custom LLM ({self.custom_server_url})")
        return self._generate_custom(system_message, user_message, images, tools)

    def _generate_openai(self, system_message: str, user_message: str, images: list = None, tools: list = None):
        messages = [{"role": "system", "content": system_message}]
        
        if images:
            content_array =[{"type": "text", "text": user_message}]
            for img_b64 in images:
                if not img_b64.startswith("data:image"):
                    img_b64 = f"data:image/jpeg;base64,{img_b64}"
                content_array.append({
                    "type": "image_url",
                    "image_url": {"url": img_b64}
                })
            messages.append({"role": "user", "content": content_array})
        else:
            messages.append({"role": "user", "content": user_message})

        try:
            kwargs = {
                "model": self.config["openai_model"],
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": self.config.get("max_tokens", 3000)
            }
            
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self.openai_client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            
            if tools:
                if msg.tool_calls:
                    calls =[]
                    for tc in msg.tool_calls:
                        args = tc.function.arguments
                        try: args = json.loads(args)
                        except: pass
                        calls.append({"name": tc.function.name, "arguments": args})
                    return {"type": "tool_calls", "tool_calls": calls, "content": msg.content or ""}
                else:
                    return {"type": "text", "content": msg.content or ""}
            else:
                return msg.content.strip() if msg.content else ""
                
        except Exception as e:
            err = f"Error connecting to OpenAI: {str(e)}"
            return {"type": "text", "content": err} if tools else err

    def _generate_custom(self, system_message: str, user_message: str, images: list = None, tools: list = None):
        messages =[{"role": "system", "content": system_message}]
        
        if images:
            content_array =[{"type": "text", "text": user_message}]
            for img_b64 in images:
                if not img_b64.startswith("data:image"):
                    img_b64 = f"data:image/jpeg;base64,{img_b64}"
                content_array.append({
                    "type": "image_url",
                    "image_url": {"url": img_b64} 
                })
            messages.append({"role": "user", "content": content_array})
        else:
            messages.append({"role": "user", "content": user_message})

        payload = {
            "model": "qwen-vision", 
            "messages": messages,
            "max_tokens": 2048,  # Increased from 1024 for better responses
            "temperature": 0.1,  # Reduced from 0.05 for faster generation
            "stream": True 
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {'Content-Type': 'application/json'}

        try:
            response = requests.post(self.custom_server_url, headers=headers, json=payload, stream=True, timeout=60)  # Reduced timeout from 1200
            response.raise_for_status() 
            
            final_text = ""
            thinking_text = ""
            tool_calls_acc = {}
            
            if tools:
                print(f"    🛠️  Payload Tools: {[t['function']['name'] for t in tools]}")
            
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith("data:"):
                        data_str = decoded_line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                thinking_text += delta["reasoning_content"]
                                
                            if "content" in delta and delta["content"]:
                                final_text += delta["content"]
                                
                            if "tool_calls" in delta:
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_acc:
                                        func = tc.get("function", {})
                                        tool_calls_acc[idx] = {
                                            "name": func.get("name", ""),
                                            "arguments": func.get("arguments", "")
                                        }
                                    else:
                                        func = tc.get("function", {})
                                        if "arguments" in func:
                                            tool_calls_acc[idx]["arguments"] += func["arguments"]
                                            
                        except json.JSONDecodeError:
                            pass
            
            if thinking_text:
                print(f"--- THINKING ---\n{thinking_text}\n----------------")

            final_text = re.sub(r'<think>.*?</think>', '', final_text, flags=re.DOTALL).strip()
            
            if tools:
                if tool_calls_acc:
                    calls =[]
                    for call in tool_calls_acc.values():
                        args = call["arguments"]
                        try: args = json.loads(args)
                        except: pass
                        calls.append({"name": call["name"], "arguments": args})
                    return {"type": "tool_calls", "tool_calls": calls, "content": final_text, "thinking": thinking_text}
                else:
                    return {"type": "text", "content": final_text, "thinking": thinking_text}
            else:
                return final_text
            
        except requests.exceptions.Timeout:
            err = "Error: Remote Custom LLM timed out."
            return {"type": "text", "content": err} if tools else err
        except requests.exceptions.HTTPError as e:
            err = f"HTTP Error connecting to Custom LLM: {e.response.text}"
            return {"type": "text", "content": err} if tools else err
        except Exception as e:
            err = f"Error connecting to Custom LLM: {str(e)}"
            return {"type": "text", "content": err} if tools else err

# Singleton instance
llm_instance = LLMClient()