# --- START OF FILE app/orchestrator.py (MODIFIED) ---

from app.db.postgres import PostgresClient
from app.core.embedder import embedder_instance
from app.core.remote_llm import llm_instance # Import the renamed LLMClient instance
import json
import re # Import regex for parsing cell numbers from user queries
from typing import List, Dict, Any

class IncidentOrchestrator:
    def __init__(self):
        self.db = PostgresClient()
        self.embedder = embedder_instance
        self.llm = llm_instance
        self.active_file_context = "" # Store uploaded file content

    def set_file_context(self, text: str):
        """Sets the context for file-based Q&A."""
        self.active_file_context = text

    def _get_llm_response(self, system_message: str, user_message: str, tool_used: str = "LLM_Generic") -> Dict[str, Any]:
        """Helper to get a response from the LLM."""
        answer = self.llm.generate(system_message, user_message)
        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": f"LLM call for {tool_used} intent.",
            "raw_data": [] # No raw data for generic LLM calls
        }

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """Formats chat history for LLM context."""
        if not history:
            return "No previous conversation."
        
        formatted = []
        for msg in history[-5:]: # Limit to last 5 exchanges to save tokens
            role = msg.get('role', 'unknown').title()
            content = msg.get('content', '')
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)

    def _identify_intent(self, user_query: str, notebook_cells: List[str], client_vars: List[str], chat_history: List[Dict[str, str]]) -> str:
        """
        FAST ROUTING: Uses keywords/regex first, falls back to LLM only if necessary.
        """
        q = user_query.lower().strip()
        print(f"🕵️ ORCHESTRATOR: Analyzing intent for: '{q}'") # <--- DEBUG PRINT

        # --- 1. FILE UPLOAD QA (Instant) ---
        if self.active_file_context and any(x in q for x in ["file", "document", "pdf", "summary", "upload", "spreadsheet"]):
            print("⚡ FAST MATCH: Intent identified as FILE_QA via keywords") # <--- DEBUG PRINT
            return "FILE_QA"

        # --- 2. EXPLAIN CODE (Instant) ---
        # Matches: "explain cell 1", "define code", "what does cell 2 do"
        explain_patterns = [
            r"explain", r"describe", r"define", r"meaning", 
            r"what does .* code", r"what does .* cell", r"how does .* work"
        ]
        if any(re.search(p, q) for p in explain_patterns):
            print("⚡ FAST MATCH: Intent identified as EXPLAIN_CODE via regex") # <--- DEBUG PRINT
            return "EXPLAIN_CODE"

        # --- 3. SQL (Instant) ---
        # Look for strong SQL keywords
        if any(x in q for x in ["select ", "from ", "count(", "database", "sql", "table", "query data"]):
            print("⚡ FAST MATCH: Intent identified as SQL_QUERY via keywords") # <--- DEBUG PRINT
            return "SQL_QUERY"

        # --- 4. GENERATE CODE (Instant) ---
        # Triggers on plotting, logic, or explicit code requests
        code_keywords = ["plot", "graph", "chart", "code", "python", "dataframe", "pandas", "function", "generate", "write", "create a","make it", "change", "update", "add to", "modify", "fix"]
        if any(x in q for x in code_keywords):
            print("⚡ FAST MATCH: Intent identified as GENERATE_CODE via keywords") # <--- DEBUG PRINT
            return "GENERATE_CODE"

        # --- 5. VECTOR SEARCH (Instant) ---
        if "search" in q or "find similar" in q:
            print("⚡ FAST MATCH: Intent identified as VECTOR_SEARCH via keywords") # <--- DEBUG PRINT
            return "VECTOR_SEARCH"

        # --- 6. SLOW FALLBACK (LLM) ---
        print("🐢 NO MATCH: Falling back to LLM for intent classification...") # <--- DEBUG PRINT
        
        system_msg = (
            "Identify user intent: SQL_QUERY, VECTOR_SEARCH, EXPLAIN_CODE, GENERATE_CODE, FILE_QA, GENERAL_QUESTION. Output ONLY the category."
        )
        
        notebook_context_str = "\n".join([f"Cell {i+1}:\n```python\n{cell}\n```" for i, cell in enumerate(notebook_cells)])
        history_str = self._format_history(chat_history)
        
        user_msg = f"""User Query: {user_query}
Previous Chat History: {history_str}
Notebook Code: {notebook_context_str if notebook_cells else "None"}
Identify the PRIMARY intent (choose only ONE): SQL_QUERY, VECTOR_SEARCH, EXPLAIN_CODE, GENERATE_CODE, FILE_QA, GENERAL_QUESTION"""
        
        intent_response = self.llm.generate(system_msg, user_msg)
        intent = intent_response.strip().upper().replace(" ", "_")
        
        valid_intents = ["SQL_QUERY", "VECTOR_SEARCH", "EXPLAIN_CODE", "GENERATE_CODE", "FILE_QA", "GENERAL_QUESTION"]
        if intent in valid_intents:
            return intent
        return "GENERAL_QUESTION"


    # ... (handlers need updating too) ...
    # I'll update route_and_execute first to pass history, and then general_question handler
    
    def _handle_sql_query(self, user_query: str) -> Dict[str, Any]:
        """Handles SQL query intent, constructing SQL and summarizing results."""
        tool_used = "SQL"
        base_sql = 'SELECT incident_id, project, priority, status, threat_category FROM "cyber_secuitry"'
        sql = ""
        
        query_lower = user_query.lower()

        if "critical" in query_lower:
            sql = f"{base_sql} WHERE priority = 'Critical';"
        elif "open" in query_lower:
            sql = f"{base_sql} WHERE status = 'Open';"
        elif "how many incidents" in query_lower or "count incidents" in query_lower:
            sql = 'SELECT COUNT(incident_id) FROM "cyber_secuitry";'
        elif "list all incidents" in query_lower:
            sql = f"{base_sql} LIMIT 20;" # Limiting for display
        elif "highest priority" in query_lower:
             sql = f"{base_sql} ORDER BY CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 WHEN 'Low' THEN 4 ELSE 5 END LIMIT 5;"
        else:
            # Default to a small list for general "list" or "how many" without specific filters
            sql = f"{base_sql} LIMIT 10;"

        retrieved_data = self.db.execute_query(sql)
        execution_trace = sql
        
        # Use LLM to summarize SQL results for a user-friendly answer
        llm_context = json.dumps(retrieved_data, indent=2, default=str)
        system_msg = "You are a Security Analyst AI. Summarize the provided incident data concisely. Use Markdown tables if listing data. Use bold text for key metrics."
        user_msg = f"Summarize the following incident data:\n\n{llm_context}\n\nUser's original query: {user_query}"
        answer = self.llm.generate(system_msg, user_msg)

        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": execution_trace,
            "raw_data": retrieved_data
        }

    def _handle_vector_search(self, user_query: str) -> Dict[str, Any]:
        """Handles vector search intent, performing search and summarizing results."""
        tool_used = "Vector"
        query_vec = self.embedder.get_embedding(user_query)
        retrieved_data = self.db.search_vectors(query_vec, limit=5)
        execution_trace = "Vector Search on cyber_secuitry table."

        llm_context = json.dumps(retrieved_data, indent=2, default=str)
        system_msg = "You are a Security Analyst AI. Answer the user's question using ONLY the provided DATA context. If the answer is not in the data, state that you do not know."
        user_msg = f"Based on the following context, answer the user's query: '{user_query}'\n\nDATA CONTEXT:\n{llm_context}"
        answer = self.llm.generate(system_msg, user_msg)

        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": execution_trace,
            "raw_data": retrieved_data
        }

    def _handle_explain_code(self, user_query: str, notebook_cells: List[str]) -> Dict[str, Any]:
        """Handles requests to explain notebook code content."""
        tool_used = "Explain_Code"
        
        if not notebook_cells:
            return self._get_llm_response(
                "You are a helpful AI assistant.",
                "There is no code in the notebook to explain.",
                tool_used="Explain_Code_Error"
            )

        # Try to extract cell number from query (e.g., "cell 3", "third cell")
        cell_number_match = re.search(r'(?:cell|the)\s+(\d+)', user_query, re.IGNORECASE)
        cell_content = ""
        cell_index_display = -1 # For user-facing messages (1-indexed)

        if cell_number_match:
            try:
                cell_index_zero_based = int(cell_number_match.group(1)) - 1 # Convert to 0-indexed
                if 0 <= cell_index_zero_based < len(notebook_cells):
                    cell_content = notebook_cells[cell_index_zero_based]
                    cell_index_display = cell_index_zero_based + 1
                else:
                    return self._get_llm_response(
                        "You are a helpful AI assistant.",
                        f"I cannot find cell number {cell_index_zero_based + 1}. There are only {len(notebook_cells)} cells in the notebook.",
                        tool_used="Explain_Code_Error"
                    )
            except ValueError:
                pass # If number parsing fails, continue to default behavior

        # If no specific cell mentioned or parsing failed, default to the last cell
        if not cell_content and notebook_cells:
            cell_content = notebook_cells[-1]
            cell_index_display = len(notebook_cells)
            trace_info = f"Explaining content of the last cell (Cell {cell_index_display})."
        elif cell_content:
            trace_info = f"Explaining content of Cell {cell_index_display}."
        else: # Should not be reached due to initial check, but for safety
            return self._get_llm_response(
                "You are a helpful AI assistant.",
                "Failed to identify code to explain.",
                tool_used="Explain_Code_Error"
            )

        system_msg = (
            "You are a helpful and detailed Python programming assistant. "
            "Explain the provided Python code clearly. "
            "Structure your response using standard Markdown formatting: "
            "use '###' for section headers, bullet points for steps, and bold text for emphasis. "
            "Do NOT use decorative lines like '====' or '----'. "
            "Wrap all code references in backticks (e.g., `variable_name`)."
        )
        user_msg = f"Explain the following Python code from the notebook:\n```python\n{cell_content}\n```"
        
        return self._get_llm_response(system_msg, user_msg, tool_used)


    def _handle_generate_code(self, user_query: str, notebook_cells: List[str], client_vars: List[str], is_modification: bool = False, original_code: str = None, active_cell_id: str = None) -> Dict[str, Any]:
        """Handles requests to generate new Python code."""
        
        # --- REFACTORING LOGIC ---
        if is_modification and original_code:
            tool_used = "Modify_Code"
            system_msg = (
                "You are a code refactoring assistant. A user will provide a block of Python code and a request to modify it. "
                "Your task is to return the *entire*, complete, modified code block. "
                "DO NOT add explanations, comments, or markdown wrappers like ```python. ONLY return the raw, updated code."
            )
            user_msg = f"""Original Code:
{original_code}

Modification Request: "{user_query}"

Return the full modified code block now:"""
            
            modified_code_raw = self.llm.generate(system_msg, user_msg)
            modified_code = modified_code_raw.replace("```python", "").replace("```", "").strip()

            return {
                "answer": f"I've updated the code in {active_cell_id.replace('-', ' ') if active_cell_id else 'the active cell'} to apply your changes.",
                "tool_used": tool_used,
                "action": "UPDATE_CELL",
                "cell_id": active_cell_id,
                "modified_code": modified_code,
                "trace": "LLM modified existing code block.",
                "raw_data": []
            }
        
        # --- ORIGINAL GENERATION LOGIC ---
        tool_used = "Generate_Code"
        
        # 1. Get the very last cell content specifically (The one being modified)
        last_cell_content = notebook_cells[-1] if notebook_cells else ""
        
        # 2. Context Pruning
        recent_cells = notebook_cells[-3:] if len(notebook_cells) > 3 else notebook_cells
        offset = len(notebook_cells) - len(recent_cells)
        notebook_context_str = "\n".join([f"Cell {i+1+offset}:\n```python\n{cell}\n```" for i, cell in enumerate(recent_cells)])

        # 3. Smart Hints
        hints = []
        if "3d" in user_query.lower():
            hints.append("For 3D plots, use: `from mpl_toolkits.mplot3d import Axes3D`, `fig = plt.figure()`, `ax = fig.add_subplot(111, projection='3d')`.")
        
        hint_str = "\n".join(hints)
        specific_instructions = f"SPECIFIC INSTRUCTIONS:\n{hint_str}" if hints else ""

        system_msg = (
            "You are an expert Python programmer.\n"
            "RULES:\n"
            "1. Output the COMPLETE code block. Do not just output the changed lines. Output the full runnable cell.\n" # <--- IMPORTANT
            "2. NO Markdown wrappers (no ```python). Just raw code.\n"
            "3. NO explanations. Just code.\n"
            "4. VISUALIZATION SPECIFICS: Check if the user asks for 3D plots and use correct libraries.\n"
        )
        
        user_msg = f"""User Request: {user_query}

Current Code in Active Cell (Modify THIS code if asking for changes):
```python
{last_cell_content}
```

Full Notebook Context:
{notebook_context_str}

{specific_instructions}

Active Variables: {json.dumps(client_vars) if client_vars else "[]"}

Generate the COMPLETE updated Python code:
"""
        generated_code_raw = self.llm.generate(system_msg, user_msg)
        
        # Clean up code blocks if LLM ignores instruction
        code_match = re.search(r'```python\n(.*?)```', generated_code_raw, re.DOTALL)
        if code_match:
            generated_code = code_match.group(1).strip()
        else:
            generated_code = generated_code_raw.replace("```", "").strip()

        # We return the code wrapped so frontend regex can find it
        answer = f"Here is the updated code:\n```python\n{generated_code}\n```"
        
        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": "LLM generated Python code.",
            "raw_data": []
        }

    def _handle_file_qa(self, user_query: str) -> Dict[str, Any]:
        """Handles questions based on the uploaded file content."""
        tool_used = "FILE_QA"
        
        if not self.active_file_context:
             return self._get_llm_response(
                "You are a helpful AI assistant.",
                "No file has been uploaded yet. Please upload a file to ask questions about it.",
                tool_used="FILE_QA_Error"
            )

        system_msg = (
            "You are a helpful AI assistant. Answer the user's question based ONLY on the provided file content. "
            "Respond in the following STRICT FORMAT:\n"
            "----------------------------------\n"
            "Title: [Appropriate Title]\n"
            "Summary: [1-2 sentences]\n"
            "Key Points:\n"
            "- Point 1\n"
            "- Point 2\n"
            "- Point 3\n\n"
            "Detailed Explanation:\n"
            "[Use bullet points and short paragraphs]\n\n"
            "Conclusion:\n"
            "[Brief conclusion]\n"
            "----------------------------------\n"
            "If the answer is not found in the file, clearly state that."
        )
        
        user_msg = f"""User Question: {user_query}

File Content:
{self.active_file_context}
"""
        return self._get_llm_response(system_msg, user_msg, tool_used)

    def _handle_general_question(self, user_query: str, notebook_cells: List[str], client_vars: List[str], chat_history: List[Dict[str, str]]) -> Dict[str, Any]:
        """Handles general questions using the LLM, leveraging notebook context if available."""
        tool_used = "General_Question"
        
        notebook_context_str = "\n".join([f"Cell {i+1}:\n```python\n{cell}\n```" for i, cell in enumerate(notebook_cells)])
        history_str = self._format_history(chat_history)
        
        system_msg = (
            "You are a helpful and knowledgeable AI assistant for a data science notebook. "
            "Answer the user's question, making use of the provided `Notebook Cells` and `Active Variables`. "
            "CONSIDER PREVIOUS CHAT HISTORY for context (e.g., if user says 'it', referring to previous topic). "
            "If the answer is not in the context, use your general knowledge."
        )
        user_msg = f"""User Question: {user_query}

Previous Chat History:
{history_str}

Notebook Cells:
{notebook_context_str if notebook_cells else "No existing notebook cells."}

Active Variables: {json.dumps(client_vars) if client_vars else "No active variables."}
"""
        return self._get_llm_response(system_msg, user_msg, tool_used)


    def route_and_execute(self, user_query: str, notebook_cells: List[str], client_vars: List[str], chat_history: List[Dict[str, str]]=[], *, is_modification: bool = False, original_code: str = None, active_cell_id: str = None) -> Dict[str, Any]:
        """
        Routes the user query to the appropriate tool based on identified intent.
        """
        
        # Identify the user's intent using the LLM (or fast path)
        # If it's a modification, force GENERATE_CODE intent
        if is_modification:
            intent = "GENERATE_CODE"
        else:
            intent = self._identify_intent(user_query, notebook_cells, client_vars, chat_history)
        
        if intent == "SQL_QUERY":
            return self._handle_sql_query(user_query)
        elif intent == "VECTOR_SEARCH":
            return self._handle_vector_search(user_query)
        elif intent == "EXPLAIN_CODE":
            return self._handle_explain_code(user_query, notebook_cells)
        elif intent == "GENERATE_CODE":
             return self._handle_generate_code(user_query, notebook_cells, client_vars, is_modification, original_code, active_cell_id)
        elif intent == "FILE_QA":
            return self._handle_file_qa(user_query)
        else:
            return self._handle_general_question(user_query, notebook_cells, client_vars, chat_history)