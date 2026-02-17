# --- START OF FILE app/core/remote_llm.py (MODIFIED) ---
import requests
import os
import json # Import json for handling JSONDecodeError

class LLMClient: # Renamed from RemoteLLMClient
    def __init__(self):
        # Your remote LLM server URL, based on your prompt
        self.llm_server_url = "http://138.201.254.240:8098/v1/chat"
        print(f"🧠 Using Remote LLM Server: {self.llm_server_url}")

    # Modified signature to accept system and user messages separately
    def generate(self, system_message: str, user_message: str):
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
            response = requests.post(self.llm_server_url, headers=headers, json=payload, timeout=300) # Added timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            
            json_response = response.json()
            # The remote server's response format shows 'response' as the key
            generated_text = json_response.get("response", "").strip()
            
            # If the remote LLM also includes the <|assistant|> tag, you might still need this split.
            # Based on your curl output, it seems the remote server already provides the clean answer.
            # If it still includes the tags, uncomment the line below:
            # return generated_text.split("<|assistant|>")[-1].strip()
            
            return generated_text

        except requests.exceptions.Timeout:
            print(f"❌ Error: Remote LLM server timed out after 300 seconds.")
            return "Error: Remote LLM server timed out."
        except requests.exceptions.RequestException as e:
            print(f"❌ Error connecting to Remote LLM Server: {e}")
            return f"Error: Could not connect to remote LLM server. {str(e)}"
        except json.JSONDecodeError:
            print(f"❌ Error: Could not decode JSON from remote LLM server response: {response.text}")
            return "Error: Invalid JSON response from remote LLM server."

# Singleton instance for easy import
llm_instance = LLMClient() # Renamed instance