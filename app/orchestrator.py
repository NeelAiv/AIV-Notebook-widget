from app.db.db_client import DBClient
from app.core.embedder import embedder_instance
from app.core.remote_llm import llm_instance
from app.db.vector_store import vector_store
import json
import re
import sys
from typing import List, Dict, Any, Optional



PYODIDE_PRELOADED = {"numpy", "pandas", "matplotlib", "micropip"}

PYODIDE_AVAILABLE = {
    "numpy", "pandas", "matplotlib", "scipy", "scikit-learn", "statsmodels",
    "pillow", "cryptography", "regex", "pytz", "six", "python-dateutil",
    "networkx", "sympy", "lxml", "beautifulsoup4", "requests", "pydantic",
    "attrs", "click", "colorama", "joblib", "threadpoolctl",
}

PYODIDE_UNAVAILABLE = {
    "subprocess", "threading", "multiprocessing", "socket",
    "tkinter", "wx", "PyQt5", "PyQt6", "PySide2", "PySide6",
    "cv2", "opencv", "tensorflow", "torch", "torchvision",
    "flask", "django", "fastapi", "sqlalchemy", "psycopg2",
    "pymysql", "sqlite3",
    "pyspark", "dask", "ray", "celery",
}

IMPORT_ALIAS_MAP = {
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "mpl_toolkits": "matplotlib",
    "cv2": None,
    "torch": None,
    "tensorflow": None,
    "tf": None,
}

PYODIDE_PRE_INJECTED_VARS = {
    "np": "numpy alias (numpy is already imported)",
    "pd": "pandas alias (pandas is already imported)",
    "plt": "matplotlib.pyplot alias (matplotlib is already imported, plt.show() is a no-op — plots are captured automatically)",
    "query_db": "async function — use: df = await query_db('SELECT ...')",
}

PYODIDE_SYSTEM_CONTEXT = (
    "ENVIRONMENT: Pyodide — Python in a WebAssembly browser sandbox.\n"
    "ALREADY IN SCOPE (never re-import): np=numpy  pd=pandas  plt=matplotlib.pyplot  query_db=async-DB-fn.\n"
    "SAFE IMPORTS: json re math random datetime io base64 os(read-only) mpl_toolkits.mplot3d.\n"
    "MICROPIP PACKAGES (await install before import): scikit-learn scipy seaborn pillow plotly networkx.\n"
    "FORBIDDEN (kernel crash): subprocess threading multiprocessing socket tkinter PyQt5 torch tensorflow cv2 open(local_path) pip-install.\n"
    "\n"
    "MANDATORY RULES:\n"
    "1. Never re-import np/pd/plt.\n"
    "2. Never call plt.show() — plots render automatically.\n"
    "3. Use micropip only: import micropip; await micropip.install('pkg'); import pkg.\n"
    "4. No local file paths. Inline CSV: pd.read_csv(io.StringIO(string)).\n"
    "5. Top-level await is fine. Output raw Python only — no ```python fences, no prose.\n"
    "6. Output the COMPLETE runnable block, never a partial diff.\n"
    "7. Always print() the final result natively (especially for math/data analysis) so the exact numerical answer is visibly outputted.\n"
    "\n"
    "PLOT STYLE (always apply when any figure is produced):\n"
    "- Dark bg: plt.style.use('dark_background') or fig.patch.set_facecolor('#0d1117')+ax.set_facecolor('#161b22').\n"
    "- Colormaps (viridis/plasma/coolwarm) over flat single colors.\n"
    "- xlabel ylabel title(fontsize=14,fontweight='bold'). Legend when >1 series. Colorbar when cmap used.\n"
    "- 3D: pane.fill=False, white labels. End with fig.tight_layout().\n"
)


class IncidentOrchestrator:
    def __init__(self):
        self.db = DBClient()
        self.embedder = embedder_instance
        self.llm = llm_instance
        self.active_file_context = ""
        self.active_file_metadata = None
        self.active_file_type = None
        self.active_filename = None

    def set_file_context(self, text: str, metadata: dict = None, file_type: str = None, filename: str = None):
        """Sets the context for file-based Q&A."""
        self.active_file_context = text
        self.active_file_metadata = metadata
        self.active_file_type = file_type
        self.active_filename = filename

    # =========================================================================
    # LLM HELPERS
    # =========================================================================

    def _get_llm_response(self, system_message: str, user_message: str, tool_used: str = "LLM_Generic", images: list = None) -> Dict[str, Any]:
        """Helper to get a response from the LLM."""
        answer = self.llm.generate(system_message, user_message, images)
        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": f"LLM call for {tool_used} intent.",
            "raw_data": []
        }

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """Formats chat history for LLM context."""
        if not history:
            return "No previous conversation."
        formatted = []
        for msg in history[-5:]:
            role = msg.get('role', 'unknown').title()
            content = msg.get('content', '')
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)

 

    def _sanitize_for_pyodide(self, code: str) -> str:
        """
        Cleans LLM-generated code of known Pyodide incompatibilities.
        Acts as a safety net when the LLM ignores the system prompt constraints.
        """
        lines = code.split('\n')
        sanitized = []
        micropip_installs_added = set()
        needs_micropip_import = False

        for line in lines:
            stripped = line.strip()
            if re.match(r'^plt\.show\(\s*\)$', stripped):
                continue


            _SILENT_DROP_PATTERNS = [
                r'^import\s+numpy\s+as\s+np\s*$',
                r'^import\s+numpy\s*$',
                r'^import\s+pandas\s+as\s+pd\s*$',
                r'^import\s+pandas\s*$',
                r'^import\s+matplotlib\.pyplot\s+as\s+plt\s*$',
                r'^import\s+matplotlib\s*$',
                r'^import\s+matplotlib\.pyplot\s*$',
            ]
            if any(re.match(p, stripped) for p in _SILENT_DROP_PATTERNS):
                continue  


            forbidden_match = re.match(r'^(?:import|from)\s+(\w+)', stripped)
            if forbidden_match:
                module_root = forbidden_match.group(1)
                if module_root in PYODIDE_UNAVAILABLE:
                    sanitized.append(f"# ❌ '{module_root}' is not available in Pyodide (browser sandbox) — line removed")
                    continue

            pip_match = re.match(r'^(?:!pip|pip)\s+install\s+(.+)$', stripped)
            if pip_match:
                package = pip_match.group(1).strip().split()[0]
                if package not in micropip_installs_added:
                    micropip_installs_added.add(package)
                    needs_micropip_import = True
                    sanitized.append(f"await micropip.install('{package}')  # converted from pip install")
                continue

            if re.search(r'\bsubprocess\.(run|call|Popen|check_output)', stripped):
                sanitized.append(f"# ❌ BLOCKED: subprocess calls are not available in Pyodide")
                continue
            if re.search(r'\bos\.system\s*\(', stripped):
                sanitized.append(f"# ❌ BLOCKED: os.system() is not available in Pyodide")
                continue

            sanitized.append(line)

        result = "\n".join(sanitized)

        if needs_micropip_import and "import micropip" not in result:
            result = "import micropip\n" + result

        return result.strip()

    def _detect_packages_needing_install(self, code: str) -> List[str]:
        """
        Scans generated code for imports that need micropip.install() calls
        and checks if the install guard is already present.
        """
        import_pattern = re.compile(r'^(?:import|from)\s+(\w+)', re.MULTILINE)
        found_roots = set(import_pattern.findall(code))

        packages_to_install = []
        for root in found_roots:
           
            real_pkg = IMPORT_ALIAS_MAP.get(root, root)
            if real_pkg is None:
                continue  

            
            if real_pkg in PYODIDE_PRELOADED:
                continue
            if real_pkg in PYODIDE_UNAVAILABLE:
                continue

            # Dynamically ignore standard library packages (Python 3.10+)
            if hasattr(sys, 'stdlib_module_names') and real_pkg in sys.stdlib_module_names:
                continue

            # Fallback for older pythons / common stdlib modules
            if real_pkg in {'sys', 'io', 'os', 're', 'json',
                            'math', 'random', 'datetime', 'base64',
                            'collections', 'itertools', 'functools',
                            'pathlib', 'typing', 'abc', 'copy',
                            'time', 'hashlib', 'struct', 'string',
                            'unicodedata', 'decimal', 'fractions'}:
                continue

            # Check if micropip.install for this package is already in the code
            install_guard = f"micropip.install('{real_pkg}')"
            if install_guard not in code and f"micropip.install(\"{real_pkg}\")" not in code:
                packages_to_install.append((root, real_pkg))

        return packages_to_install

    def _inject_micropip_guards(self, code: str) -> str:
        """
        If the LLM forgot to add micropip.install() calls for non-standard packages,
        this injects them at the top of the code automatically.
        """
        packages_to_install = self._detect_packages_needing_install(code)
        if not packages_to_install:
            return code

        install_block_lines = []
        if "import micropip" not in code:
            install_block_lines.append("import micropip")

        for root, pkg in packages_to_install:
            install_block_lines.append(f"await micropip.install('{pkg}')  # auto-injected for Pyodide compatibility")

        install_block = "\n".join(install_block_lines)
        return install_block + "\n\n" + code

    # =========================================================================
    # INTENT ROUTING
    # =========================================================================

    def _identify_intent(self, user_query: str, notebook_cells: List[str], client_vars: List[str], chat_history: List[Dict[str, str]], use_db_context: bool = True) -> str:
        """
        FAST ROUTING: Uses keywords/regex first, falls back to LLM only if necessary.
        """
        q = user_query.lower().strip()
        print(f"🕵️ ORCHESTRATOR: Analyzing intent for: '{q}'")

        # --- 1. FILE UPLOAD QA (Instant) ---
        if self.active_file_context and any(x in q for x in ["file", "document", "pdf", "summary", "upload", "spreadsheet"]):
            print("⚡ FAST MATCH: Intent identified as FILE_QA via keywords")
            return "FILE_QA"

        # --- 2. EXPLAIN CODE (Instant) ---
        explain_patterns = [
            r"explain", r"describe", r"define", r"meaning",
            r"what does .* code", r"what does .* cell", r"how does .* work"
        ]
        if any(re.search(p, q) for p in explain_patterns):
            print("⚡ FAST MATCH: Intent identified as EXPLAIN_CODE via regex")
            return "EXPLAIN_CODE"

        # --- 3. SQL (Instant) ---
        if use_db_context and any(x in q for x in ["select ", "from ", "count(", "database", "sql", "table", "query data"]):
            print("⚡ FAST MATCH: Intent identified as SQL_QUERY via keywords")
            return "SQL_QUERY"

        # --- 4. GENERATE CODE (Instant) ---
        code_keywords = [
            "plot", "graph", "chart", "code", "python", "dataframe", "pandas",
            "function", "generate", "write", "create a", "make it", "change",
            "update", "add to", "modify", "fix", "install", "micropip",
            "sklearn", "scipy", "seaborn", "plotly",
            "calculate", "compute", "sum of", "find the total", "average",
            "mean", "median", "variance", "total sum"
        ]
        if any(x in q for x in code_keywords):
            print("⚡ FAST MATCH: Intent identified as GENERATE_CODE via keywords")
            return "GENERATE_CODE"

        # --- 5. VECTOR SEARCH (Instant) ---
        if "search" in q or "find similar" in q:
            print("⚡ FAST MATCH: Intent identified as VECTOR_SEARCH via keywords")
            return "VECTOR_SEARCH"

        # --- 5.5 DATA INSIGHTS (Instant) ---
        insight_keywords = ["insight", "figure", "happening in the chart", "analyze the data", "conclusion", "what is happening", "summary of data"]
        if any(x in q for x in insight_keywords) and ("code" not in q and "plot" not in q and "graph" not in q):
            print("⚡ FAST MATCH: Intent identified as GENERAL_QUESTION (Insights) via keywords")
            return "GENERAL_QUESTION"

        # --- 6. SLOW FALLBACK (LLM) ---
        print("🐢 NO MATCH: Falling back to LLM for intent classification...")

        system_msg = (
            "Identify user intent: SQL_QUERY, VECTOR_SEARCH, EXPLAIN_CODE, GENERATE_CODE, FILE_QA, GENERAL_QUESTION. "
            "Output ONLY the category name."
        )

        notebook_context_str = "\n".join([f"Cell {i+1}:\n```python\n{cell}\n```" for i, cell in enumerate(notebook_cells)])
        history_str = self._format_history(chat_history)

        # Give the router context on what resources are actually available
        db_schema = self.db.get_schema() if (getattr(self, "db", None) and use_db_context) else None
        db_tables_list = list(set([row['table_name'] for row in db_schema])) if db_schema else []
        db_connected = True if db_schema else False
        
        active_file = True if self.active_file_context else False
        file_name_context = getattr(self, "active_filename", "Unknown File") if active_file else "None"

        user_msg = f"""User Query: {user_query}
Previous Chat History: {history_str}
Notebook Code: {notebook_context_str if notebook_cells else "None"}

SYSTEM STATE:
- Active File Uploaded: {active_file} | File Name: {file_name_context}
- SQL Database Connected: {db_connected} | Tables: {", ".join(db_tables_list) if db_tables_list else "None"}

CRITICAL RULES:
- If the user's query refers to data found in the "File Name", YOU MUST CHOOSE FILE_QA or GENERATE_CODE (Choose GENERATE_CODE if it requires calculations/pandas, choose FILE_QA if reading/summarizing).
- ONLY choose SQL_QUERY if the user's query specifically targets the SQL "Tables" listed above! Do NOT guess SQL_QUERY for random topics.

Identify the PRIMARY intent (choose only ONE): SQL_QUERY, VECTOR_SEARCH, EXPLAIN_CODE, GENERATE_CODE, FILE_QA, GENERAL_QUESTION"""

        intent_response = self.llm.generate(system_msg, user_msg)
        intent = intent_response.strip().upper().replace(" ", "_").replace(":", "").replace("-", "").split("\n")[0]

        valid_intents = ["SQL_QUERY", "VECTOR_SEARCH", "EXPLAIN_CODE", "GENERATE_CODE", "FILE_QA", "GENERAL_QUESTION"]
        if intent in valid_intents:
            return intent
        return "GENERAL_QUESTION"

    # =========================================================================
    # HANDLERS
    # =========================================================================

    def _handle_sql_query(self, user_query: str) -> Dict[str, Any]:
        """Handles SQL query intent dynamically based on connected database schema."""
        tool_used = "SQL"
        
        # 1. Ensure Database is actually connected and get schema
        schema = self.db.get_schema()
        if not schema:
            return self._get_llm_response(
                "You are a helpful AI assistant.",
                "There is no active SQL database connection to query. Please add a database connection first from the Data Sources tab.",
                tool_used="SQL_Error"
            )

        # 2. Format schema for LLM
        tables = {}
        for row_dic in schema:
            tbl = row_dic['table_name']
            col = row_dic['column_name']
            dtype = row_dic['data_type']
            if tbl not in tables: tables[tbl] = []
            tables[tbl].append(f"{col} ({dtype})")
        
        db_schema_str = "DATABASE SCHEMA AVAILABLE:\n"
        for tbl, cols in tables.items():
            db_schema_str += f"- Table `{tbl}`: {', '.join(cols)}\n"
            
        # 3. Use LLM to generate precisely structured SQL
        sql_system_msg = (
            "You are an expert SQL Developer. Generate ONLY a valid, safe SQL query to answer the user's question, "
            "based STRICTLY on the provided database schema. "
            "Respond ONLY with the raw SQL syntax. Do not wrap it in markdown. Do not include explanation."
        )
        sql_user_msg = f"{db_schema_str}\n\nUser Question: {user_query}\n\nSQL Query:"
        
        sql_query_raw = self.llm.generate(sql_system_msg, sql_user_msg)
        
        # Cleanup any sneaky markdown the LLM might have still added
        sql = re.sub(r'```sql\n?', '', sql_query_raw)
        sql = sql.replace("```", "").strip()

        # 4. Execute the dynamically built database query
        try:
            retrieved_data = self.db.execute_query(sql)
            if not retrieved_data or len(retrieved_data) == 0:
                retrieved_data = [{"Message": "Query successfully executed but returned 0 rows."}]
        except Exception as e:
            retrieved_data = [{"SQL_Execution_Error": str(e)}]
        
        # 5. Bring results back and summarize for user
        llm_context = json.dumps(retrieved_data, indent=2, default=str)
        # Prevent token limit explosion if query returns a million rows
        if len(llm_context) > 12000:
            llm_context = llm_context[:12000] + "\n\n... [RESULTS TOO LARGE, TRUNCATED] ..."

        summary_system_msg = "You are a Data Analyst AI. Answer the user's question clearly based ONLY on the provided SQL query results. If there is an error, just explain the error gracefully."
        summary_user_msg = f"User's original query: {user_query}\n\nSQL query executed: {sql}\n\nSQL Results:\n{llm_context}\n\nPlease summarize these results."
        
        answer = self.llm.generate(summary_system_msg, summary_user_msg)

        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": sql,
            "raw_data": retrieved_data
        }

    def _handle_vector_search(self, user_query: str) -> Dict[str, Any]:
        """Handles vector search intent."""
        tool_used = "Vector Search (RAG)"
        
        # Embed the user's question
        query_vec = self.embedder.get_embedding(user_query)
        
        # Search the universal ChromaDB RAG store!
        session_id = getattr(self, "session_id", "default")
        retrieved_data = vector_store.search(query_vec, n_results=5, session_id=session_id)

        # Give it to the LLM
        llm_context = json.dumps(retrieved_data, indent=2, default=str)
        system_msg = "Answer the user's question using ONLY the provided retrieved context from the workspace knowledge base."
        user_msg = f"Question: '{user_query}'\n\nCONTEXT:\n{llm_context}"
        
        answer = self.llm.generate(system_msg, user_msg)
        return {"answer": answer, "tool_used": tool_used, "trace": "RAG Universal Search", "raw_data": retrieved_data}

    def _handle_explain_code(self, user_query: str, notebook_cells: List[str]) -> Dict[str, Any]:
        """Handles requests to explain notebook code content."""
        tool_used = "Explain_Code"

        if not notebook_cells:
            return self._get_llm_response(
                "You are a helpful AI assistant.",
                "There is no code in the notebook to explain.",
                tool_used="Explain_Code_Error"
            )

        cell_number_match = re.search(r'(?:cell|the)\s+(\d+)', user_query, re.IGNORECASE)
        cell_content = ""
        cell_index_display = -1

        if cell_number_match:
            try:
                cell_index_zero_based = int(cell_number_match.group(1)) - 1
                if 0 <= cell_index_zero_based < len(notebook_cells):
                    cell_content = notebook_cells[cell_index_zero_based]
                    cell_index_display = cell_index_zero_based + 1
                else:
                    return self._get_llm_response(
                        "You are a helpful AI assistant.",
                        f"I cannot find cell number {cell_index_zero_based + 1}. There are only {len(notebook_cells)} cells.",
                        tool_used="Explain_Code_Error"
                    )
            except ValueError:
                pass

        if not cell_content and notebook_cells:
            cell_content = notebook_cells[-1]
            cell_index_display = len(notebook_cells)

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

    def _handle_generate_code(
        self,
        user_query: str,
        notebook_cells: List[str],
        client_vars: List[str],
        is_modification: bool = False,
        original_code: Optional[str] = None,
        active_cell_id: Optional[str] = None,
        images: list = None,
        use_db_context: bool = True
    ) -> Dict[str, Any]:
        """
        Handles requests to generate or modify Python code.
        All generated code is Pyodide-aware via PYODIDE_SYSTEM_CONTEXT injection,
        and then post-processed through the sanitizer and micropip injector.
        """

        # ---- MODIFICATION PATH ----
        if is_modification and original_code:
            tool_used = "Modify_Code"

            system_msg = (
                "You are a code refactoring assistant for a Pyodide (browser-based Python) notebook.\n"
                + PYODIDE_SYSTEM_CONTEXT +
                "\nA user will provide a block of Python code and a request to modify it. "
                "Return the *entire*, complete, modified code block. "
                "DO NOT add explanations, markdown wrappers, or ```python fences. ONLY return the raw, updated code."
            )
            user_msg = f"""Original Code:
{original_code}

Modification Request: "{user_query}"

Return the full modified code block now:"""

            modified_code_raw = self.llm.generate(system_msg, user_msg, images=images)
            modified_code = re.sub(r'```python\n?', '', modified_code_raw)
            modified_code = modified_code.replace("```", "").strip()

            # Post-process: sanitize + inject micropip guards
            modified_code = self._sanitize_for_pyodide(modified_code)
            modified_code = self._inject_micropip_guards(modified_code)

            return {
                "answer": f"I've updated the code in {active_cell_id.replace('-', ' ') if active_cell_id else 'the active cell'} to apply your changes.",
                "tool_used": tool_used,
                "action": "UPDATE_CELL",
                "cell_id": active_cell_id,
                "modified_code": modified_code,
                "trace": "LLM modified existing code block (Pyodide-sanitized).",
                "raw_data": []
            }

        # ---- GENERATION PATH ----
        tool_used = "Generate_Code"

        last_cell_content = notebook_cells[-1] if notebook_cells else ""
        recent_cells = notebook_cells[-3:] if len(notebook_cells) > 3 else notebook_cells
        offset = len(notebook_cells) - len(recent_cells)
        notebook_context_str = "\n".join([
            f"Cell {i+1+offset}:\n```python\n{cell}\n```"
            for i, cell in enumerate(recent_cells)
        ])

        # ---------------------------------------------------------------
        # Query-specific install hints — ONLY for things that genuinely
        # depend on what the user asked for (which micropip package to
        # pre-install). Visualization beauty & Pyodide rules live in
        # PYODIDE_SYSTEM_CONTEXT and are always active.
        # ---------------------------------------------------------------
        hints = []
        q_lower = user_query.lower()

        if any(k in q_lower for k in ["sklearn", "scikit", "machine learning",
                                       "linear regression", "logistic",
                                       "classification", "cluster", "svm", "knn"]):
            hints.append(
                "scikit-learn is needed — add at the top:\n"
                "  import micropip\n"
                "  await micropip.install('scikit-learn')\n"
                "  from sklearn.xxx import ..."
            )

        if any(k in q_lower for k in ["seaborn", "sns"]):
            hints.append(
                "seaborn is needed — add at the top:\n"
                "  import micropip\n"
                "  await micropip.install('seaborn')\n"
                "  import seaborn as sns"
            )

        if any(k in q_lower for k in ["plotly", "interactive", "interactive chart"]):
            hints.append(
                "plotly is needed — add at the top:\n"
                "  import micropip\n"
                "  await micropip.install('plotly')\n"
                "  import plotly.express as px"
            )

        if any(k in q_lower for k in ["scipy", "statistics", "stats", "signal"]):
            hints.append(
                "scipy is needed — add at the top:\n"
                "  import micropip\n"
                "  await micropip.install('scipy')"
            )

        if any(k in q_lower for k in ["read_csv", "load csv", "parse csv",
                                       "load data", "load file", "inline data"]):
            hints.append(
                "No local filesystem in Pyodide. "
                "Parse inline data with: pd.read_csv(io.StringIO(your_string_variable))"
            )

        hint_str = "\n- ".join(hints)
        specific_instructions = f"\n### QUERY-SPECIFIC NOTES:\n- {hint_str}" if hints else ""

        system_msg = (
            "You are an expert Python programmer generating code for a Pyodide notebook in the browser.\n"
            + PYODIDE_SYSTEM_CONTEXT
            + specific_instructions
        )

        # 1. Grab Database Schema if connected:
        db_schema_str = ""
        if use_db_context:
            schema = self.db.get_schema()
            if schema:
                # Group by table
                tables = {}
                for row_dic in schema:
                    tbl = row_dic['table_name']
                    col = row_dic['column_name']
                    dtype = row_dic['data_type']
                    if tbl not in tables: tables[tbl] = []
                    tables[tbl].append(f"{col} ({dtype})")
                
                db_schema_str = "\nDATABASE SCHEMA AVAILABLE VIA `query_db()`:\n"
                for tbl, cols in tables.items():
                    db_schema_str += f"- Table `{tbl}`: {', '.join(cols)}\n"

        # 2. Grab Uploaded File Header/Context if present:
        file_context_str = ""
        if self.active_file_context:
            # Provide first 1000 characters to give header/structure idea without overloading
            file_context_str = (
                "\nAN UPLOADED FILE IS IN THE SYSTEM MEMORY.\n"
                "Here is the beginning of the file (headers/content):\n"
                f"{self.active_file_context[:1000]}\n"
            )

        user_msg = f"""User Request: {user_query}

Current Code in Active Cell (Modify THIS code if the request is about changes):
```python
{last_cell_content}
```

Recent Notebook Context (for variable awareness):
{notebook_context_str}

Active Variables already in scope: {json.dumps(client_vars) if client_vars else "[]"}
{db_schema_str}{file_context_str}
Generate the COMPLETE Pyodide-compatible Python code now (raw code only, no markdown):
"""

        generated_code_raw = self.llm.generate(system_msg, user_msg, images=images)

        # Extract code from markdown fences if LLM ignores instructions
        code_match = re.search(r'```python\n(.*?)```', generated_code_raw, re.DOTALL)
        if code_match:
            generated_code = code_match.group(1).strip()
        else:
            generated_code = generated_code_raw.replace("```", "").strip()

        # Post-process: sanitize + inject micropip guards
        generated_code = self._sanitize_for_pyodide(generated_code)
        generated_code = self._inject_micropip_guards(generated_code)

        answer = f"Here is the updated code:\n```python\n{generated_code}\n```"

        return {
            "answer": answer,
            "tool_used": tool_used,
            "trace": "LLM generated Pyodide-compatible Python code.",
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

        # Safely cap the file contents to avoid blowing up the OpenAI 30K/128K token limit 
        # (roughly 12000 chars should be safely under limit along with history)
        preview_limit = 12000
        file_content_preview = self.active_file_context[:preview_limit]
        if len(self.active_file_context) > preview_limit:
            file_content_preview += "\n\n... [FILE TRUNCATED FOR LENGTH] ..."

        rag_context = ""
        # Append metadata if it was a structured file (CSV/JSON/Excel)
        if self.active_file_type == 'structured' and self.active_file_metadata:
            meta_str = json.dumps(self.active_file_metadata, indent=2)
            file_content_preview = f"--- DATABASE/FILE STRUCTURE METADATA ---\n{meta_str}\n\n--- FILE DATA PREVIEW ---\n{file_content_preview}"
        
        # If it's an unstructured file (PDF/Docx), do a quick RAG search to pull specific snippets!
        elif self.active_file_type == 'unstructured':
            try:
                session_id = getattr(self, "session_id", "default")
                query_vec = self.embedder.get_embedding(user_query)
                from app.db.vector_store import vector_store
                retrieved_data = vector_store.search(query_vec, n_results=4, session_id=session_id)
                if retrieved_data and len(retrieved_data) > 0:
                    rag_context = f"\n\n--- RAG SEARCH HIGHLIGHTS (Specific Excerpts) ---\n{json.dumps(retrieved_data, indent=2, default=str)}"
            except Exception as e:
                print(f"FILE_QA RAG Supplemental fetch error: {e}")

        user_msg = f"""User Question: {user_query}

File Content/Preview (Top lines):
{file_content_preview}{rag_context}
"""
        return self._get_llm_response(system_msg, user_msg, tool_used)

    def _handle_general_question(
        self,
        user_query: str,
        notebook_cells: List[str],
        client_vars: List[str],
        chat_history: List[Dict[str, str]],
        images: list = None,
        use_db_context: bool = True
    ) -> Dict[str, Any]:
        """Handles general questions using the LLM."""
        tool_used = "General_Question"

        notebook_context_str = "\n".join([f"Cell {i+1}:\n```python\n{cell}\n```" for i, cell in enumerate(notebook_cells)])
        history_str = self._format_history(chat_history)

        # 2. 👈 NEW: Grab the active uploaded dataset/document if it exists
        # We limit to ~4000 chars to avoid blowing up the token limit, but it gives enough context for the AI
        dataset_context = ""
        if self.active_file_context:
            dataset_context = f"\n\n--- UPLOADED DATASET / FILE CONTEXT ---\n{self.active_file_context[:4000]}\n---------------------------------------"

        # 3. 👈 NEW: Dynamic System Prompt depending on if an image is attached
        if images:
            system_msg = (
                "You are an expert Data Analyst and Vision AI. The user has attached an image (e.g., a chart, graph, or diagram). "
                "Analyze the image deeply. Cross-reference what you see in the image with the 'Uploaded Dataset' and 'Notebook Cells' provided below. "
                "Explain the trends, point out specific data points from the dataset that match the image, and answer the user's question accurately."
            )
        else:
            system_msg = (
                "You are AivNotebook Buddy, a highly intelligent data analysis and coding assistant embedded within a Pyodide software notebook. "
                "Answer the user's question directly, concisely, and practically, making use of the provided 'Notebook Cells', 'Active Variables', and 'Uploaded Dataset'. "
                "If the user asks for insights, figures, or analysis of data/images, PROVIDE THE ANSWER DIRECTLY IN NATURAL LANGUAGE. "
                "DO NOT generate Python code unless the user explicitly asks to draw a chart, plot a graph, or write a script. "
                "CONSIDER PREVIOUS CHAT HISTORY for context."
            )

        # 4. Construct the final user message
        user_msg = f"""User Question: {user_query}

Previous Chat History:
{history_str}

Notebook Cells (contains recent code and DB outputs):
{notebook_context_str if notebook_cells else "No existing notebook cells."}

Active Variables: {json.dumps(client_vars) if client_vars else "No active variables."}
{dataset_context}
"""
        return self._get_llm_response(system_msg, user_msg, tool_used, images=images)

    # =========================================================================
    # MAIN ROUTER
    # =========================================================================

    def route_and_execute(
        self,
        user_query: str,
        notebook_cells: List[str],
        client_vars: List[str],
        chat_history: List[Dict[str, str]] = [],
        images: list = None,
        *,
        is_modification: bool = False,
        original_code: Optional[str] = None,
        active_cell_id: Optional[str] = None,
        use_db_context: bool = True
    ) -> Dict[str, Any]:
        """
        Routes the user query to the appropriate handler based on identified intent.
        """
        if is_modification:
            intent = "GENERATE_CODE"
        else:
            intent = self._identify_intent(user_query, notebook_cells, client_vars, chat_history, use_db_context=use_db_context)

        print(f"🎯 ORCHESTRATOR: Routing to intent → {intent}")

        if intent == "SQL_QUERY":
            return self._handle_sql_query(user_query)
        elif intent == "VECTOR_SEARCH":
            return self._handle_vector_search(user_query)
        elif intent == "EXPLAIN_CODE":
            return self._handle_explain_code(user_query, notebook_cells)
        elif intent == "GENERATE_CODE":
            return self._handle_generate_code(
                user_query, notebook_cells, client_vars,
                is_modification, original_code, active_cell_id, images=images, use_db_context=use_db_context
            )
        elif intent == "FILE_QA":
            return self._handle_file_qa(user_query)
        else:
            return self._handle_general_question(user_query, notebook_cells, client_vars, chat_history, images=images, use_db_context=use_db_context)