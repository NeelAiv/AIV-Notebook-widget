import requests
import json
import os
from openai import OpenAI

CONFIG_FILE = "llm_config.json"

# 👉 Define your OpenAI API key here
OPENAI_API_KEY = "OPENAI_API_KEY"

class LLMClient:
    def __init__(self):
        self.custom_server_url = "http://138.201.254.240:8098/v1/chat"
        self.load_config()

    def load_config(self):
        """Loads LLM settings from JSON file and initializes the active client."""
        # Default configuration
        self.config = {
            "provider": "custom", # 'custom' or 'openai'
            "openai_model": "gpt-4o" # default model
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

        if self.config["provider"] == "openai" and OPENAI_API_KEY:
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
            print(f"🧠 Using OpenAI Provider (Model: {self.config['openai_model']})")
        else:
            if self.config["provider"] == "openai":
                print("⚠️ OpenAI selected but OPENAI_API_KEY is missing in remote_llm.py. Falling back to custom.")
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
        self.load_config() # Reload the client with new settings

    def generate(self, system_message: str, user_message: str, images: list = None):
        """Routes the prompt to the active provider."""
        if self.config["provider"] == "openai" and self.openai_client:
            return self._generate_openai(system_message, user_message, images)
        return self._generate_custom(system_message, user_message, images)

    def _generate_openai(self, system_message: str, user_message: str, images: list = None):
        messages = [{"role": "system", "content": system_message}]
        
        # If images are provided, use the OpenAI vision array format
        if images:
            content_array = [{"type": "text", "text": user_message}]
            for img_b64 in images:
                content_array.append({
                    "type": "image_url",
                    "image_url": {"url": img_b64} # Already contains data:image/png;base64,...
                })
            messages.append({"role": "user", "content": content_array})
        else:
            # Standard text-only format
            messages.append({"role": "user", "content": user_message})

        try:
            response = self.openai_client.chat.completions.create(
                model=self.config["openai_model"],
                messages=messages,
                temperature=0.2 
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ OpenAI API Error: {e}")
            return f"Error connecting to OpenAI: {str(e)}"

    def _generate_custom(self, system_message: str, user_message: str, images: list = None):
        # Notify the local LLM that an image was provided, just in case it's a text-only model
        if images:
            user_message = f"[User attached {len(images)} image(s)]\n" + user_message

        # Your existing custom prompt formatting
        full_prompt = f"""<|system|>
{system_message}
<|end|>
<|user|>
{user_message}
<|end|>
<|assistant|>"""

        headers = {'Content-Type': 'application/json'}
        payload = {"prompt": full_prompt}

        try:
            response = requests.post(self.custom_server_url, headers=headers, json=payload, timeout=300)
            response.raise_for_status()
            json_response = response.json()
            return json_response.get("response", "").strip()
        except requests.exceptions.Timeout:
            return "Error: Remote LLM server timed out."
        except Exception as e:
            return f"Error connecting to Custom LLM: {str(e)}"

# Singleton instance
llm_instance = LLMClient()