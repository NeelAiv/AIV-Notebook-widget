import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import os

class LocalLLM:
    def __init__(self):
        # We stay with Phi-3 Mini as it's excellent for CPU-based reasoning
        self.model_id = "microsoft/Phi-3-mini-4k-instruct"
        
        print(f"🧠 Loading LLM into System RAM: {self.model_id}...")
        print("   (Using 16GB RAM as the engine...)")

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            
            # --- CPU OPTIMIZED LOADING ---
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                # We force it to CPU to avoid the 2GB GPU bottleneck
                device_map="cpu", 
                # bfloat16 is efficient and works well on 12th Gen Intel CPUs
                torch_dtype=torch.bfloat16, 
                trust_remote_code=True
            )
            
            self.pipe = pipeline(
                "text-generation", 
                model=self.model, 
                tokenizer=self.tokenizer
            )
            print("✅ LLM Loaded Successfully on CPU.")
            
        except Exception as e:
            print(f"❌ Error loading LLM: {e}")
            raise e

    def generate(self, user_query, data_context):
        system_msg = (
            "You are a strict Security Analyst AI. "
            "Answer the user's question using ONLY the provided DATA context. "
            "If the answer is not in the data, state that you do not know."
        )

        full_prompt = f"""<|system|>
{system_msg}

DATA CONTEXT:
{data_context}
<|end|>
<|user|>
{user_query}
<|end|>
<|assistant|>"""

        # We keep max_new_tokens lower for better CPU speed
        outputs = self.pipe(
            full_prompt,
            max_new_tokens=200, 
            do_sample=True,
            temperature=0.1,
        )

        return outputs[0]['generated_text'].split("<|assistant|>")[-1].strip()

# Singleton instance
llm_instance = LocalLLM()