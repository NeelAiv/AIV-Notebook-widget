from app.db.db_client import DBClient
from app.core.embedder import embedder_instance
from app.core.remote_llm import llm_instance
from app.db.vector_store import vector_store
from app.utils.logger import info, error, warning
from sqlalchemy import text
import json
import re
import sys
from typing import List, Dict, Any, Optional



PYODIDE_PRELOADED = {"numpy", "pandas", "matplotlib", "micropip", "pyodide"}

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
    "ALREADY IN SCOPE (never re-import): np=numpy  pd=pandas  plt=matplotlib.pyplot  query_db=async-DB-fn  micropip.\n"
    "SAFE IMPORTS: json re math random datetime io base64 os(read-only) mpl_toolkits.mplot3d.\n"
    "MICROPIP PACKAGES (await install before import): scikit-learn scipy seaborn pillow plotly networkx.\n"
    "FORBIDDEN (will crash kernel): subprocess threading multiprocessing socket tkinter PyQt5 torch tensorflow cv2 open(local_path) pip-install.\n"
    "\n"
    "MANDATORY PYODIDE COMPATIBILITY RULES:\n"
    "1. NEVER import micropip - it's already available in scope\n"
    "2. NEVER use f-strings with formatting specifiers ({:,}, {:.2f}, etc.) - they fail in Pyodide\n"
    "3. NEVER use fig.show() or plt.show() - just return the figure object\n"
    "4. NEVER use pd.read_excel() - use pd.read_csv(io.StringIO(dataset_string)) instead\n"
    "5. NEVER create hardcoded sample data - always use await query_db() for real data\n"
    "6. ALWAYS use simple string concatenation: print('text: ' + str(value)) NOT print(f'text: {value}')\n"
    "7. CRITICAL: The LAST LINE of code MUST be OUTSIDE all conditionals (if/else/for/while)\n"
    "8. ALWAYS use await for async operations like query_db() and micropip.install()\n"
    "\n"
    "MANDATORY RULES:\n"
    "1. You MUST ALWAYS communicate and write code strictly in English.\n"
    "2. If you need to analyze data, YOU MUST USE THE 'generate_code' TOOL. Never provide code as a direct answer.\n"
    "3. DATA VISIBILITY: You cannot read local files. Any CSV/Excel data is accessible via `dataset_string` (already in CSV format).\n"
    "4. USE io.StringIO: To load data, ALWAYS use: import io; df = pd.read_csv(io.StringIO(dataset_string))\n"
    "5. CRITICAL: Even if the original file was Excel (.xlsx), use pd.read_csv() NOT pd.read_excel()! The data is pre-converted to CSV.\n"
    "6. NO FENCES: Within the 'generate_code' tool, provide RAW Python code. Do NOT wrap it in backticks.\n"
    "7. RICH OUTPUT: Ensure the final expression in your code is the DataFrame or Plot to render it beautifully.\n"
    "\n"
    "DATABASE RULES (CRITICAL):\n"
    "- When database schema is available, ALWAYS use await query_db('SELECT...') to fetch REAL data\n"
    "- NEVER create hardcoded sample data\n"
    "- Example: df = await query_db('SELECT product_id, current_stock FROM inventory')\n"
    "\n"
    "OUTPUT FORMATTING RULES (PYODIDE-SAFE):\n"
    "- CRITICAL: NEVER use f-strings with formatting specifiers - they fail in Pyodide!\n"
    "- For single values: Use ONLY simple string concatenation with +\n"
    "- CORRECT: print('Total: ' + str(value))\n"
    "- WRONG: print(f'Total: {value:,}')\n"
    "- For DataFrames: Just write 'df' as the last line\n"
    "\n"
    "INTERACTIVE PLOTTING RULES (PLOTLY - ALWAYS USE go.Figure):\n"
    "- ALWAYS use Plotly for ALL charts\n"
    "- Use go.Figure pattern (NOT px.express) - it renders reliably in Pyodide\n"
    "- CRITICAL: Use go.Scatter, go.Bar, go.Histogram, etc. for chart types\n"
    "- CRITICAL: Return fig (NOT fig.show())\n"
    "- CRITICAL: NEVER import micropip - it's already available\n"
    "- CRITICAL: End code with 'fig' on its own line OUTSIDE all conditionals - this is what displays the chart\n"
    "\n"
    "PLOTLY TEMPLATE (COPY THIS PATTERN - TESTED AND WORKING):\n"
    "import plotly.graph_objects as go\n"
    "df = await query_db('SELECT ...')\n"
    "fig = go.Figure(\n"
    "    data=go.Scatter(\n"
    "        x=df['col1'],\n"
    "        y=df['col2'],\n"
    "        mode='lines+markers',\n"
    "        name='Data',\n"
    "        line=dict(color='#667eea', width=2),\n"
    "        marker=dict(size=6)\n"
    "    )\n"
    ")\n"
    "fig.update_layout(title='Title', xaxis_title='X', yaxis_title='Y', hovermode='x unified', template='plotly_white', height=400)\n"
    "fig  # <-- OUTSIDE all conditionals\n"
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


    def _format_history(self, history: List[Dict[str, str]], scrub_db: bool = False, scrub_rag: bool = False) -> str:
        """Formats recent chat turns into a string for LLM context.
        
        scrub_db=True  — strips SQL/schema content when DB context is off
        scrub_rag=True — strips RAG/document content when RAG context is off
        """
        if not history:
            return "No previous conversation."
        formatted = []
        for msg in history[-5:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            if scrub_db:
                import re
                content = re.sub(r'```(?:sql|python)[\s\S]*?```', '[code removed — DB context was on]', content)
                content = re.sub(r'await query_db\([^)]*\)', '[query removed]', content)
                content = re.sub(r'(?:Table|Column|Schema|SELECT|FROM|WHERE|GROUP BY|ORDER BY)[^\n]{0,200}', '', content, flags=re.IGNORECASE)
                content = content.strip()
            if scrub_rag:
                import re
                # Remove RAG chunk references and document-backed answers
                content = re.sub(r'\[[\w\s./]+\]:\s*.{0,300}', '[document context removed — RAG was on]', content)
                content = re.sub(r'(?:according to|based on|from the document|the document states)[^\n]{0,300}', '', content, flags=re.IGNORECASE)
                content = content.strip()
            if len(content) > 500:
                content = content[:500] + "..."
            if content:
                formatted.append(f"{role}: {content}")
        return "\n".join(formatted) if formatted else "No previous conversation."

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
            if re.match(r'^fig\.show\(\s*\)$', stripped):
                continue  # fig.show() doesn't work in Pyodide — just use 'fig' as last line


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

    def _ensure_final_output(self, code: str) -> str:
        """
        Ensures code ends with a result object for display in the notebook.
        If code creates a figure or dataframe but doesn't return it, adds the return statement.
        """
        lines = code.strip().split('\n')
        if not lines:
            return code
        
        last_line = lines[-1].strip()
        
        # If last line is already a result object, return as-is
        if last_line in ('fig', 'df', 'result', 'data', 'output'):
            return code
        
        # If last line is a comment or print statement, check if we need to add result
        if last_line.startswith('#') or last_line.startswith('print('):
            # Check if code creates a figure
            code_lower = code.lower()
            if 'fig = px.' in code_lower or 'fig = go.' in code_lower or 'fig = plt.' in code_lower:
                # Add 'fig' as final line
                return code + '\nfig'
            elif 'df = ' in code_lower or 'df=' in code_lower:
                # Add 'df' as final line
                return code + '\ndf'
        
        # If code ends with a variable assignment or function call, add the variable
        if '=' in last_line and not last_line.endswith(')'):
            # Extract variable name from assignment
            var_name = last_line.split('=')[0].strip()
            if var_name and not var_name.startswith('#'):
                return code + '\n' + var_name
        
        return code

    def _get_db_type(self) -> str:
        """Detect the database type from the connection URL."""
        if not getattr(self, "db", None) or not self.db.engine:
            return "sqlite"
        
        db_url = str(self.db.engine.url).lower()
        if 'mysql' in db_url:
            return "mysql"
        elif 'postgres' in db_url:
            return "postgres"
        elif 'sqlite' in db_url:
            return "sqlite"
        return "sqlite"

    def _get_matching_tables(self, user_query: str) -> list:
        """Find tables that match the user's query using fuzzy matching."""
        import re
        
        actual_tables = []
        if getattr(self, "db", None) and self.db.engine:
            try:
                schema = self.db.get_schema()
                actual_tables = list(set([row['table_name'] for row in schema]))
            except:
                pass
        
        if not actual_tables:
            return []
        
        user_query_lower = user_query.lower()
        matches = []
        
        # Exact matches first
        for table in actual_tables:
            if table.lower() in user_query_lower:
                matches.append(table)
        
        # Fuzzy matches (substring matching)
        if not matches:
            words = re.findall(r'\b\w+\b', user_query_lower)
            for table in actual_tables:
                for word in words:
                    if len(word) > 3 and word in table.lower():
                        matches.append(table)
                        break
        
        return matches

    def _get_columns_query(self, table_name: str) -> str:
        """Generate the correct query to list columns for the current database type."""
        db_type = self._get_db_type()
        
        if db_type == "postgres":
            return f"""SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position;"""
        elif db_type == "mysql":
            return f"""SELECT COLUMN_NAME as column_name, COLUMN_TYPE as data_type FROM information_schema.COLUMNS WHERE TABLE_NAME = '{table_name}' AND TABLE_SCHEMA = DATABASE() ORDER BY ORDINAL_POSITION;"""
        else:  # sqlite
            return f"""PRAGMA table_info({table_name});"""

    def _fix_table_names(self, sql_query: str) -> str:
        """Replace any wrong/partial table names in a SQL query with the actual table names from the schema."""
        actual_tables = []
        if getattr(self, "db", None) and self.db.engine:
            try:
                schema = self.db.get_schema()
                actual_tables = list(set([row['table_name'] for row in schema]))
            except:
                pass

        if not actual_tables:
            return sql_query

        # Find all table-like tokens after FROM/JOIN/INTO/UPDATE
        token_pattern = re.compile(
            r'\b(FROM|JOIN|INTO|UPDATE)\s+([`"\']?)(\w+)\2',
            re.IGNORECASE
        )

        def replace_token(m):
            keyword = m.group(1)
            quote = m.group(2)
            token = m.group(3)
            token_lower = token.lower()

            # Exact match — already correct
            if token in actual_tables:
                return m.group(0)

            # Case-insensitive exact match
            for t in actual_tables:
                if t.lower() == token_lower:
                    return f"{keyword} {quote}{t}{quote}"

            # Fuzzy: token is a prefix/substring of an actual table name
            for t in actual_tables:
                if len(token) > 3 and token_lower in t.lower():
                    info(f"Table name fix: '{token}' → '{t}'")
                    return f"{keyword} {quote}{t}{quote}"

            return m.group(0)  # no match found, leave as-is

        return token_pattern.sub(replace_token, sql_query)

    def _fix_column_query(self, sql_query: str, user_query: str) -> str:
        """Fix column listing queries to use the correct database syntax and table name."""
        import re
        
        user_query_lower = user_query.lower()
        
        # Check if this is a column listing request
        if not any(word in user_query_lower for word in ['column', 'columns', 'field', 'fields', 'schema']):
            return sql_query
        
        # Get actual table names from the database schema
        actual_tables = []
        if getattr(self, "db", None) and self.db.engine:
            try:
                schema = self.db.get_schema()
                actual_tables = list(set([row['table_name'] for row in schema]))
            except:
                pass
        
        # Try to find the table name in the user query by matching against actual tables
        table_name = None
        
        # First, try exact word matching against actual tables
        for actual_table in actual_tables:
            if actual_table.lower() in user_query_lower:
                table_name = actual_table
                break
        
        # If no exact match, try fuzzy matching (e.g., "cyber" might match "cyber_secuitry")
        if not table_name:
            for actual_table in actual_tables:
                # Check if any word in the user query is a substring of the table name
                words = re.findall(r'\b\w+\b', user_query_lower)
                for word in words:
                    if len(word) > 3 and word in actual_table.lower():
                        table_name = actual_table
                        break
                if table_name:
                    break
        
        # If still no match, try extracting from the query itself
        if not table_name:
            table_match = re.search(r'(?:in|from)\s+(?:the\s+)?(?:table\s+)?[`"\']?(\w+)[`"\']?', user_query, re.IGNORECASE)
            if table_match:
                table_name = table_match.group(1)
        
        if not table_name:
            return sql_query
        
        # Generate the correct query for the current database
        correct_query = self._get_columns_query(table_name)
        info(f"Fixed column query: '{table_name}' → {self._get_db_type()} syntax")
        return correct_query

    # =========================================================================
    # VAGUE QUERY DETECTION
    # =========================================================================
    def _is_vague_query(self, user_query: str) -> bool:
        """Detect if a query is too vague to answer without clarification."""
        vague_patterns = [
            r'^show\s+me\s+\w+$',           # "show me sales"
            r'^give\s+me\s+\w+$',           # "give me data"
            r'^get\s+\w+$',                  # "get products"
            r'^list\s+\w+$',                 # "list orders"
            r'^analyze\s+\w+$',              # "analyze data"
        ]
        q = user_query.strip().lower()
        # Only flag as vague if very short AND matches pattern AND no table/column context
        if len(q.split()) <= 4:
            for pattern in vague_patterns:
                if re.match(pattern, q):
                    return True
        return False

    def _is_conversational_followup(self, user_query: str, chat_history: list) -> bool:
        """
        Detect if the message is a conversational follow-up about existing output/code
        that should be answered directly without generating new code.
        """
        q = user_query.strip().lower()

        # Must be short — not a new data request
        if len(q.split()) > 15:
            return False

        # Must have prior conversation context
        if not chat_history or len(chat_history) < 2:
            return False

        # Starts with question words about existing state
        followup_starters = [
            "is the", "is this", "is that", "is it",
            "are the", "are these", "are they",
            "does the", "does this", "did the", "did it",
            "why did", "why is", "why are", "why no", "why not", "why doesn't", "why don't",
            "what does this", "what is this", "what does that",
            "what is the name", "what is my", "what are my",
            "is the output", "is it showing", "is this showing",
            "is this correct", "is that correct", "is this right",
            "still correct", "still showing", "still working",
            "looks correct", "looks right", "looks good",
        ]
        for starter in followup_starters:
            if q.startswith(starter):
                return True

        # Short question ending with ? that doesn't contain action words
        action_words = ["create", "make", "generate", "show me", "give me",
                        "plot", "chart", "fetch", "get", "list", "run", "execute",
                        "find", "calculate", "compute", "count", "sum", "average"]
        if q.endswith("?") and len(q.split()) <= 10:
            if not any(w in q for w in action_words):
                return True

        return False

    def _validate_and_fix_sql(self, sql_query: str) -> str:
        """Validate SQL using EXPLAIN and auto-fix with LLM if invalid."""
        try:
            if getattr(self, "db", None) and self.db.engine:
                with self.db.engine.connect() as conn:
                    db_url = str(self.db.engine.url).lower()
                    if 'sqlite' in db_url:
                        conn.execute(text(f"EXPLAIN QUERY PLAN {sql_query}"))
                    else:
                        conn.execute(text(f"EXPLAIN {sql_query}"))
        except Exception as explain_err:
            # SQL is invalid — ask LLM to fix it
            fix_prompt = (
                f"The following SQL query has an error: {explain_err}\n\n"
                f"Original SQL:\n{sql_query}\n\n"
                f"Fix the SQL query. Output ONLY the corrected raw SQL, nothing else."
            )
            fix_resp = self.llm.generate("You are a SQL expert. Output only raw SQL.", fix_prompt)
            fixed = fix_resp if isinstance(fix_resp, str) else fix_resp.get("content", "")
            fixed = re.sub(r"```(?:sql)?|```", "", fixed).strip()
            if fixed.upper().startswith("SELECT") or fixed.upper().startswith("WITH"):
                info(f"SQL auto-fixed by LLM")
                return fixed
        return sql_query

    # =========================================================================
    # SINGLE TOOL-SELECTION AGENT (Replaces all previous intent handlers)
    # =========================================================================
    def route_and_execute(
        self,
        user_query: str,
        notebook_cells: List[str],
        client_vars: List[str],
        chat_history: List[Dict[str, str]] =[],
        images: list = None,
        *,
        is_modification: bool = False,
        original_code: Optional[str] = None,
        active_cell_id: Optional[str] = None,
        use_db_context: bool = True,
        use_rag_context: bool = False
    ) -> Dict[str, Any]:
        info(f"Agent received request: '{user_query[:50]}...'")

        # Check for vague queries and ask for clarification
        if self._is_vague_query(user_query) and use_db_context and getattr(self, "db", None) and self.db.engine:
            schema = self.db.get_schema()
            tables = list(set(row['table_name'] for row in schema))
            table_list = ", ".join(tables[:10])
            return {
                "answer": f"Could you be more specific? For example:\n- Which table or metric are you interested in? (Available: {table_list})\n- What time period or filters should I apply?\n- What format do you want — a table, chart, or summary?",
                "tool_used": "Direct Answer",
                "trace": "Vague query — asked for clarification.",
                "raw_data": []
            }

        # Check for conversational follow-ups — answer directly without tools
        if self._is_conversational_followup(user_query, chat_history):
            # Build a minimal context with recent cells for the LLM to reference
            recent_code = ""
            if notebook_cells:
                recent = [c for c in notebook_cells[-3:] if isinstance(c, dict) and c.get('code', '').strip()]
                if recent:
                    recent_code = "\n\nRECENT NOTEBOOK CELLS:\n" + "\n".join(
                        f"Cell [{c['id']}]:\n```python\n{c['code'][:500]}\n```" for c in recent
                    )
            followup_system = (
                "You are a Data Analyst Agent. Answer the user's question directly in plain text. "
                "Do NOT generate any code. Look at the recent notebook cells provided and answer "
                "factually — e.g. if asked 'is the chart showing 10 items?', check if LIMIT 10 "
                "is in the code and answer yes/no with a brief explanation."
            )
            followup_user = (
                f"Previous context:\n{self._format_history(chat_history)}"
                f"{recent_code}\n\n"
                f"User question: {user_query}"
            )
            resp = self.llm.generate(followup_system, followup_user)
            answer = resp if isinstance(resp, str) else resp.get("content", "")
            return {
                "answer": answer,
                "tool_used": "Direct Answer",
                "trace": "Conversational follow-up answered directly.",
                "raw_data": []
            }

        # Image + datasource analysis
        if images and use_db_context and getattr(self, "db", None) and self.db.engine:
            img_keywords = ['this chart', 'this image', 'this graph', 'this visualization', 'reproduce', 'recreate',
                            'similar to', 'like this', 'same as', 'based on this', 'from this']
            if any(kw in user_query.lower() for kw in img_keywords) or (images and len(user_query.split()) < 10):
                # Build schema context
                schema = self.db.get_schema()
                tables = {}
                for row in schema:
                    tables.setdefault(row['table_name'], []).append(f"{row['column_name']} ({row['data_type']})")
                schema_str = "\n".join([f"- Table `{t}`: {', '.join(c)}" for t, c in tables.items()])
                return self._analyze_image_with_schema(user_query, images, schema_str)

        # 1. Define Standard Tools — only include search_knowledge when RAG is ON
        tools =[
            {
                "type": "function",
                "function": {
                    "name": "run_sql",
                    "description": "Execute a SQL query against the connected database to retrieve raw data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The valid raw SQL query to run"},
                            "explanation": {"type": "string", "description": "Summary of what the query does"}
                        },
                        "required": ["query", "explanation"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_code",
                    "description": "Generate Pyodide-compatible Python code to run in the notebook.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "python_code": {"type": "string", "description": "The entirely runnable Python code block"},
                            "explanation": {"type": "string", "description": "Explanation of code and proposed next steps"}
                        },
                        "required":["python_code", "explanation"]
                    }
                }
            },
        ]

        # Only expose search_knowledge tool when RAG toggle is ON
        if use_rag_context:
            tools.append({
                "type": "function",
                "function": {
                    "name": "search_knowledge",
                    "description": "Search uploaded documents (PDFs, reports, policies, data dictionaries) for definitions, context, or explanations. Use this when the user asks about what something means, policy details, or wants document-backed context alongside data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "search_query": {"type": "string", "description": "The specific keyword or question to look up in documents"}
                        },
                        "required": ["search_query"]
                    }
                }
            })

        # 2. Build Universal Context
        context_parts =[]
        
        if use_db_context and getattr(self, "db", None) and self.db.engine:
            schema = self.db.get_schema()
            if schema:
                tables = {}
                for row in schema:
                    tables.setdefault(row['table_name'], []).append(f"{row['column_name']} ({row['data_type']})")
                # Smart schema injection — score tables by relevance to user query
                query_words = set(re.findall(r'\b\w{3,}\b', user_query.lower()))
                table_scores = {}
                for t, cols in tables.items():
                    score = 0
                    # Table name match
                    if any(w in t.lower() for w in query_words): score += 3
                    # Column name match
                    for col_str in cols:
                        col_name = col_str.split(' ')[0].lower()
                        if any(w in col_name for w in query_words): score += 1
                    table_scores[t] = score

                # Sort by relevance
                sorted_tables = sorted(tables.keys(), key=lambda t: table_scores[t], reverse=True)
                top_tables = sorted_tables[:4]  # top 4 most relevant get full detail
                other_tables = sorted_tables[4:]

                schema_lines = []
                for t in top_tables:
                    schema_lines.append(f"- Table `{t}` (columns: {', '.join(tables[t])})")
                if other_tables:
                    schema_lines.append(f"- Other tables (no columns shown): {', '.join(f'`{t}`' for t in other_tables)}")

                context_parts.append("SQL DATABASE SCHEMA (most relevant tables first):\n" + "\n".join(schema_lines))

                # Add connection name so AI can answer "what is my datasource"
                from app.db.config_manager import get_active_name
                active_conn_name = get_active_name() or "unknown"
                context_parts.append(f"\nACTIVE DATASOURCE NAME: `{active_conn_name}`")

                # Add exact table names for matching
                table_names = list(tables.keys())
                context_parts.append(f"\nEXACT TABLE NAMES (use these exact names in queries):\n" + ", ".join([f"`{t}`" for t in table_names]))
                
                # Detect database type and add specific SQL rules
                db_url = str(self.db.engine.url)
                if 'mysql' in db_url.lower():
                    context_parts.append(
                        "\n⚠️ DATABASE: MySQL\n"
                        "MYSQL-SPECIFIC SQL RULES:\n"
                        "- Use DATE_FORMAT() instead of DATE_TRUNC(): DATE_FORMAT(date_col, '%Y-%m-01')\n"
                        "- Use DATE_ADD() for date arithmetic: DATE_ADD(date_col, INTERVAL 1 MONTH)\n"
                        "- Use YEAR(), MONTH(), DAY() for date parts\n"
                        "- Use DATE() to convert timestamps to dates\n"
                        "- Use CAST(col AS CHAR) for type conversion\n"
                        "- Use CONCAT() for string concatenation\n"
                        "- To list all tables: SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()\n"
                    )
                elif 'postgres' in db_url.lower():
                    context_parts.append(
                        "\n⚠️ DATABASE: PostgreSQL\n"
                        "POSTGRESQL-SPECIFIC SQL RULES:\n"
                        "- Use DATE_TRUNC('month', date_col) for date truncation\n"
                        "- Use EXTRACT(YEAR FROM date_col) for date parts\n"
                        "- Use || for string concatenation\n"
                        "- To list all tables: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'\n"
                    )
                elif 'sqlite' in db_url.lower():
                    context_parts.append(
                        "\n⚠️ DATABASE: SQLite\n"
                        "SQLITE-SPECIFIC SQL RULES:\n"
                        "- Use strftime('%Y-%m-01', date_col) for date formatting\n"
                        "- Use date(date_col) to convert to date\n"
                        "- Use || for string concatenation\n"
                        "- To list all tables: SELECT name FROM sqlite_master WHERE type='table'\n"
                    )
                
                context_parts.append("\nNOTE: You can use `run_sql` tool for direct SQL queries, OR use `generate_code` with `await query_db('SELECT ...')` for Python analysis.")

                # Inject inferred JOIN hints
                join_hints = self._infer_joins()
                if join_hints:
                    context_parts.append(join_hints)

        if self.active_file_context:
            dataset_preview = self.active_file_context[:1500]
            filename = getattr(self, "active_filename", "uploaded_data")
            file_context_str = f"--- UPLOADED FILE CONTEXT ---\nFilename: {filename}\n"
            
            if self.active_file_type == 'structured':
                file_context_str += (
                    "Type: Structured Data (CSV/Excel converted to CSV format)\n"
                    "WORKFLOW: The file content has been pre-processed and is available as `dataset_string` in CSV format.\n"
                    "You MUST use the `generate_code` tool to write Python code to load it.\n"
                    "IMPORTANT: Use pd.read_csv(io.StringIO(dataset_string)) - NOT pd.read_excel()!\n"
                    "The data is already in CSV format even if the original file was Excel.\n"
                    "Example code:\n"
                    "```python\n"
                    "import io\n"
                    "import pandas as pd\n"
                    "df = pd.read_csv(io.StringIO(dataset_string))\n"
                    "df.head()\n"
                    "```\n"
                )
            elif self.active_file_type == 'unstructured':
                file_context_str += "Type: Unstructured Text\nFor deep lookups, use the `search_knowledge` tool.\n"

            file_context_str += f"DATA PREVIEW:\n{dataset_preview}\n... [TRUNCATED]\n-----------------------------\n"
            context_parts.append(file_context_str)

        if notebook_cells:
            # Handle both old format (list of strings) and new format (list of dicts)
            if notebook_cells and isinstance(notebook_cells[0], dict):
                # New format with metadata
                recent_cells = notebook_cells[-5:]  # Show last 5 cells
                cell_context = []
                active_cell_id = None
                
                for cell_data in recent_cells:
                    cell_id = cell_data.get('id', 'unknown')
                    cell_type = cell_data.get('type', 'code')
                    code = cell_data.get('code', '').strip()
                    output = cell_data.get('output', '').strip()
                    is_active = cell_data.get('is_active', False)
                    
                    if is_active:
                        active_cell_id = cell_id
                    
                    if not code:
                        continue  # Skip empty cells
                    
                    cell_str = f"Cell [{cell_id}] ({cell_type}):\n```python\n{code}\n```"
                    if output:
                        cell_str += f"\nOutput:\n{output[:300]}"  # Limit output
                    cell_context.append(cell_str)
                
                if cell_context:
                    context_parts.append("RECENT NOTEBOOK CELLS:\n" + "\n\n".join(cell_context))
                
                if active_cell_id:
                    context_parts.append(f"\nACTIVE CELL: {active_cell_id} (user may refer to this as 'this cell' or 'current cell')")
            else:
                # Old format (backward compatibility)
                recent_cells = notebook_cells[-3:]
                offset = len(notebook_cells) - len(recent_cells)
                context_parts.append("RECENT NOTEBOOK CELLS:\n" + "\n".join([
                    f"Cell {i+1+offset}:\n```python\n{cell}\n```" for i, cell in enumerate(recent_cells)
                ]))

        if client_vars: context_parts.append(f"ACTIVE VARIABLES: {json.dumps(client_vars[:15])}")

        # RAG context: if toggle is ON, pre-fetch relevant chunks and inject into context
        if use_rag_context:
            try:
                query_vec = self.embedder.get_embedding(user_query)
                session_id = getattr(self, "session_id", "default")
                rag_results = vector_store.search(query_vec, n_results=3, session_id=session_id)
                if rag_results:
                    # Cap each chunk at 300 chars and total RAG context at 1200 chars
                    rag_lines = []
                    total = 0
                    for r in rag_results:
                        chunk = r['chunk_text'][:300]
                        line = f"[{r['source_name']}]: {chunk}"
                        if total + len(line) > 1200:
                            break
                        rag_lines.append(line)
                        total += len(line)
                    context_parts.append(f"RAG KNOWLEDGE BASE ({len(rag_lines)} chunks):\n" + "\n\n".join(rag_lines))
                    info(f"RAG: Injected {len(rag_lines)} chunks (~{total} chars) into context")
                else:
                    context_parts.append("RAG KNOWLEDGE BASE: No relevant documents found.")
            except Exception as e:
                info(f"RAG retrieval failed: {e}")

        # 3. Formulate Agent Prompt (OPTIMIZED - Shorter for faster generation)
        rag_tool_hint = (
            "\n- RAG is ENABLED: Use `search_knowledge` for any question about documents, policies, definitions, or non-SQL knowledge.\n"
            "- For questions that need BOTH data and document context, use `generate_code` with the RAG context already injected above.\n"
        ) if use_rag_context else ""

        no_db_notice = (
            "\n⛔ DATABASE CONTEXT IS OFF: The user has disabled DB context.\n"
            "- Do NOT generate any SQL queries or query_db() calls\n"
            "- Do NOT reference any table names, column names, or schema from previous messages\n"
            "- Do NOT assume any database type (PostgreSQL, MySQL, etc.)\n"
            "- If the user asks about data, tell them to enable 'Use DB Context' toggle first\n"
            "- Answer only from general knowledge or uploaded files\n\n"
        ) if not use_db_context else ""

        no_rag_notice = (
            "\n⛔ RAG CONTEXT IS OFF: The user has disabled document search.\n"
            "- Do NOT use the search_knowledge tool\n"
            "- Do NOT reference any document content or uploaded file knowledge from previous messages\n"
            "- If the user asks about document content, tell them to enable 'Use RAG' toggle first\n\n"
        ) if not use_rag_context else ""

        system_msg = (
            "You are a Data Analyst Agent in a Pyodide notebook. EVERY code you generate MUST be Pyodide-compatible.\n\n"
            f"{no_db_notice}"
            f"{no_rag_notice}"
            "CRITICAL PYODIDE RULES (ALWAYS FOLLOW):\n"
            "- NEVER import micropip - it's already available\n"
            "- NEVER use f-strings with formatting ({:,}, {:.2f}) - use string concatenation instead\n"
            "- NEVER use fig.show() or plt.show() - just return the figure\n"
            "- fig.show() WILL CRASH in Pyodide with OSError — ALWAYS end with just 'fig' on its own line\n"
            "- NEVER use pd.read_excel() - use pd.read_csv(io.StringIO(dataset_string))\n"
            "- ALWAYS use await for async operations (query_db, micropip.install)\n"
            "- CRITICAL: The LAST LINE must be OUTSIDE all conditionals (if/else/for/while) - this is how Pyodide displays output\n\n"
            "CELL CONTEXT:\n"
            "- Each cell has an ID like [cell-1], [cell-2], etc.\n"
            "- When user says 'this cell', 'current cell', 'that code', they mean the ACTIVE CELL\n"
            "- Cell outputs show the last execution result\n"
            "- You can reference specific cells by their ID in your responses\n\n"
            f"{rag_tool_hint}"
            "TOOL USAGE — DECISION TREE (follow in order):\n"
            "\n"
            "0. ANSWER DIRECTLY (NO TOOL) — use plain text response for:\n"
            "   - Greetings, thanks, clarifications, follow-up questions\n"
            "   - Questions about schema/columns/tables that are ALREADY in the context above (e.g. 'is there a column named X?' → check schema and answer yes/no)\n"
            "   - Questions about existing notebook cells or charts (e.g. 'is the chart showing 10 items?', 'what does this cell do?', 'is this correct?' → read the cell code and answer)\n"
            "   - Questions about the datasource name, connection, or database type → answer from ACTIVE DATASOURCE NAME in context\n"
            "   - Explaining what was done in a previous cell\n"
            "   - Correcting yourself or acknowledging a mistake\n"
            "   - Any yes/no or factual question answerable from the schema or cell context without running new code\n"
            "   RULE: If the answer is already visible in the SQL DATABASE SCHEMA, EXACT TABLE NAMES, ACTIVE DATASOURCE NAME, or RECENT NOTEBOOK CELLS above, NEVER use a tool — just answer in plain text.\n"
            "   CRITICAL EXAMPLES that MUST be answered directly (no code, no tool):\n"
            "     'what is in the data?' → list the tables and key columns from the schema\n"
            "     'what is the name of my datasource?' → read ACTIVE DATASOURCE NAME from context\n"
            "     'it doesn't have columns or tables' → explain what tables/columns ARE in the schema\n"
            "     'why no visuals are available?' → explain based on what the previous cells returned\n"
            "     'is the chart showing only 10 products?' → look at the LIMIT in the cell code, answer yes/no\n"
            "     'is this correct?' → evaluate the code/output and explain\n"
            "     'what does this query do?' → explain it\n"
            "     'why did you use GROUP BY?' → explain the reasoning\n"
            "\n"
            "1. CHARTS/PLOTS → `generate_code` with Plotly go.Figure\n"
            "   - Triggered by: 'chart', 'plot', 'graph', 'visualize', 'histogram', 'scatter'\n"
            "   - Also triggered by: 'top N', 'ranking', 'compare', 'breakdown', 'distribution'\n"
            "   - ALWAYS use go.Figure (NOT px.express)\n"
            "   - For 'top N' queries: if N is not specified, default to top 10 and mention it\n"
            "   - For 'top N brands/products/categories': use ORDER BY total DESC LIMIT N pattern\n"
            "\n"
            "2. DATA RETRIEVAL / ANALYSIS → `run_sql` or `generate_code`\n"
            "   - Triggered by: 'show me the data', 'get rows', 'fetch records', 'count', 'sum', 'average', 'group by'\n"
            "   - Use `run_sql` for simple SELECT queries\n"
            "   - Use `generate_code` for multi-step Python analysis\n"
            "\n"
            "3. DOCUMENT SEARCH → `search_knowledge`\n"
            "   - Only when user asks about uploaded documents/PDFs\n"
            "\n"
            "TOP N / CHART QUERY RULES (UNIVERSAL):\n"
            "   These rules apply to ANY chart or top-N request regardless of the datasource:\n"
            "\n"
            "   1. METRIC SELECTION — look at the schema and pick the most meaningful numeric column:\n"
            "      - If a 'sales', 'orders', or 'transactions' table exists → prefer SUM(revenue), SUM(amount), SUM(quantity_sold)\n"
            "      - If only a product/item table exists → prefer AVG(price), SUM(stock), MAX(rating)\n"
            "      - NEVER use COUNT(*) or COUNT(id) as the primary metric unless user explicitly says 'count' or 'how many'\n"
            "      - When user says 'top N X' with no metric → infer the most meaningful metric from the schema\n"
            "        (e.g. 'top brands' → revenue or quantity sold, 'top products' → revenue or rating, 'top customers' → total spend)\n"
            "\n"
            "   2. SQL STRUCTURE — always: label column first, ONE aggregated metric second\n"
            "      SELECT <label_col>, <AGG_FUNCTION>(<metric_col>) AS <alias>\n"
            "      FROM <table(s)>\n"
            "      [JOIN if needed to get label or metric from another table]\n"
            "      GROUP BY <label_col>\n"
            "      ORDER BY <alias> DESC\n"
            "      LIMIT <N>\n"
            "\n"
            "   3. JOINS — always JOIN when the label and metric are in different tables\n"
            "      (e.g. brand name is in products, revenue is in sales → JOIN products ON sales.product_id = products.product_id)\n"
            "\n"
            "   4. AGGREGATION — always aggregate for charts. Never use raw unaggregated rows.\n"
            "\n"
            "   5. N DEFAULT — if N is not specified, default to 10\n"
            "\n"
            "EXAMPLES OF DIRECT ANSWERS (no tool needed):\n"
            "   User: 'is there a column named brand?' → Check schema, answer: 'Yes, the products table has a brand column'\n"
            "   User: 'what tables are available?' → List from schema context\n"
            "   User: 'why did you say X?' → Explain directly\n"
            "   User: 'what does this cell do?' → Explain the code\n"
            "\n"
            "CRITICAL PLOTTING RULES (TESTED & WORKING):\n"
            "- When user asks for 'line chart', 'bar chart', 'scatter plot', etc. → MUST create Plotly visualization\n"
            "- ALWAYS use go.Figure pattern (NOT px.express) - it renders reliably in Pyodide\n"
            "- Use: import plotly.graph_objects as go\n"
            "- Use go.Scatter for line/scatter, go.Bar for bar charts, go.Histogram for histograms\n"
            "- Add clear titles and labels\n"
            "- CRITICAL: Return fig object at the end - NEVER use fig.show() in Pyodide!\n"
            "- CORRECT: fig (just return the figure on its own line OUTSIDE conditionals)\n"
            "- WRONG: fig.show() (doesn't work in Pyodide)\n"
            "- WRONG: Using px.express (use go.Figure instead)\n"
            "- WRONG: Putting fig inside an if block (must be at end of cell)\n\n"
            "DATABASE RULES:\n"
            "- When DB available, ALWAYS use await query_db() for real data\n"
            "- NEVER use hardcoded sample data\n"
            "- READ-ONLY: NEVER generate INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE or any write SQL\n"
            "- The database is read-only — any write attempt will be blocked by the server\n"
            "- SCHEMA VALIDATION (CRITICAL): Use ONLY columns that exist in the provided schema — NEVER invent or assume column names\n"
            "- BEFORE writing any SQL: verify every column exists in the target table(s)\n"
            "- FIELD MATCHING (universal — works for any schema):\n"
            "  * Try exact match first, then substring match, then semantic similarity\n"
            "  * 'price' → look for price, unit_price, cost, MSRP, sale_price in any table\n"
            "  * 'sold' → look for quantity_sold, units_sold, qty, amount_sold in any table\n"
            "  * 'name' → look for product_name, customer_name, brand, title, label in any table\n"
            "  * 'revenue' → look for revenue, sales, amount, total, income in any table\n"
            "  * If a column doesn't exist in the target table → check other tables and JOIN\n"
            "- GROUP BY: All non-aggregated SELECT columns MUST be in GROUP BY\n"
            "- QUERY MODIFICATION: When modifying a previous query:\n"
            "  * Keep all existing SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY unchanged unless asked\n"
            "  * Only modify the specific part requested\n"
            "  * NEVER add columns from other tables without JOIN\n"
            "- For listing columns in a table:\n"
            "  * PostgreSQL: SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'YOUR_TABLE_NAME' ORDER BY ordinal_position;\n"
            "  * MySQL: SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_NAME = 'YOUR_TABLE_NAME' AND TABLE_SCHEMA = DATABASE();\n"
            "  * SQLite: PRAGMA table_info(YOUR_TABLE_NAME);\n"
            "- CRITICAL: Replace 'YOUR_TABLE_NAME' with the actual table name from the user's request\n"
            "- NEVER use PRAGMA syntax for PostgreSQL or MySQL\n"
            "- NEVER query information_schema itself as a data table\n\n"
            "FINAL OUTPUT RULES (CRITICAL - MUST FOLLOW):\n"
            "- EVERY code block MUST end with the result object on its own line\n"
            "- CRITICAL: The result (df, fig, or value) MUST be OUTSIDE all conditionals\n"
            "- For charts: End with 'fig' (not fig.show())\n"
            "- For data: End with 'df' or the result variable\n"
            "- For single values: Use print() inside conditionals, then end with the value outside\n"
            "- NEVER end code with comments or print statements - end with the actual object\n"
            "- This final line is what gets displayed in the notebook\n"
            "- EXAMPLE CORRECT:\n"
            "  if df is not None and not df.empty:\n"
            "      print('Data found')\n"
            "  else:\n"
            "      print('No data')\n"
            "  df  # <-- OUTSIDE all conditionals\n"
            "- EXAMPLE WRONG:\n"
            "  if df is not None and not df.empty:\n"
            "      df  # <-- INSIDE conditional, won't display\n"
            "  else:\n"
            "      print('No data')\n\n"
            "MODIFICATION RULES (CRITICAL):\n"
            "- If user says 'change', 'modify', 'update', 'fix', 'edit', 'add', 'remove' about existing code → use generate_code tool with the MODIFIED version of the existing code\n"
            "- NEVER create a new chart/query when the user is asking to modify an existing one\n"
            "- The modified code should be a complete replacement of the active cell code\n\n"
            "RULES:\n"
            "- Keep code simple and focused\n"
            "- If user asks for visualization, ALWAYS create one - don't just print data\n"
            "- If user asks for a list/table, use run_sql tool (system handles display)\n"
        )
        
        if is_modification and original_code:
            system_msg += f"\nMODIFICATION REQUEST: Use `generate_code` to output the modified version of:\n```python\n{original_code}\n```"

        user_msg = f"User Request: {user_query}\n\nENVIRONMENT CONTEXT:\n" + "\n\n".join(context_parts)

        # Inject last SQL query for refinement context
        last_sql = None
        for msg in reversed(chat_history[-6:]):
            content = msg.get("content", "")
            sql_match = re.search(r'query_db\s*\(\s*[\'\"]{1,3}([\s\S]*?)[\'\"]{1,3}\s*\)', content)
            if sql_match:
                last_sql = sql_match.group(1).strip()
                break
        if last_sql and any(w in user_query.lower() for w in ["fix", "wrong", "incorrect", "not right", "change", "modify", "update", "refine", "adjust", "that's not", "instead"]):
            user_msg += (
                f"\n\nPREVIOUS SQL QUERY TO MODIFY:\n```sql\n{last_sql}\n```\n"
                f"MODIFICATION REQUEST: '{user_query}'\n"
                f"TASK: Modify the previous SQL query. Keep all existing SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY unchanged unless explicitly asked. "
                f"Only add columns that exist in the current table(s). Use JOIN if needed to access columns from other tables."
            )

        if chat_history:
            user_msg = f"Previous Chat History:\n{self._format_history(chat_history, scrub_db=not use_db_context, scrub_rag=not use_rag_context)}\n\n{user_msg}"

        # 4. Agent Execution
        print(f"  ├─ 🧠 Building context: {len(context_parts)} parts included.")
        response = self.llm.generate(system_msg, user_msg, images=images, tools=tools)

        # 5. Handle Text Responses
        if isinstance(response, str) or response.get("type") == "text":
            return {
                "answer": response if isinstance(response, str) else response.get("content", "I am processing your request."),
                "tool_used": "Direct Answer",
                "trace": "LLM answered directly without tools.",
                "raw_data":[]
            }

        # 6. Execute Triggered Tools
        elif response.get("type") == "tool_calls":
            tool_call = response["tool_calls"][0]
            name = tool_call.get("name")
            args = tool_call.get("arguments", {})
            info(f"Agent selected tool: {name}")
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}

            if name == "run_sql":
                sql_query = args.get("query", "")
                explanation = args.get("explanation", "")
                user_query_lower = user_query.lower()

                # Fix wrong/partial table names in the generated SQL
                sql_query = self._fix_table_names(sql_query)

                wants_visualization = any(word in user_query_lower for word in [
                    'chart', 'plot', 'graph', 'visualize', 'visualization',
                    'line chart', 'bar chart', 'scatter', 'pie chart', 'histogram',
                    'top n', 'top 5', 'top 10', 'top 20', 'ranking', 'compare', 'breakdown',
                    'analysis', 'analyze', 'distribution', 'trend', 'performance', 'summary chart',
                    'show me a', 'give me a chart', 'give me a graph'
                ])
                wants_notebook_code = any(word in user_query_lower for word in [
                    'code', 'python', 'notebook', 'cell', 'write code', 'show me how'
                ])

                # Only fix column-listing queries when NOT a visualization/code request
                # (avoids corrupting chart SQL that happens to mention a table name)
                if not wants_visualization and not wants_notebook_code:
                    if any(word in user_query_lower for word in ['column', 'columns', 'field', 'fields', 'schema', 'data type', 'data types']):
                        sql_query = self._fix_column_query(sql_query, user_query)

                # Detect specific chart type from user query
                def _detect_chart_type(q: str) -> str:
                    q = q.lower()
                    if any(w in q for w in ['line chart', 'line graph', 'trend', 'over time', 'time series']):
                        return 'line'
                    if any(w in q for w in ['scatter', 'correlation', 'vs ', 'versus']):
                        return 'scatter'
                    if any(w in q for w in ['pie chart', 'pie', 'proportion', 'share', 'percentage breakdown']):
                        return 'pie'
                    if any(w in q for w in ['histogram', 'distribution', 'frequency']):
                        return 'histogram'
                    if any(w in q for w in ['area chart', 'area graph', 'stacked area']):
                        return 'area'
                    return 'bar'  # default

                if wants_visualization:
                    fixed_query = self._validate_and_fix_sql(self._fix_table_names(sql_query))
                    chart_type = _detect_chart_type(user_query)

                    # Execute SQL server-side to get actual column info
                    try:
                        preview_data = self.db.execute_query(fixed_query + " LIMIT 5" if "LIMIT" not in fixed_query.upper() else fixed_query)
                    except:
                        preview_data = None

                    if preview_data and len(preview_data) > 0:
                        # Get actual column names and types from real data
                        cols = list(preview_data[0].keys())

                        # Identify label col (first non-numeric) and value col (best numeric)
                        import decimal
                        label_hints = ['name', 'title', 'label', 'product', 'category', 'brand', 'region', 'month', 'date', 'year', 'type', 'status']
                        value_hints = ['total_revenue', 'revenue', 'total_sales', 'sales', 'total_profit', 'profit', 'units_sold', 'quantity_sold', 'quantity', 'amount', 'price', 'value', 'count', 'total']

                        # Find label column
                        x_col = None
                        for c in cols:
                            if any(h in c.lower() for h in label_hints):
                                x_col = c
                                break
                        if not x_col:
                            # Use first column that has non-numeric values
                            for c in cols:
                                val = preview_data[0][c]
                                if not isinstance(val, (int, float, decimal.Decimal)):
                                    x_col = c
                                    break
                        if not x_col:
                            x_col = cols[0]

                        # Find best value column
                        numeric_cols = []
                        for c in cols:
                            if c == x_col: continue
                            val = preview_data[0][c]
                            if isinstance(val, (int, float, decimal.Decimal)):
                                numeric_cols.append(c)

                        # Score numeric cols by hint priority
                        def score_col(col):
                            cl = col.lower()
                            for i, h in enumerate(value_hints):
                                if cl == h: return len(value_hints) - i + 20
                                if h in cl: return len(value_hints) - i
                            return 0

                        if len(cols) == 2:
                            y_col = numeric_cols[0] if numeric_cols else cols[1]
                        else:
                            y_col = max(numeric_cols, key=score_col) if numeric_cols else (cols[1] if len(cols) > 1 else cols[0])

                        # Generate chart code with actual column names (no runtime picker needed)
                        chart_templates = {
                            'pie': f"    fig = go.Figure(data=go.Pie(labels=df['{x_col}'], values=df['{y_col}'], hole=0.3, textinfo='label+percent'))",
                            'line': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='lines+markers', line=dict(color='#2563eb', width=2)))",
                            'scatter': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='markers', marker=dict(color='#2563eb', size=7)))",
                            'histogram': f"    fig = go.Figure(data=go.Histogram(x=df['{x_col}'], marker_color='#2563eb'))",
                            'area': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='lines', fill='tozeroy', line=dict(color='#2563eb')))",
                            'bar': f"    fig = go.Figure(data=go.Bar(x=df['{x_col}'], y=df['{y_col}'], marker_color='#2563eb', hovertemplate='%{{x}}<br>{y_col}: %{{y}}<extra></extra>'))",
                        }
                        chart_code = chart_templates.get(chart_type, chart_templates['bar'])
                        safe_title = explanation.replace("'", "\\'")

                        python_code = f"""# {explanation}
import plotly.graph_objects as go
import pandas as _pd

df = await query_db('''{fixed_query}''')

if df is not None and not df.empty:
    # Convert numeric columns
    for _c in ['{y_col}']:
        try: df[_c] = _pd.to_numeric(df[_c], errors='coerce')
        except: pass
    df = df.sort_values('{y_col}', ascending=False).head(15)
{chart_code}
    fig.update_layout(
        title='{safe_title}',
        xaxis_title='{x_col}',
        yaxis_title='{y_col}',
        template='plotly_white',
        height=450,
        xaxis_tickangle=-35,
        xaxis=dict(categoryorder='total descending'),
        yaxis=dict(tickformat=',.0f' if df['{y_col}'].max() > 1000 else None)
    )
else:
    fig = go.Figure()
    print("No data returned")

fig
"""
                    else:
                        # Fallback to runtime picker if server-side execution fails
                        smart_col_picker = """    # Smart column selection: prefer readable name cols for X, best-matching numeric for Y
    _label_hints = ['name', 'title', 'label', 'description', 'product', 'category', 'brand', 'region', 'month', 'date', 'year', 'type', 'status', 'id']
    _value_hints_ranked = ['total_revenue', 'revenue', 'total_sales', 'sales', 'total_profit', 'profit',
                           'units_sold', 'quantity_sold', 'total_quantity', 'quantity', 'amount',
                           'avg_price', 'price', 'value', 'score', 'avg', 'count', 'total']
    # Convert ALL columns to numeric first (handles MySQL Decimal, object strings, etc.)
    import pandas as _pd
    for _c in df.columns:
        try: df[_c] = _pd.to_numeric(df[_c], errors='raise')
        except: pass
    _cols = list(df.columns)
    x_col = next((c for c in _cols if any(h in c.lower() for h in _label_hints)), _cols[0])
    _num_cols = [c for c in _cols if c != x_col and df[c].dtype in ['int64', 'float64', 'int32', 'float32']]
    if len(_cols) == 2:
        y_col = _num_cols[0] if _num_cols else _cols[1]
    else:
        def _score_col(col):
            cl = col.lower()
            for i, h in enumerate(_value_hints_ranked):
                if cl == h: return len(_value_hints_ranked) - i + 20
                if cl.startswith(h + '_') or cl.endswith('_' + h): return len(_value_hints_ranked) - i + 10
                if h in cl: return len(_value_hints_ranked) - i
            return 0
        y_col = max(_num_cols, key=_score_col) if _num_cols else (_cols[1] if len(_cols) > 1 else _cols[0])
    df = df.sort_values(y_col, ascending=False).head(15)"""

                        if chart_type == 'pie':
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Pie(labels=df[x_col], values=df[y_col], hole=0.3,
                    textinfo='label+percent', hovertemplate='%{label}<br>%{value}<extra></extra>')
    )"""
                        elif chart_type == 'line':
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Scatter(x=df[x_col], y=df[y_col], mode='lines+markers', name=y_col,
                        line=dict(color='#2563eb', width=2), marker=dict(size=5),
                        hovertemplate='%{x}<br>' + y_col + ': %{y}<extra></extra>')
    )"""
                        elif chart_type == 'scatter':
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Scatter(x=df[x_col], y=df[y_col], mode='markers', name=y_col,
                        marker=dict(color='#2563eb', size=7, opacity=0.7),
                        hovertemplate='%{x}<br>' + y_col + ': %{y}<extra></extra>')
    )"""
                        elif chart_type == 'histogram':
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Histogram(x=df[x_col], marker_color='#2563eb', opacity=0.8)
    )"""
                        elif chart_type == 'area':
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Scatter(x=df[x_col], y=df[y_col], mode='lines', fill='tozeroy', name=y_col,
                        line=dict(color='#2563eb', width=2))
    )"""
                        else:  # bar
                            chart_code = smart_col_picker + """
    fig = go.Figure(
        data=go.Bar(x=df[x_col], y=df[y_col], name=y_col, marker_color='#2563eb',
                    hovertemplate='%{x}<br>' + y_col + ': %{y}<extra></extra>')
    )"""

                        safe_title = explanation.replace("'", "\\'")
                        python_code = f"""# {explanation}
import plotly.graph_objects as go

df = await query_db('''{fixed_query}''')

if df is not None and not df.empty:
{chart_code}
    fig.update_layout(
        title='{safe_title}',
        xaxis_title=x_col,
        yaxis_title=y_col,
        template='plotly_white',
        height=450,
        xaxis_tickangle=-35,
        xaxis=dict(categoryorder='total descending'),
        yaxis=dict(tickformat=',.0f' if df[y_col].max() > 1000 else None)
    )
else:
    fig = go.Figure()
    print("No data returned")

fig
"""

                    python_code = self._sanitize_for_pyodide(python_code)
                    python_code = self._inject_micropip_guards(python_code)
                    return {
                        "answer": f"```python\n{python_code}\n```",
                        "tool_used": "Generate Code",
                        "trace": fixed_query,
                        "raw_data": []
                    }

                elif wants_notebook_code:
                    fixed_query = self._fix_table_names(sql_query)
                    # Validate SQL before using it
                    fixed_query = self._validate_and_fix_sql(fixed_query)
                    python_code = f"""# {explanation}
df = await query_db('''{fixed_query}''')

if df is not None and not df.empty:
    print("Results: " + str(len(df)) + " rows")
else:
    print("No data returned")

df
"""
                    python_code = self._sanitize_for_pyodide(python_code)
                    python_code = self._inject_micropip_guards(python_code)
                    return {
                        "answer": f"```python\n{python_code}\n```",
                        "tool_used": "Generate Code",
                        "trace": fixed_query,
                        "raw_data": []
                    }

                else:
                    # Validate SQL before sending to user
                    sql_query = self._validate_and_fix_sql(sql_query)

                    # Wrap SQL in a Pyodide query_db cell so the user gets a live DataFrame
                    python_code = f"""# {explanation}
df = await query_db('''{sql_query}''')

if df is not None and not df.empty:
    print("Results: " + str(len(df)) + " rows")
else:
    print("⚠️ No data returned. The query ran successfully but found no matching records.")
    print("Try: checking filters, date ranges, or whether the table has data.")
df
"""
                    python_code = self._sanitize_for_pyodide(python_code)
                    python_code = self._inject_micropip_guards(python_code)
                    return {
                        "answer": f"```python\n{python_code}\n```",
                        "tool_used": "Generate Code",
                        "trace": sql_query,
                        "raw_data": []
                    }

            elif name == "generate_code":
                info("Generating Python code for notebook...")
                code = self._sanitize_for_pyodide(args.get("python_code", ""))
                code = self._inject_micropip_guards(code)
                code = self._ensure_final_output(code)
                
                if is_modification:
                    return {
                        "answer": f"I've updated the code in the active cell.",
                        "tool_used": "Modify_Code",
                        "action": "UPDATE_CELL",
                        "cell_id": active_cell_id,
                        "modified_code": code,
                        "trace": "Code modified via Tool.",
                        "raw_data":[]
                    }
                
                # Combine LLM's general text content with the tool-specific explanation
                explanation = args.get('explanation', '')
                llm_content = response.get('content', '').strip()
                
                # Avoid redundancy if the explanation is already in the content
                final_answer = llm_content if llm_content else explanation
                if code not in final_answer:
                    final_answer += f"\n\n```python\n{code}\n```"
                
                return {"answer": final_answer, "tool_used": "Generate Code", "trace": "Code generated.", "raw_data":[]}

            elif name == "search_knowledge":
                search_query = args.get("search_query", user_query)
                query_vec = self.embedder.get_embedding(search_query)
                session_id = getattr(self, "session_id", "default")
                retrieved_data = vector_store.search(query_vec, n_results=3, session_id=session_id)

                # Cap chunks to stay token-safe
                rag_lines = []
                total = 0
                for r in retrieved_data:
                    chunk = r['chunk_text'][:300]
                    line = f"[{r['source_name']}]: {chunk}"
                    if total + len(line) > 1200:
                        break
                    rag_lines.append(line)
                    total += len(line)
                rag_context = "\n\n".join(rag_lines) if rag_lines else "No relevant documents found."

                # Hybrid: if DB is also on, run a related SQL query and combine
                db_data_str = ""
                if use_db_context and getattr(self, "db", None) and self.db.engine:
                    try:
                        # Ask the LLM to generate a relevant SQL query for the same question
                        schema = self.db.get_schema()
                        tables = {}
                        for row in schema:
                            tables.setdefault(row['table_name'], []).append(f"{row['column_name']} ({row['data_type']})")
                        schema_str = "\n".join([f"- Table `{t}`: {', '.join(c)}" for t, c in tables.items()])
                        sql_prompt = (
                            f"Given this schema:\n{schema_str}\n\n"
                            f"Write ONE simple SQL query to get relevant data for: '{user_query}'\n"
                            f"Output ONLY the raw SQL, nothing else."
                        )
                        sql_resp = self.llm.generate("You are a SQL expert. Output only raw SQL.", sql_prompt)
                        sql_query = sql_resp.strip() if isinstance(sql_resp, str) else sql_resp.get("content", "").strip()
                        # Strip markdown fences if present
                        sql_query = re.sub(r"```(?:sql)?|```", "", sql_query).strip()
                        if sql_query.upper().startswith("SELECT"):
                            db_rows = self.db.execute_query(sql_query)
                            if db_rows:
                                db_data_str = f"\n\nDB QUERY RESULTS (for context):\nSQL: {sql_query}\nData: {json.dumps(db_rows[:10], default=str)}"
                                info(f"Hybrid RAG+SQL: fetched {len(db_rows)} rows")
                    except Exception as e:
                        info(f"Hybrid SQL fetch failed: {e}")

                tool_label = "Hybrid (RAG + SQL)" if db_data_str else "Vector_Search (RAG)"
                system_msg = (
                    "You are a data analyst. Answer the user's question using the provided document context and database results. "
                    "Be specific — use numbers from the DB data and definitions/context from the documents. "
                    "If the documents don't cover the topic, say so and rely on the DB data."
                )
                user_msg = f"Question: '{user_query}'\n\nDOCUMENT CONTEXT:\n{rag_context}{db_data_str}"
                synth_response = self.llm.generate(system_msg, user_msg)
                final_ans = synth_response if isinstance(synth_response, str) else synth_response.get("content", "")
                return {"answer": final_ans, "tool_used": tool_label, "trace": search_query, "raw_data": retrieved_data}

        return {"answer": "Unexpected format.", "tool_used": "Error", "trace": "Parse error.", "raw_data": []}

    # =========================================================================
    # STREAMING VERSION — yields SSE-formatted JSON events
    # =========================================================================
    def route_and_execute_stream(self, user_query: str, notebook_cells, client_vars,
                                  chat_history=None, images=None, *,
                                  is_modification=False, original_code=None,
                                  active_cell_id=None, use_db_context=True,
                                  use_rag_context=False):
        """
        Generator that yields newline-delimited JSON strings (NDJSON / SSE data).
        Each line is: data: <json>\n\n

        Event types:
          {"type": "token",     "text": "..."}          — streaming text token
          {"type": "code",      "answer": "...", ...}    — final code/tool result
          {"type": "done",      "tool_used": "...", ...} — stream complete
          {"type": "error",     "message": "..."}        — error
        """
        import json as _json

        def _sse(obj: dict) -> str:
            return f"data: {_json.dumps(obj)}\n\n"

        # Reuse the same context-building logic from route_and_execute
        # by calling it with a flag to get back the prepared prompts
        try:
            # Build context (reuse existing logic)
            result = self._build_prompt_context(
                user_query, notebook_cells, client_vars, chat_history or [],
                images, is_modification=is_modification, original_code=original_code,
                active_cell_id=active_cell_id, use_db_context=use_db_context,
                use_rag_context=use_rag_context
            )

            if result.get("early_return"):
                # Vague query or other early exit — stream the answer as tokens
                answer = result["answer"]
                # Stream word by word for a natural feel
                words = answer.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    yield _sse({"type": "token", "text": token})
                yield _sse({"type": "done", "tool_used": result.get("tool_used", "Direct Answer"),
                            "answer": answer, "trace": result.get("trace", ""), "raw_data": []})
                return

            system_msg = result["system_msg"]
            user_msg   = result["user_msg"]
            tools      = result["tools"]

            # Stream from LLM
            accumulated_text = ""
            tool_event = None

            for event in self.llm.generate_stream(system_msg, user_msg, images=images, tools=tools):
                if event["type"] == "token":
                    accumulated_text += event["text"]
                    yield _sse({"type": "token", "text": event["text"]})

                elif event["type"] == "tool_call":
                    tool_event = event
                    # Don't yield yet — process the tool call first

                elif event["type"] == "done":
                    break

            # No tool call — pure text answer
            if tool_event is None:
                yield _sse({"type": "done", "tool_used": "Direct Answer",
                            "answer": accumulated_text, "trace": "", "raw_data": []})
                return

            # Process tool call — reuse existing tool execution logic
            name = tool_event["name"]
            args = tool_event["arguments"]
            llm_content = tool_event.get("content", "")
            info(f"Agent selected tool (stream): {name}")

            if isinstance(args, str):
                try: args = _json.loads(args)
                except: args = {}

            # Delegate to the synchronous tool execution (already handles all cases)
            # We pass a fake response object that matches what route_and_execute expects
            fake_response = {"type": "tool_calls", "tool_calls": [{"name": name, "arguments": args}], "content": llm_content}
            tool_result = self._execute_tool(
                name, args, llm_content, user_query, is_modification,
                original_code, active_cell_id, use_db_context, use_rag_context
            )

            # Emit the tool result as a final event
            yield _sse({"type": "code", **tool_result})
            yield _sse({"type": "done", "tool_used": tool_result.get("tool_used", name),
                        "answer": tool_result.get("answer", ""), "trace": tool_result.get("trace", ""),
                        "raw_data": tool_result.get("raw_data", [])})

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield _sse({"type": "error", "message": str(e)})
            yield _sse({"type": "done", "tool_used": "Error", "answer": f"Error: {e}", "trace": "", "raw_data": []})

    def _infer_joins(self) -> str:
        """Infer likely JOIN relationships from column naming patterns."""
        if not getattr(self, "db", None) or not self.db.engine:
            return ""
        try:
            schema = self.db.get_schema()
            tables = {}
            for row in schema:
                tables.setdefault(row['table_name'], []).append(row['column_name'])
            
            joins = []
            for table, cols in tables.items():
                for col in cols:
                    # Look for columns like product_id, brand_id, customer_id
                    if col.endswith('_id') and col != 'id':
                        ref_table = col[:-3]  # strip _id
                        # Find matching table (exact or prefix match)
                        for other_table in tables:
                            if other_table == ref_table or other_table.startswith(ref_table):
                                if 'id' in tables[other_table] or f'{other_table}_id' in tables[other_table]:
                                    joins.append(f"  {table}.{col} → {other_table}.id")
                                    break
            
            if joins:
                return "\nINFERRED JOIN RELATIONSHIPS (use these for JOINs):\n" + "\n".join(joins[:10])
            return ""
        except:
            return ""

    def _build_prompt_context(self, user_query, notebook_cells, client_vars,
                               chat_history, images, *, is_modification, original_code,
                               active_cell_id, use_db_context, use_rag_context):
        """
        Extracts the prompt-building logic from route_and_execute so it can be
        shared with the streaming path. Returns a dict with system_msg, user_msg,
        tools, or early_return=True with answer.
        """
        # Vague query check
        if self._is_vague_query(user_query) and use_db_context and getattr(self, "db", None) and self.db.engine:
            schema = self.db.get_schema()
            tables = list(set(row['table_name'] for row in schema))
            table_list = ", ".join(tables[:10])
            return {
                "early_return": True,
                "answer": f"Could you be more specific? For example:\n- Which table or metric are you interested in? (Available: {table_list})\n- What time period or filters should I apply?\n- What format do you want — a table, chart, or summary?",
                "tool_used": "Direct Answer",
                "trace": "Vague query — asked for clarification.",
            }

        # Build tools list
        tools = [
            {"type": "function", "function": {"name": "run_sql", "description": "Execute a SQL query against the connected database to retrieve raw data.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["query", "explanation"]}}},
            {"type": "function", "function": {"name": "generate_code", "description": "Generate Pyodide-compatible Python code to run in the notebook.", "parameters": {"type": "object", "properties": {"python_code": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["python_code", "explanation"]}}},
        ]
        if use_rag_context:
            tools.append({"type": "function", "function": {"name": "search_knowledge", "description": "Search uploaded documents for definitions, context, or explanations.", "parameters": {"type": "object", "properties": {"search_query": {"type": "string"}}, "required": ["search_query"]}}})

        # Build context parts (same as route_and_execute)
        context_parts = []
        if use_db_context and getattr(self, "db", None) and self.db.engine:
            schema = self.db.get_schema()
            if schema:
                tables = {}
                for row in schema:
                    tables.setdefault(row['table_name'], []).append(f"{row['column_name']} ({row['data_type']})")
                context_parts.append("SQL DATABASE SCHEMA:\n" + "\n".join([f"- Table `{t}`: {', '.join(c)}" for t, c in tables.items()]))
                context_parts.append(f"\nEXACT TABLE NAMES:\n" + ", ".join([f"`{t}`" for t in tables.keys()]))
                db_url = str(self.db.engine.url).lower()
                if 'postgres' in db_url:
                    context_parts.append("\n⚠️ DATABASE: PostgreSQL")
                elif 'mysql' in db_url:
                    context_parts.append("\n⚠️ DATABASE: MySQL")

        if notebook_cells:
            if notebook_cells and isinstance(notebook_cells[0], dict):
                recent = notebook_cells[-5:]
                cell_ctx = []
                for c in recent:
                    code = c.get('code', '').strip()
                    if code:
                        cell_ctx.append(f"Cell [{c.get('id')}]:\n```python\n{code}\n```")
                if cell_ctx:
                    context_parts.append("RECENT NOTEBOOK CELLS:\n" + "\n\n".join(cell_ctx))

        if client_vars:
            context_parts.append(f"ACTIVE VARIABLES: {json.dumps(client_vars[:15])}")

        if use_rag_context:
            try:
                qv = self.embedder.get_embedding(user_query)
                rr = vector_store.search(qv, n_results=3, session_id=getattr(self, "session_id", "default"))
                if rr:
                    lines, total = [], 0
                    for r in rr:
                        line = f"[{r['source_name']}]: {r['chunk_text'][:300]}"
                        if total + len(line) > 1200: break
                        lines.append(line); total += len(line)
                    context_parts.append(f"RAG KNOWLEDGE BASE:\n" + "\n\n".join(lines))
            except: pass

        no_db = ("\n⛔ DATABASE CONTEXT IS OFF — do NOT generate SQL or reference schema.\n") if not use_db_context else ""
        no_rag = ("\n⛔ RAG CONTEXT IS OFF — do NOT use search_knowledge.\n") if not use_rag_context else ""
        rag_hint = ("\n- RAG ENABLED: use search_knowledge for document questions.\n") if use_rag_context else ""

        system_msg = (
            "You are a Data Analyst Agent in a Pyodide notebook.\n\n"
            f"{no_db}{no_rag}"
            "TOOL USAGE:\n"
            "0. Answer directly (no tool) for: greetings, yes/no questions about existing cells/charts, schema questions already in context, follow-ups, corrections.\n"
            "   EXAMPLES: 'is the chart showing 10 items?' → read cell code, answer yes/no. 'is this correct?' → evaluate and explain.\n"
            "1. Charts/plots → generate_code with go.Figure\n"
            "2. Data retrieval → run_sql\n"
            "3. Documents → search_knowledge\n"
            f"{rag_hint}"
        )
        if is_modification and original_code:
            system_msg += f"\nMODIFICATION: use generate_code to modify:\n```python\n{original_code}\n```"

        user_msg = f"User Request: {user_query}\n\nENVIRONMENT CONTEXT:\n" + "\n\n".join(context_parts)

        # Inject last SQL for refinement
        last_sql = None
        for msg in reversed((chat_history or [])[-6:]):
            m = re.search(r"query_db\s*\(\s*['\"{]{1,3}([\s\S]*?)['\"}]{1,3}\s*\)", msg.get("content", ""))
            if m:
                last_sql = m.group(1).strip()
                break
        if last_sql and any(w in user_query.lower() for w in ["fix", "wrong", "change", "modify", "refine"]):
            user_msg += f"\n\nLAST SQL:\n```sql\n{last_sql}\n```"

        if chat_history:
            user_msg = f"Previous Chat:\n{self._format_history(chat_history, scrub_db=not use_db_context, scrub_rag=not use_rag_context)}\n\n{user_msg}"

        return {"system_msg": system_msg, "user_msg": user_msg, "tools": tools, "early_return": False}

    def _execute_tool(self, name, args, llm_content, user_query, is_modification,
                      original_code, active_cell_id, use_db_context, use_rag_context):
        """
        Executes a tool call and returns the result dict.
        Extracted from route_and_execute so it can be shared with the streaming path.
        """
        user_query_lower = user_query.lower()

        if name == "run_sql":
            sql_query = args.get("query", "")
            explanation = args.get("explanation", "")
            sql_query = self._fix_table_names(sql_query)

            wants_visualization = any(w in user_query_lower for w in [
                'chart', 'plot', 'graph', 'visualize', 'visualization',
                'line chart', 'bar chart', 'scatter', 'pie chart', 'histogram',
                'top n', 'top 5', 'top 10', 'top 20', 'ranking', 'compare', 'breakdown',
                'analysis', 'analyze', 'distribution', 'trend', 'performance', 'summary chart',
                'show me a', 'give me a chart', 'give me a graph'
            ])
            wants_notebook_code = any(w in user_query_lower for w in [
                'code', 'python', 'notebook', 'cell', 'write code', 'show me how'
            ])

            if not wants_visualization and not wants_notebook_code:
                if any(w in user_query_lower for w in ['column', 'columns', 'field', 'fields', 'schema', 'data type']):
                    sql_query = self._fix_column_query(sql_query, user_query)

            if wants_visualization:
                fixed_query = self._validate_and_fix_sql(self._fix_table_names(sql_query))
                chart_type = self._detect_chart_type_static(user_query)

                # Execute SQL server-side to get actual column info
                try:
                    preview_data = self.db.execute_query(fixed_query + " LIMIT 5" if "LIMIT" not in fixed_query.upper() else fixed_query)
                except:
                    preview_data = None

                if preview_data and len(preview_data) > 0:
                    # Get actual column names and types from real data
                    cols = list(preview_data[0].keys())

                    import decimal
                    label_hints = ['name', 'title', 'label', 'product', 'category', 'brand', 'region', 'month', 'date', 'year', 'type', 'status']
                    value_hints = ['total_revenue', 'revenue', 'total_sales', 'sales', 'total_profit', 'profit', 'units_sold', 'quantity_sold', 'quantity', 'amount', 'price', 'value', 'count', 'total']

                    x_col = None
                    for c in cols:
                        if any(h in c.lower() for h in label_hints):
                            x_col = c
                            break
                    if not x_col:
                        for c in cols:
                            val = preview_data[0][c]
                            if not isinstance(val, (int, float, decimal.Decimal)):
                                x_col = c
                                break
                    if not x_col:
                        x_col = cols[0]

                    numeric_cols = []
                    for c in cols:
                        if c == x_col: continue
                        val = preview_data[0][c]
                        if isinstance(val, (int, float, decimal.Decimal)):
                            numeric_cols.append(c)

                    def score_col(col):
                        cl = col.lower()
                        for i, h in enumerate(value_hints):
                            if cl == h: return len(value_hints) - i + 20
                            if h in cl: return len(value_hints) - i
                        return 0

                    if len(cols) == 2:
                        y_col = numeric_cols[0] if numeric_cols else cols[1]
                    else:
                        y_col = max(numeric_cols, key=score_col) if numeric_cols else (cols[1] if len(cols) > 1 else cols[0])

                    chart_templates = {
                        'pie': f"    fig = go.Figure(data=go.Pie(labels=df['{x_col}'], values=df['{y_col}'], hole=0.3, textinfo='label+percent'))",
                        'line': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='lines+markers', line=dict(color='#2563eb', width=2)))",
                        'scatter': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='markers', marker=dict(color='#2563eb', size=7)))",
                        'histogram': f"    fig = go.Figure(data=go.Histogram(x=df['{x_col}'], marker_color='#2563eb'))",
                        'area': f"    fig = go.Figure(data=go.Scatter(x=df['{x_col}'], y=df['{y_col}'], mode='lines', fill='tozeroy', line=dict(color='#2563eb')))",
                        'bar': f"    fig = go.Figure(data=go.Bar(x=df['{x_col}'], y=df['{y_col}'], marker_color='#2563eb', hovertemplate='%{{x}}<br>{y_col}: %{{y}}<extra></extra>'))",
                    }
                    chart_code = chart_templates.get(chart_type, chart_templates['bar'])
                    safe_title = explanation.replace("'", "\\'")

                    python_code = f"""# {explanation}
import plotly.graph_objects as go
import pandas as _pd

df = await query_db('''{fixed_query}''')

if df is not None and not df.empty:
    # Convert numeric columns
    for _c in ['{y_col}']:
        try: df[_c] = _pd.to_numeric(df[_c], errors='coerce')
        except: pass
    df = df.sort_values('{y_col}', ascending=False).head(15)
{chart_code}
    fig.update_layout(
        title='{safe_title}',
        xaxis_title='{x_col}',
        yaxis_title='{y_col}',
        template='plotly_white',
        height=450,
        xaxis_tickangle=-35,
        xaxis=dict(categoryorder='total descending'),
        yaxis=dict(tickformat=',.0f' if df['{y_col}'].max() > 1000 else None)
    )
else:
    fig = go.Figure()
    print("No data returned")

fig
"""
                else:
                    # Fallback to runtime picker if server-side execution fails
                    smart_col_picker = """    _label_hints = ['name', 'title', 'label', 'description', 'product', 'category', 'brand', 'region', 'month', 'date', 'year', 'type', 'status', 'id']
    _value_hints_ranked = ['total_revenue', 'revenue', 'total_sales', 'sales', 'total_profit', 'profit',
                           'units_sold', 'quantity_sold', 'total_quantity', 'quantity', 'amount',
                           'avg_price', 'price', 'value', 'score', 'avg', 'count', 'total']
    import pandas as _pd
    for _c in df.columns:
        try: df[_c] = _pd.to_numeric(df[_c], errors='raise')
        except: pass
    _cols = list(df.columns)
    x_col = next((c for c in _cols if any(h in c.lower() for h in _label_hints)), _cols[0])
    _num_cols = [c for c in _cols if c != x_col and df[c].dtype in ['int64', 'float64', 'int32', 'float32']]
    if len(_cols) == 2:
        y_col = _num_cols[0] if _num_cols else _cols[1]
    else:
        def _score_col(col):
            cl = col.lower()
            for i, h in enumerate(_value_hints_ranked):
                if cl == h: return len(_value_hints_ranked) - i + 20
                if cl.startswith(h + '_') or cl.endswith('_' + h): return len(_value_hints_ranked) - i + 10
                if h in cl: return len(_value_hints_ranked) - i
            return 0
        y_col = max(_num_cols, key=_score_col) if _num_cols else (_cols[1] if len(_cols) > 1 else _cols[0])
    df = df.sort_values(y_col, ascending=False).head(15)"""
                    chart_map = {
                        'line': """    fig = go.Figure(data=go.Scatter(x=df[x_col], y=df[y_col], mode='lines+markers', line=dict(color='#2563eb', width=2)))""",
                        'scatter': """    fig = go.Figure(data=go.Scatter(x=df[x_col], y=df[y_col], mode='markers', marker=dict(color='#2563eb', size=7)))""",
                        'histogram': """    fig = go.Figure(data=go.Histogram(x=df[x_col], marker_color='#2563eb'))""",
                        'area': """    fig = go.Figure(data=go.Scatter(x=df[x_col], y=df[y_col], mode='lines', fill='tozeroy', line=dict(color='#2563eb')))""",
                        'bar': """    fig = go.Figure(data=go.Bar(x=df[x_col], y=df[y_col], marker_color='#2563eb'))""",
                    }
                    chart_code = smart_col_picker + "\n" + chart_map.get(chart_type, chart_map['bar'])
                    safe_title = explanation.replace("'", "\\'")
                    python_code = f"""# {explanation}
import plotly.graph_objects as go
df = await query_db('''{fixed_query}''')
if df is not None and not df.empty:
{chart_code}
    fig.update_layout(title='{safe_title}', xaxis_title=x_col, yaxis_title=y_col, template='plotly_white', height=450, xaxis_tickangle=-35, xaxis=dict(categoryorder='total descending'), yaxis=dict(tickformat=',.0f' if df[y_col].max() > 1000 else None))
else:
    fig = go.Figure()
    print("No data returned")
fig
"""

                python_code = self._sanitize_for_pyodide(self._inject_micropip_guards(python_code))
                return {"answer": f"```python\n{python_code}\n```", "tool_used": "Generate Code", "trace": fixed_query, "raw_data": []}

            elif wants_notebook_code:
                fixed_query = self._validate_and_fix_sql(self._fix_table_names(sql_query))
                python_code = f"""# {explanation}
df = await query_db('''{fixed_query}''')
if df is not None and not df.empty:
    print("Results: " + str(len(df)) + " rows")
else:
    print("⚠️ No data returned.")
df
"""
                python_code = self._sanitize_for_pyodide(self._inject_micropip_guards(python_code))
                return {"answer": f"```python\n{python_code}\n```", "tool_used": "Generate Code", "trace": fixed_query, "raw_data": []}

            else:
                sql_query = self._validate_and_fix_sql(sql_query)
                python_code = f"""# {explanation}
df = await query_db('''{sql_query}''')
if df is not None and not df.empty:
    print("Results: " + str(len(df)) + " rows")
else:
    print("⚠️ No data returned. Try checking filters or date ranges.")
df
"""
                python_code = self._sanitize_for_pyodide(self._inject_micropip_guards(python_code))
                return {"answer": f"```python\n{python_code}\n```", "tool_used": "Generate Code", "trace": sql_query, "raw_data": []}

        elif name == "generate_code":
            code = self._sanitize_for_pyodide(args.get("python_code", ""))
            code = self._inject_micropip_guards(code)
            code = self._ensure_final_output(code)
            if is_modification:
                return {"answer": "I've updated the code in the active cell.", "tool_used": "Modify_Code",
                        "action": "UPDATE_CELL", "cell_id": active_cell_id, "modified_code": code,
                        "trace": "Code modified.", "raw_data": []}
            explanation = args.get('explanation', '')
            final_answer = (llm_content or explanation)
            if code not in final_answer:
                final_answer += f"\n\n```python\n{code}\n```"
            return {"answer": final_answer, "tool_used": "Generate Code", "trace": "Code generated.", "raw_data": []}

        elif name == "search_knowledge":
            search_query = args.get("search_query", user_query)
            qv = self.embedder.get_embedding(search_query)
            retrieved = vector_store.search(qv, n_results=3, session_id=getattr(self, "session_id", "default"))
            lines, total = [], 0
            for r in retrieved:
                line = f"[{r['source_name']}]: {r['chunk_text'][:300]}"
                if total + len(line) > 1200: break
                lines.append(line); total += len(line)
            rag_ctx = "\n\n".join(lines) if lines else "No relevant documents found."
            synth = self.llm.generate(
                "Answer using the document context provided.",
                f"Question: '{user_query}'\n\nDOCUMENT CONTEXT:\n{rag_ctx}"
            )
            ans = synth if isinstance(synth, str) else synth.get("content", "")
            return {"answer": ans, "tool_used": "Vector_Search (RAG)", "trace": search_query, "raw_data": retrieved}

        return {"answer": "Unknown tool.", "tool_used": "Error", "trace": "", "raw_data": []}

    def _analyze_image_with_schema(self, user_query: str, images: list, schema_context: str) -> dict:
        """
        When user provides an image (chart/screenshot) with DB connected,
        analyze the image and reproduce/extend it from the actual datasource.
        """
        system_msg = (
            "You are a Data Analyst Agent. The user has provided an image (likely a chart or data visualization) "
            "along with a connected database. Your job is to:\n"
            "1. Analyze what the image shows (chart type, axes, data being displayed)\n"
            "2. Identify which tables/columns from the schema could produce similar data\n"
            "3. Generate Python code using await query_db() and Plotly go.Figure to reproduce or extend the chart from the actual database\n\n"
            "CRITICAL RULES:\n"
            "- Use ONLY columns that exist in the provided schema\n"
            "- Use go.Figure (NOT fig.show(), NOT px.express)\n"
            "- End code with 'fig' on its own line\n"
            "- NEVER use hardcoded data\n"
            f"\nDATABASE SCHEMA:\n{schema_context}"
        )
        user_msg = f"User request: {user_query}\n\nPlease analyze the image and generate code to reproduce/extend this visualization from the connected database."

        response = self.llm.generate(system_msg, user_msg, images=images)

        if isinstance(response, str):
            content = response
        else:
            content = response.get("content", "")

        # Extract code if present
        code_match = re.search(r'```(?:python|py)\n([\s\S]*?)```', content)
        if code_match:
            code = self._sanitize_for_pyodide(code_match.group(1))
            code = self._inject_micropip_guards(code)
            explanation_text = content.replace(code_match.group(0), "").strip()
            return {
                "answer": f"{explanation_text}\n\n```python\n{code}\n```",
                "tool_used": "Generate Code",
                "trace": "Image analyzed and reproduced from datasource.",
                "raw_data": []
            }

        return {
            "answer": content,
            "tool_used": "Direct Answer",
            "trace": "Image analyzed.",
            "raw_data": []
        }

    def _detect_chart_type_static(self, user_query: str) -> str:
        q = user_query.lower()
        if any(w in q for w in ['line chart', 'line graph', 'trend', 'over time', 'time series']): return 'line'
        if any(w in q for w in ['scatter', 'correlation', 'vs ', 'versus']): return 'scatter'
        if any(w in q for w in ['pie chart', 'pie', 'proportion', 'share']): return 'pie'
        if any(w in q for w in ['histogram', 'distribution', 'frequency']): return 'histogram'
        if any(w in q for w in ['area chart', 'area graph']): return 'area'
        return 'bar'
