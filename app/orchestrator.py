from app.db.db_client import DBClient
from app.core.embedder import embedder_instance
from app.core.remote_llm import llm_instance
from app.db.vector_store import vector_store
from app.utils.logger import info, error, warning
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


    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """Formats recent chat turns into a string for LLM context."""
        if not history:
            return "No previous conversation."
        formatted = []
        for msg in history[-5:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            if len(content) > 500:
                content = content[:500] + "..."
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

        # 1. Define Standard Tools
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
            {
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
            }
        ]

        # 2. Build Universal Context
        context_parts =[]
        
        if use_db_context and getattr(self, "db", None) and self.db.engine:
            schema = self.db.get_schema()
            if schema:
                tables = {}
                for row in schema:
                    tables.setdefault(row['table_name'], []).append(f"{row['column_name']} ({row['data_type']})")
                context_parts.append("SQL DATABASE SCHEMA:\n" + "\n".join([f"- Table `{t}`: {', '.join(c)}" for t, c in tables.items()]))
                
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

        system_msg = (
            "You are a Data Analyst Agent in a Pyodide notebook. EVERY code you generate MUST be Pyodide-compatible.\n\n"
            "CRITICAL PYODIDE RULES (ALWAYS FOLLOW):\n"
            "- NEVER import micropip - it's already available\n"
            "- NEVER use f-strings with formatting ({:,}, {:.2f}) - use string concatenation instead\n"
            "- NEVER use fig.show() or plt.show() - just return the figure\n"
            "- NEVER use pd.read_excel() - use pd.read_csv(io.StringIO(dataset_string))\n"
            "- ALWAYS use await for async operations (query_db, micropip.install)\n"
            "- CRITICAL: The LAST LINE must be OUTSIDE all conditionals (if/else/for/while) - this is how Pyodide displays output\n\n"
            "CELL CONTEXT:\n"
            "- Each cell has an ID like [cell-1], [cell-2], etc.\n"
            "- When user says 'this cell', 'current cell', 'that code', they mean the ACTIVE CELL\n"
            "- Cell outputs show the last execution result\n"
            "- You can reference specific cells by their ID in your responses\n\n"
            f"{rag_tool_hint}"
            "TOOL USAGE:\n"
            "1. LIST/TABLE REQUESTS: Use `run_sql` tool (system will convert to display code)\n"
            "   - User says 'list', 'show', 'display', 'table', 'retrieve', 'get', 'fetch' → Use run_sql\n"
            "   - System will automatically convert to generate_code for nice table display\n"
            "2. CHARTS/PLOTS: ALWAYS use `generate_code` with PLOTLY go.Figure (NOT px.express)\n"
            "   - User says 'chart', 'plot', 'graph', 'visualize' → MUST use go.Figure pattern\n"
            "   - NEVER just print data - ALWAYS create visual charts\n"
            "3. ANALYSIS: Use `generate_code` for Python code\n"
            "4. FILE DATA: Use `generate_code` with pd.read_csv(io.StringIO(dataset_string))\n"
            "5. DATABASE:\n"
            "   - ALWAYS use `generate_code` with await query_db('SELECT...') to fetch REAL data\n"
            "   - NEVER create sample/dummy data - always query the actual database\n"
            "6. SEARCH: Use `search_knowledge` for documents\n\n"
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
            "- For listing columns in a table:\n"
            "  * PostgreSQL: SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'YOUR_TABLE_NAME' ORDER BY ordinal_position;\n"
            "  * MySQL: SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_NAME = 'YOUR_TABLE_NAME' AND TABLE_SCHEMA = DATABASE();\n"
            "  * SQLite: PRAGMA table_info(YOUR_TABLE_NAME);\n"
            "- CRITICAL: Replace 'YOUR_TABLE_NAME' with the actual table name from the user's request\n"
            "- NEVER use PRAGMA syntax for PostgreSQL or MySQL - it only works in SQLite\n"
            "- NEVER query information_schema itself - query the actual table name the user asked about\n\n"
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
            "RULES:\n"
            "- Keep code simple and focused\n"
            "- If user asks for visualization, ALWAYS create one - don't just print data\n"
            "- If user asks for a list/table, use run_sql tool (system handles display)\n"
        )
        
        if is_modification and original_code:
            system_msg += f"\nMODIFICATION REQUEST: Use `generate_code` to output the modified version of:\n```python\n{original_code}\n```"

        user_msg = f"User Request: {user_query}\n\nENVIRONMENT CONTEXT:\n" + "\n\n".join(context_parts)
        if chat_history:
            user_msg = f"Previous Chat History:\n{self._format_history(chat_history)}\n\n{user_msg}"

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

                # Fix column listing queries to use correct DB syntax and actual table names
                if any(word in user_query_lower for word in ['column', 'columns', 'field', 'fields', 'schema']):
                    sql_query = self._fix_column_query(sql_query, user_query)

                wants_visualization = any(word in user_query_lower for word in [
                    'chart', 'plot', 'graph', 'visualize', 'visualization',
                    'line chart', 'bar chart', 'scatter', 'pie chart', 'histogram'
                ])
                wants_notebook_code = any(word in user_query_lower for word in [
                    'code', 'python', 'notebook', 'cell', 'write code', 'show me how'
                ])

                if wants_visualization:
                    fixed_query = self._fix_table_names(self._fix_column_query(sql_query, user_query))
                    python_code = f"""# {explanation}
import plotly.graph_objects as go

df = await query_db('''{fixed_query}''')

if df is not None and not df.empty:
    x_col = df.columns[0]
    y_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    fig = go.Figure(
        data=go.Bar(x=df[x_col], y=df[y_col], name=y_col, marker_color='#667eea')
    )
    fig.update_layout(
        title='{explanation}',
        xaxis_title=x_col,
        yaxis_title=y_col,
        template='plotly_white',
        height=400
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
                    fixed_query = self._fix_table_names(self._fix_column_query(sql_query, user_query))
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
                    # Wrap SQL in a Pyodide query_db cell so the user gets a live DataFrame
                    python_code = f"""# {explanation}
df = await query_db('''{sql_query}''')

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