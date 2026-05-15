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



PYODIDE_PRELOADED = {"numpy", "pandas", "matplotlib", "micropip", "pyodide", "plotly", "plotly.express"}

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
    "plt": "matplotlib.pyplot alias (matplotlib is already imported, plt.show() is a no-op â€” plots are captured automatically)",
    "query_db": "async function â€” use: df = await query_db('SELECT ...')",
}

PYODIDE_SYSTEM_CONTEXT = (
    "ENVIRONMENT: Pyodide â€” Python in a WebAssembly browser sandbox.\n"
    "ALREADY IN SCOPE (never re-import): np=numpy  pd=pandas  plt=matplotlib.pyplot  query_db=async-DB-fn  micropip  go=plotly.graph_objects  px=plotly.express  pio=plotly.io  make_subplots=plotly.subplots.make_subplots.\n"
    "SAFE IMPORTS: json re math random datetime io base64 os(read-only) mpl_toolkits.mplot3d.\n"
    "MICROPIP PACKAGES (await install before import): scikit-learn scipy seaborn pillow networkx.\n"
    "FORBIDDEN (will crash kernel): subprocess threading multiprocessing socket tkinter PyQt5 torch tensorflow cv2 open(local_path) pip-install matplotlib.animation FuncAnimation plt.show() fig.show().\n"
    "\n"
    "MANDATORY PYODIDE COMPATIBILITY RULES:\n"
    "1. NEVER import micropip - it's already available in scope\n"
    "2. NEVER import plotly or plotly.graph_objects - go is already in scope\n"
    "3. NEVER use f-strings with formatting specifiers ({:,}, {:.2f}, etc.) - they fail in Pyodide\n"
    "4. NEVER use fig.show() or plt.show() - just return the figure object\n"
    "5. NEVER use pd.read_excel() - use pd.read_csv(io.StringIO(dataset_string)) instead\n"
    "6. NEVER create hardcoded sample data - always use await query_db() for real data\n"
    "7. ALWAYS use simple string concatenation: print('text: ' + str(value)) NOT print(f'text: {value}')\n"
    "8. CRITICAL: The LAST LINE of code MUST be OUTSIDE all conditionals (if/else/for/while)\n"
    "9. ALWAYS use await for async operations like query_db()\n"
    "10. SQL STRING QUOTING: NEVER use triple-single-quotes for query_db() SQL strings that contain single quotes.\n"
    "    WRONG: df = await query_db('''SELECT * FROM t WHERE name = 'foo'''')\n"
    "    CORRECT: df = await query_db(\"SELECT * FROM t WHERE name = 'foo'\")\n"
    "    RULE: Always use double-quotes or triple-double-quotes for SQL strings: query_db(\"...\") or query_db(\"\"\"...\"\"\")\n"
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
    "- CRITICAL: ALWAYS use the actual column names from the query result â€” NEVER use generic placeholders like 'col1', 'col2'\n"
    "- CRITICAL: For bar/scatter charts, ALWAYS add hovertemplate using the real column names so tooltips show meaningful labels\n"
    "- CRITICAL: For bar charts, ALWAYS add text=df['metric_col'] and textposition='auto' to show values on bars\n"
    "\n"
    "AXIS SELECTION â€” decide x/y at code-generation time using the schema (NEVER use runtime column-detection):\n"
    "   X-AXIS signals (TEXT/VARCHAR/DATE columns, GROUP BY columns):\n"
    "     name, title, label, description, category, type, status, brand, region, country, city,\n"
    "     product, customer, segment, department, group, class, month, year, date, quarter, week, period\n"
    "   Y-AXIS signals (NUMERIC/INT/FLOAT columns, aggregate results), in priority order:\n"
    "     total_revenue, revenue, total_sales, sales, total_profit, profit,\n"
    "     units_sold, quantity_sold, total_quantity, quantity, amount,\n"
    "     avg_price, price, value, score, rating, count, total, avg, sum\n"
    "   FIELD MATCHING: exact ’ substring ’ semantic (e.g. 'price'’unit_price/buyPrice/MSRP, 'sold'’quantity_sold/units_sold)\n"
    "   CHART TYPE: bar=rankings/comparisons, line=time trends, scatter=correlation, pie=proportions(â‰¤8 cats), histogram=distribution\n"
    "\n"
    "PLOTLY TEMPLATE \u2014 BAR CHART (use for top-N, rankings, comparisons):\n"
    "import pandas as _pd\n"
    "df = await query_db(\"SELECT label_col, SUM(metric_col) AS metric FROM table GROUP BY label_col ORDER BY metric DESC LIMIT 10\")\n"
    "for _c in df.columns:\n"
    "    try: df[_c] = _pd.to_numeric(df[_c], errors='raise')\n"
    "    except: pass\n"
    "fig = go.Figure(\n"
    "    data=go.Bar(\n"
    "        x=df['label_col'].tolist(),\n"
    "        y=df['metric'].tolist(),\n"
    "        text=[round(float(v), 2) for v in df['metric']],\n"
    "        textposition='auto',\n"
    "        hovertemplate='<b>%{x}</b><br>metric: %{y:,.2f}<extra></extra>',\n"
    "        marker_color='#667eea'\n"
    "    )\n"
    ")\n"
    "fig.update_layout(title='Title', xaxis_title='Label', yaxis_title='Metric', template='plotly_white', height=400)\n"
    "fig  # <-- OUTSIDE all conditionals\n"
    "\n"
    "PLOTLY TEMPLATE \u2014 LINE/SCATTER CHART (use for trends over time):\n"
    "import pandas as _pd\n"
    "df = await query_db(\"SELECT date_col, SUM(metric_col) AS metric FROM table GROUP BY date_col ORDER BY date_col\")\n"
    "for _c in df.columns:\n"
    "    try: df[_c] = _pd.to_numeric(df[_c], errors='raise')\n"
    "    except: pass\n"
    "fig = go.Figure(\n"
    "    data=go.Scatter(\n"
    "        x=df['date_col'].tolist(),\n"
    "        y=df['metric'].tolist(),\n"
    "        mode='lines+markers',\n"
    "        name='metric',\n"
    "        hovertemplate='<b>%{x}</b><br>metric: %{y:,.2f}<extra></extra>',\n"
    "        line=dict(color='#667eea', width=2),\n"
    "        marker=dict(size=6)\n"
    "    )\n"
    ")\n"
    "fig.update_layout(title='Title', xaxis_title='Date', yaxis_title='Metric', hovermode='x unified', template='plotly_white', height=400)\n"
    "fig  # <-- OUTSIDE all conditionals\n"
    "\n"
    "PLOTLY TEMPLATE \u2014 ANIMATION (use for animated/time-lapse charts, NEVER use matplotlib FuncAnimation):\n"
    "CRITICAL: matplotlib.animation.FuncAnimation DOES NOT WORK in Pyodide. ALWAYS use Plotly frames instead.\n"
    "import pandas as _pd\n"
    "df = await query_db(\"SELECT time_col, label_col, metric_col FROM table ORDER BY time_col\")\n"
    "for _c in df.columns:\n"
    "    try: df[_c] = _pd.to_numeric(df[_c], errors='raise')\n"
    "    except: pass\n"
    "time_steps = sorted(df['time_col'].unique().tolist())\n"
    "frames = [go.Frame(\n"
    "    data=[go.Bar(x=df[df['time_col']==t]['label_col'].tolist(), y=df[df['time_col']==t]['metric_col'].tolist())],\n"
    "    name=str(t)\n"
    ") for t in time_steps]\n"
    "fig = go.Figure(\n"
    "    data=[go.Bar(x=df[df['time_col']==time_steps[0]]['label_col'].tolist(), y=df[df['time_col']==time_steps[0]]['metric_col'].tolist())],\n"
    "    layout=go.Layout(\n"
    "        title='Animated Chart',\n"
    "        template='plotly_white',\n"
    "        height=500,\n"
    "        margin=dict(t=50, l=60, r=20, b=80),\n"
    "        updatemenus=[]  # Play/Pause button is injected automatically by the notebook renderer\n"
    "    ),\n"
    "    ),\n"
    "    frames=frames\n"
    ")\n"
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
        
        scrub_db=True  â€” strips SQL/schema content when DB context is off
        scrub_rag=True â€” strips RAG/document content when RAG context is off
        """
        if not history:
            return "No previous conversation."
        formatted = []
        for msg in history[-5:]:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            if scrub_db:
                import re
                content = re.sub(r'```(?:sql|python)[\s\S]*?```', '[code removed â€” DB context was on]', content)
                content = re.sub(r'await query_db\([^)]*\)', '[query removed]', content)
                content = re.sub(r'(?:Table|Column|Schema|SELECT|FROM|WHERE|GROUP BY|ORDER BY)[^\n]{0,200}', '', content, flags=re.IGNORECASE)
                content = content.strip()
            if scrub_rag:
                import re
                # Remove RAG chunk references and document-backed answers
                content = re.sub(r'\[[\w\s./]+\]:\s*.{0,300}', '[document context removed â€” RAG was on]', content)
                content = re.sub(r'(?:according to|based on|from the document|the document states)[^\n]{0,300}', '', content, flags=re.IGNORECASE)
                content = content.strip()
            if len(content) > 500:
                content = content[:500] + "..."
            if content:
                formatted.append(f"{role}: {content}")
        return "\n".join(formatted) if formatted else "No previous conversation."

    def _sanitize_for_pyodide(self, code: str, fix_charts: bool = True) -> str:
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
            # fig.show() -> convert to comment so fig stays in scope for rendering
            if re.match(r'^fig\.show\(\s*\)$', stripped):
                sanitized.append('# fig.show() \u2014 display handled by notebook renderer')
                continue

            _SILENT_DROP_PATTERNS = [
                r'^import\s+numpy\s+as\s+np\s*$',
                r'^import\s+numpy\s*$',
                r'^import\s+pandas\s+as\s+pd\s*$',
                r'^import\s+pandas\s*$',
                r'^import\s+matplotlib\.pyplot\s+as\s+plt\s*$',
                r'^import\s+matplotlib\s*$',
                r'^import\s+matplotlib\.pyplot\s*$',
                r'^import\s+plotly\.graph_objects\s+as\s+go\s*$',
                r'^from\s+plotly\s+import\s+graph_objects\s+as\s+go\s*$',
                r'^import\s+plotly\.express\s+as\s+px\s*$',
                r'^from\s+plotly\s+import\s+express\s+as\s+px\s*$',
                r'^\s*from\s+plotly\.subplots\s+import\s+make_subplots\s*$',
                r'^\s*import\s+plotly\.subplots\s*$',
                r'^\s*import\s+plotly\.io\s+as\s+pio\s*$',
                r'^\s*from\s+mpl_toolkits\.mplot3d\s+import\s+Axes3D\s*$',
                r'^\s*import\s+mpl_toolkits\.mplot3d\s*$',
                r'^\s*import\s+plotly\.io\s*$',
            ]
            if any(re.match(p, stripped) for p in _SILENT_DROP_PATTERNS):
                continue  

            # Block matplotlib.animation imports and FuncAnimation usage
            if re.search(r'\bmatplotlib\.animation\b', stripped) or re.search(r'\bFuncAnimation\b', stripped):
                sanitized.append('# ❌ BLOCKED: matplotlib.animation.FuncAnimation does not work in Pyodide — use Plotly frames-based animation instead')
                continue

            forbidden_match = re.match(r'^(?:import|from)\s+(\w+)', stripped)
            if forbidden_match:
                module_root = forbidden_match.group(1)
                if module_root in PYODIDE_UNAVAILABLE:
                    sanitized.append(f"# âŒ '{module_root}' is not available in Pyodide (browser sandbox) â€” line removed")
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
                sanitized.append(f"# âŒ BLOCKED: subprocess calls are not available in Pyodide")
                continue
            if re.search(r'\bos\.system\s*\(', stripped):
                sanitized.append(f"# âŒ BLOCKED: os.system() is not available in Pyodide")
                continue

            sanitized.append(line)

        result = "\n".join(sanitized)

        if needs_micropip_import and "import micropip" not in result:
            result = "import micropip\n" + result

        # Fix SQL strings that use triple-quotes but contain single quotes inside,
        # e.g. query_db('''SHOW TABLES LIKE 'foo'''') ’ query_db("SHOW TABLES LIKE 'foo'")
        result = self._fix_sql_string_quoting(result)

        # Fix broken chart patterns (same column on both axes, bad layout overrides, etc.)
        # Only run on LLM-generated code, not on code we built ourselves
        if fix_charts:
            result = self._fix_chart_code(result)

        return result.strip()

    def _fix_chart_code(self, code: str) -> str:
        """
        Detect and fix common LLM chart generation mistakes.
        When the _label_hints / runtime column-detection pattern is detected,
        completely replace the chart block with clean generated code.
        """

        # â”€â”€ Detect the _label_hints anti-pattern â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # If the LLM generated runtime column-detection code, rip it all out and
        # rebuild a clean chart from the SQL query that's already in the code.
        if '_label_hints' in code or '_value_hints_ranked' in code or '_score_col' in code:
            code = self._rebuild_chart_from_sql(code)
            return code

        # â”€â”€ Fix update_layout: remove xaxis=dict(...) and yaxis=dict(...) â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # These override xaxis_title/yaxis_title and crash on text columns.
        # Use a bracket-aware replacer instead of a simple regex.
        code = self._strip_layout_dict_overrides(code)

        # â”€â”€ Fix SELECT DISTINCT single-column ’ proper aggregate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        def _fix_distinct(m):
            col = m.group(1).strip()
            table = m.group(2).strip()
            return f'SELECT {col}, COUNT(*) AS count FROM {table} GROUP BY {col} ORDER BY count DESC'
        code = re.sub(
            r'SELECT\s+DISTINCT\s+(\w+)\s+FROM\s+(\w+)',
            _fix_distinct, code, flags=re.IGNORECASE
        )

        # â”€â”€ Fix same column on both x= and y= â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        same_axis = re.compile(
            r"x\s*=\s*df\[['\"](\w+)['\"]\][\s\S]{0,200}?y\s*=\s*df\[['\"](\1)['\"]\]",
            re.DOTALL
        )
        if same_axis.search(code):
            code = self._fix_single_column_chart_sql(code)

        return code

    def _strip_layout_dict_overrides(self, code: str) -> str:
        """
        Remove xaxis=dict(...) and yaxis=dict(...) kwargs from fig.update_layout(...)
        using a bracket-depth-aware parser so nested parens don't confuse the regex.
        """
        result = []
        i = 0
        while i < len(code):
            # Find next fig.update_layout(
            start = code.find('fig.update_layout(', i)
            if start == -1:
                result.append(code[i:])
                break
            result.append(code[i:start])

            # Walk forward to find the matching closing paren
            depth = 0
            j = start + len('fig.update_layout(') - 1  # points at '('
            while j < len(code):
                if code[j] == '(':
                    depth += 1
                elif code[j] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1

            layout_inner = code[start + len('fig.update_layout('):j]

            # Remove xaxis=dict(...) â€” bracket-aware
            layout_inner = self._remove_kwarg_dict(layout_inner, 'xaxis')
            # Remove yaxis=dict(...) â€” bracket-aware
            layout_inner = self._remove_kwarg_dict(layout_inner, 'yaxis')
            # Clean up double commas / leading-trailing commas
            layout_inner = re.sub(r',\s*,', ',', layout_inner)
            layout_inner = layout_inner.strip().strip(',').strip()

            result.append(f'fig.update_layout({layout_inner})')
            i = j + 1

        return ''.join(result)

    def _remove_kwarg_dict(self, args: str, kwarg: str) -> str:
        """
        Remove `kwarg=dict(...)` from a function argument string,
        handling nested parentheses correctly.
        """
        pattern = re.compile(r',?\s*\b' + re.escape(kwarg) + r'\s*=\s*dict\s*\(')
        m = pattern.search(args)
        if not m:
            return args
        # Walk forward from the opening paren to find the matching close
        start = m.start()
        paren_start = args.index('(', m.end() - 1)
        depth = 0
        j = paren_start
        while j < len(args):
            if args[j] == '(':
                depth += 1
            elif args[j] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        return args[:start] + args[j + 1:]

    def _rebuild_chart_from_sql(self, code: str) -> str:
        """
        When the LLM generates _label_hints / runtime column-detection code,
        extract the SQL query and rebuild a clean, correct chart from scratch.
        """
        # Extract the SQL from the query_db call
        sql_match = re.search(
            r'await\s+query_db\s*\(\s*(?:\'\'\'|"""|\'|")([\s\S]*?)(?:\'\'\'|"""|\'|")\s*\)',
            code
        )
        if not sql_match:
            return code  # Can't fix without SQL

        sql = sql_match.group(1).strip().rstrip(';')

        # Extract SELECT columns to determine x and y
        select_match = re.match(r'SELECT\s+([\s\S]+?)\s+FROM\s+(\w+)', sql, re.IGNORECASE)
        if not select_match:
            return code

        select_clause = select_match.group(1)
        table = select_match.group(2)

        # Parse columns: split by comma, handle aliases
        raw_cols = [c.strip() for c in select_clause.split(',')]
        cols = []
        for c in raw_cols:
            # Get alias if present (e.g. "SUM(revenue) AS total_revenue" ’ "total_revenue")
            alias_match = re.search(r'\bAS\s+(\w+)\s*$', c, re.IGNORECASE)
            if alias_match:
                cols.append(alias_match.group(1))
            else:
                # Plain column name â€” strip any function wrapper
                plain = re.sub(r'^\w+\s*\(([^)]+)\)', r'\1', c).strip()
                cols.append(plain.split('.')[-1])  # strip table prefix

        if len(cols) < 2:
            # Single column â€” make it a count query
            col = cols[0] if cols else '*'
            sql = f'SELECT {col}, COUNT(*) AS count FROM {table} GROUP BY {col} ORDER BY count DESC LIMIT 20'
            x_col = col
            y_col = 'count'
        else:
            x_col = cols[0]
            y_col = cols[1]

        # Extract title from the original code if present
        title_match = re.search(r"title\s*=\s*['\"]([^'\"]+)['\"]", code)
        title = title_match.group(1) if title_match else f'{y_col} by {x_col}'

        # Build clean chart code
        clean = f'''df = await query_db("""{sql}""")
if df is not None and not df.empty:
    import pandas as _pd
    for _c in df.columns:
        try: df[_c] = _pd.to_numeric(df[_c], errors='raise')
        except (ValueError, TypeError): pass
    df = df.sort_values('{y_col}', ascending=False).head(15)
    df = df.reset_index(drop=True)
    fig = go.Figure(data=go.Bar(
        x=df['{x_col}'].tolist(),
        y=df['{y_col}'].tolist(),
        text=[round(float(v), 2) for v in df['{y_col}']],
        textposition='auto',
        hovertemplate='<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>',
        marker_color='#2563eb'
    ))
    fig.update_layout(
        title='{title}',
        xaxis_title='{x_col}',
        yaxis_title='{y_col}',
        template='plotly_white',
        height=450,
        xaxis_tickangle=-35
    )
else:
    fig = go.Figure()
    print("No data returned")
fig'''

        return clean

    def _fix_single_column_chart_sql(self, code: str) -> str:
        """
        When the LLM generates a chart where x and y use the same column,
        the SQL is almost always a single-column SELECT (DISTINCT or plain).
        Rewrite it to a proper COUNT(*) aggregate so the chart has real data.
        """
        # Find the query_db call and extract the SQL
        sql_match = re.search(
            r'(await\s+query_db\s*\(\s*(?:\'\'\'|"""|\'|"))([\s\S]*?)(\s*(?:\'\'\'|"""|\'|")\s*\))',
            code
        )
        if not sql_match:
            return code

        sql = sql_match.group(2).strip()

        # Only fix if it's a single-column SELECT (with or without DISTINCT)
        single_col = re.match(
            r'SELECT\s+(?:DISTINCT\s+)?(\w+)\s+FROM\s+(\w+)\s*;?\s*$',
            sql.strip(),
            re.IGNORECASE
        )
        if not single_col:
            return code

        col = single_col.group(1)
        table = single_col.group(2)
        new_sql = f'SELECT {col}, COUNT(*) AS count FROM {table} GROUP BY {col} ORDER BY count DESC LIMIT 20'

        # Replace the SQL in the query_db call
        code = code[:sql_match.start(2)] + new_sql + code[sql_match.end(2):]

        # Now fix the go.Bar/go.Scatter to use y=df['count']
        code = re.sub(
            r"(y\s*=\s*df\[['\"])" + re.escape(col) + r"(['\"]]\s*)",
            r"\g<1>count\2",
            code
        )
        # Fix hovertemplate y reference
        code = re.sub(
            r"(hovertemplate\s*=\s*['\"].*?)<br>" + re.escape(col) + r":",
            r"\g<1><br>count:",
            code
        )
        # Fix text= if it also uses the same column
        code = re.sub(
            r"(text\s*=\s*df\[['\"])" + re.escape(col) + r"(['\"]]\s*)",
            r"\g<1>count\2",
            code
        )
        # Fix yaxis_title
        code = re.sub(
            r"(yaxis_title\s*=\s*['\"])" + re.escape(col) + r"(['\"])",
            r"\g<1>count\2",
            code
        )

        return code

    def _fix_sql_string_quoting(self, code: str) -> str:
        """
        Fix SQL strings passed to query_db() that use triple-quotes but contain
        single quotes inside, causing Python syntax errors.

        e.g. query_db('''SHOW TABLES LIKE 'foo'''')
          ’  query_db("SHOW TABLES LIKE 'foo'")

        Strategy: find all query_db('''...''') calls and rewrite them as
        query_db("...") using double-quoted strings (safe since SQL values
        use single quotes).
        """
        # Match query_db(   '''...'''   ) â€” the SQL may span multiple lines
        triple_sq = re.compile(
            r"(await\s+query_db\s*\(\s*)('{3})([\s\S]*?)('{3})(\s*\))",
            re.DOTALL
        )
        def _replace_triple_sq(m):
            sql = m.group(3)
            # Escape any double-quotes already in the SQL (rare but safe)
            sql = sql.replace('"', '\\"')
            return f'{m.group(1)}"""{sql}"""{m.group(5)}'

        code = triple_sq.sub(_replace_triple_sq, code)

        # Same fix for triple double-quotes that contain double-quotes (less common)
        triple_dq = re.compile(
            r'(await\s+query_db\s*\(\s*)("""{1})([\s\S]*?)("""{1})(\s*\))',
            re.DOTALL
        )
        # triple_dq is fine as-is unless it contains unescaped """, which is very rare.
        # No action needed for that case.

        return code

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

            # Exact match â€” already correct
            if token in actual_tables:
                return m.group(0)

            # Case-insensitive exact match
            for t in actual_tables:
                if t.lower() == token_lower:
                    return f"{keyword} {quote}{t}{quote}"

            # Fuzzy: token is a prefix/substring of an actual table name
            for t in actual_tables:
                if len(token) > 3 and token_lower in t.lower():
                    info(f"Table name fix: '{token}' ’ '{t}'")
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
        info(f"Fixed column query: '{table_name}' ’ {self._get_db_type()} syntax")
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

        # Must be short â€” not a new data request
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
        """Validate SQL using EXPLAIN and auto-fix with LLM if invalid, injecting the real schema."""
        try:
            if getattr(self, "db", None) and self.db.engine:
                with self.db.engine.connect() as conn:
                    db_url = str(self.db.engine.url).lower()
                    if 'sqlite' in db_url:
                        conn.execute(text(f"EXPLAIN QUERY PLAN {sql_query}"))
                    else:
                        conn.execute(text(f"EXPLAIN {sql_query}"))
        except Exception as explain_err:
            # Build schema context so the LLM can fix with real column names
            schema_context = ""
            try:
                schema = self.db.get_schema()
                if schema:
                    # Group by table
                    tables: dict = {}
                    for row in schema:
                        t = row['table_name']
                        tables.setdefault(t, []).append(f"{row['column_name']} ({row['data_type']})")
                    schema_context = "DATABASE SCHEMA (use ONLY these columns):\n"
                    for tbl, cols in tables.items():
                        schema_context += f"  {tbl}: {', '.join(cols)}\n"
            except Exception:
                pass

            fix_prompt = (
                f"{schema_context}\n"
                f"The following SQL query has an error: {explain_err}\n\n"
                f"Original SQL:\n{sql_query}\n\n"
                f"Fix the SQL query using ONLY the columns that exist in the schema above.\n"
                f"Output ONLY the corrected raw SQL, nothing else."
            )
            fix_resp = self.llm.generate(
                "You are a SQL expert. Fix the SQL using only columns from the provided schema. Output only raw SQL.",
                fix_prompt
            )
            fixed = fix_resp if isinstance(fix_resp, str) else fix_resp.get("content", "")
            fixed = re.sub(r"```(?:sql)?|```", "", fixed).strip()
            if fixed.upper().startswith("SELECT") or fixed.upper().startswith("WITH"):
                info(f"SQL auto-fixed by LLM: {fixed[:120]}")
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
                "answer": f"Could you be more specific? For example:\n- Which table or metric are you interested in? (Available: {table_list})\n- What time period or filters should I apply?\n- What format do you want â€” a table, chart, or summary?",
                "tool_used": "Direct Answer",
                "trace": "Vague query â€” asked for clarification.",
                "raw_data": []
            }

        # Check for conversational follow-ups â€” answer directly without tools
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
                "factually â€” e.g. if asked 'is the chart showing 10 items?', check if LIMIT 10 "
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

        # 1. Define Standard Tools â€” only include search_knowledge when RAG is ON
        tools = []

        # Only expose run_sql when DB context is ON and a connection exists
        if use_db_context and getattr(self, "db", None) and self.db.engine:
            tools.append({
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
            })

        tools.append({
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
                    "required": ["python_code", "explanation"]
                }
            }
        })

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
                # Smart schema injection â€” score tables by relevance to user query
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
                        "\nâš ï¸ DATABASE: MySQL\n"
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
                        "\nâš ï¸ DATABASE: PostgreSQL\n"
                        "POSTGRESQL-SPECIFIC SQL RULES:\n"
                        "- Use DATE_TRUNC('month', date_col) for date truncation\n"
                        "- Use EXTRACT(YEAR FROM date_col) for date parts\n"
                        "- Use || for string concatenation\n"
                        "- To list all tables: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'\n"
                    )
                elif 'sqlite' in db_url.lower():
                    context_parts.append(
                        "\nâš ï¸ DATABASE: SQLite\n"
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
                rag_results = vector_store.search(query_vec, n_results=3)
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
            "\nâ›” DATABASE CONTEXT IS OFF: The user has disabled DB context.\n"
            "- Do NOT generate any SQL queries or query_db() calls\n"
            "- Do NOT reference any table names, column names, or schema from previous messages\n"
            "- Do NOT assume any database type (PostgreSQL, MySQL, etc.)\n"
            "- If the user asks about data, tell them to enable 'Use DB Context' toggle first\n"
            "- Answer only from general knowledge or uploaded files\n\n"
        ) if not use_db_context else ""

        no_rag_notice = (
            "\nâ›” RAG CONTEXT IS OFF: The user has disabled document search.\n"
            "- Do NOT use the search_knowledge tool\n"
            "- Do NOT reference any document content or uploaded file knowledge from previous messages\n"
            "- If the user asks about document content, tell them to enable 'Use RAG' toggle first\n\n"
        ) if not use_rag_context else ""

        system_msg = (
            "You are a Data Analyst Agent in a Pyodide notebook. EVERY code you generate MUST be Pyodide-compatible.\n\n"
            f"{no_db_notice}"
            f"{no_rag_notice}"
            f"{PYODIDE_SYSTEM_CONTEXT}\n"
            "CELL CONTEXT:\n"
            "- Each cell has an ID like [cell-1], [cell-2], etc.\n"
            "- When user says 'this cell', 'current cell', 'that code', they mean the ACTIVE CELL\n"
            "- Cell outputs show the last execution result\n"
            "- You can reference specific cells by their ID in your responses\n\n"
            f"{rag_tool_hint}"
            "TOOL USAGE â€” DECISION TREE (follow in order):\n"
            "\n"
            "0. ANSWER DIRECTLY (NO TOOL) â€” use plain text response for:\n"
            "   - Greetings, thanks, clarifications, follow-up questions\n"
            "   - Questions about schema/columns/tables that are ALREADY in the context above (e.g. 'is there a column named X?' ’ check schema and answer yes/no)\n"
            "   - Questions about existing notebook cells or charts (e.g. 'is the chart showing 10 items?', 'what does this cell do?', 'is this correct?' ’ read the cell code and answer)\n"
            "   - Questions about the datasource name, connection, or database type ’ answer from ACTIVE DATASOURCE NAME in context\n"
            "   - Explaining what was done in a previous cell\n"
            "   - Correcting yourself or acknowledging a mistake\n"
            "   - Any yes/no or factual question answerable from the schema or cell context without running new code\n"
            "   RULE: If the answer is already visible in the SQL DATABASE SCHEMA, EXACT TABLE NAMES, ACTIVE DATASOURCE NAME, or RECENT NOTEBOOK CELLS above, NEVER use a tool â€” just answer in plain text.\n"
            "   CRITICAL EXAMPLES that MUST be answered directly (no code, no tool):\n"
            "     'what is in the data?' ’ list the tables and key columns from the schema\n"
            "     'what is the name of my datasource?' ’ read ACTIVE DATASOURCE NAME from context\n"
            "     'it doesn't have columns or tables' ’ explain what tables/columns ARE in the schema\n"
            "     'why no visuals are available?' ’ explain based on what the previous cells returned\n"
            "     'is the chart showing only 10 products?' ’ look at the LIMIT in the cell code, answer yes/no\n"
            "     'is this correct?' ’ evaluate the code/output and explain\n"
            "     'what does this query do?' ’ explain it\n"
            "     'why did you use GROUP BY?' ’ explain the reasoning\n"
            "\n"
            "1. CHARTS/PLOTS ’ `generate_code` with Plotly go.Figure\n"
            "   - Triggered by: 'chart', 'plot', 'graph', 'visualize', 'histogram', 'scatter'\n"
            "   - Also triggered by: 'top N', 'ranking', 'compare', 'breakdown', 'distribution'\n"
            "   - ALWAYS use go.Figure (NOT px.express)\n"
            "   - For 'top N' queries: if N is not specified, default to top 10 and mention it\n"
            "   - For 'top N brands/products/categories': use ORDER BY total DESC LIMIT N pattern\n"
            "\n"
            "2. DATA RETRIEVAL / ANALYSIS ’ `run_sql` or `generate_code`\n"
            "   - Triggered by: 'show me the data', 'get rows', 'fetch records', 'count', 'sum', 'average', 'group by'\n"
            "   - Use `run_sql` for simple SELECT queries\n"
            "   - Use `generate_code` for multi-step Python analysis\n"
            "\n"
            "3. DOCUMENT SEARCH ’ `search_knowledge`\n"
            "   - Only when user asks about uploaded documents/PDFs\n"
            "\n"
            "TOP N / CHART QUERY RULES (UNIVERSAL):\n"
            "   These rules apply to ANY chart or top-N request regardless of the datasource:\n"
            "\n"
            "   1. METRIC SELECTION â€” look at the schema and pick the most meaningful numeric column:\n"
            "      - If a 'sales', 'orders', or 'transactions' table exists ’ prefer SUM(revenue), SUM(amount), SUM(quantity_sold)\n"
            "      - If only a product/item table exists ’ prefer AVG(price), SUM(stock), MAX(rating)\n"
            "      - NEVER use COUNT(*) or COUNT(id) as the primary metric unless user explicitly says 'count' or 'how many'\n"
            "      - When user says 'top N X' with no metric ’ infer the most meaningful metric from the schema\n"
            "        (e.g. 'top brands' ’ revenue or quantity sold, 'top products' ’ revenue or rating, 'top customers' ’ total spend)\n"
            "\n"
            "   2. SQL STRUCTURE â€” always: label column first, ONE aggregated metric second\n"
            "      SELECT <label_col>, <AGG_FUNCTION>(<metric_col>) AS <alias>\n"
            "      FROM <table(s)>\n"
            "      [JOIN if needed to get label or metric from another table]\n"
            "      GROUP BY <label_col>\n"
            "      ORDER BY <alias> DESC\n"
            "      LIMIT <N>\n"
            "\n"
            "   3. JOINS â€” always JOIN when the label and metric are in different tables\n"
            "      (e.g. brand name is in products, revenue is in sales ’ JOIN products ON sales.product_id = products.product_id)\n"
            "\n"
            "   4. AGGREGATION â€” always aggregate for charts. Never use raw unaggregated rows.\n"
            "\n"
            "   5. N DEFAULT â€” if N is not specified, default to 10\n"
            "\n"
            "AXIS SELECTION RULES (CRITICAL â€” decide x/y at code-generation time using the schema):\n"
            "   You MUST decide which column is the X-axis (label/category) and which is the Y-axis (metric/value)\n"
            "   BEFORE writing any code. Use these rules in order:\n"
            "\n"
            "   X-AXIS (label/category column) â€” pick the column that best matches these signals:\n"
            "      STRONG signals (use if present): name, title, label, description, category, type, status,\n"
            "        brand, region, country, city, product, customer, segment, department, group, class,\n"
            "        month, year, date, quarter, week, period, day\n"
            "      MEDIUM signals: id columns that are clearly categorical (e.g. order_status, priority)\n"
            "      RULE: If the column is TEXT / VARCHAR / DATE ’ it is almost always the X-axis\n"
            "      RULE: If the column is the result of GROUP BY ’ it is the X-axis\n"
            "\n"
            "   Y-AXIS (metric/value column) â€” pick the column that best matches these signals:\n"
            "      STRONG signals (use if present, in priority order):\n"
            "        total_revenue, revenue, total_sales, sales, total_profit, profit,\n"
            "        units_sold, quantity_sold, total_quantity, quantity, amount,\n"
            "        avg_price, price, value, score, rating, count, total, avg, sum\n"
            "      RULE: If the column is NUMERIC / INT / FLOAT / DECIMAL ’ it is almost always the Y-axis\n"
            "      RULE: If the column is the result of an aggregate (SUM, COUNT, AVG, MAX) ’ it is the Y-axis\n"
            "      RULE: Prefer aggregated/derived columns (e.g. total_revenue) over raw IDs\n"
            "\n"
            "   FIELD MATCHING â€” map user terms to actual schema columns using:\n"
            "      1. Exact match: user says 'revenue' ’ column is 'revenue'\n"
            "      2. Substring match: user says 'price' ’ match 'unit_price', 'sale_price', 'buyPrice', 'MSRP'\n"
            "      3. Semantic match: user says 'sold' ’ match 'quantity_sold', 'units_sold', 'qty', 'amount_sold'\n"
            "                         user says 'name' ’ match 'product_name', 'customer_name', 'brand', 'title'\n"
            "                         user says 'total' ’ match 'total_amount', 'grand_total', 'order_total'\n"
            "      4. Calculated: user says 'revenue' but no revenue column ’ SUM(price * quantity)\n"
            "\n"
            "   CHART TYPE SELECTION:\n"
            "      - Bar chart (go.Bar): rankings, comparisons, counts by category, top-N\n"
            "      - Line chart (go.Scatter mode='lines+markers'): trends over time, time series\n"
            "      - Scatter plot (go.Scatter mode='markers'): correlation between two numeric columns\n"
            "      - Pie chart (go.Pie): proportions/shares of a whole (use only if â‰¤8 categories)\n"
            "      - Histogram (go.Histogram): distribution of a single numeric column\n"
            "      - Default to bar chart if chart type is not specified\n"
            "\n"
            "CRITICAL PLOTTING RULES (TESTED & WORKING):\n"
            "- When user asks for 'line chart', 'bar chart', 'scatter plot', etc. ’ MUST create Plotly visualization\n"
            "- ALWAYS use go.Figure pattern (NOT px.express) - it renders reliably in Pyodide\n"
            "- go is ALREADY IN SCOPE â€” NEVER write 'import plotly' or 'import plotly.graph_objects as go'\n"
            "- Use go.Scatter for line/scatter, go.Bar for bar charts, go.Histogram for histograms\n"
            "- Add clear titles and axis labels using the actual column names\n"
            "- CRITICAL: Return fig object at the end - NEVER use fig.show() in Pyodide!\n"
            "- CORRECT: fig (just return the figure on its own line OUTSIDE conditionals)\n"
            "- WRONG: fig.show() (doesn't work in Pyodide)\n"
            "- WRONG: Using px.express (use go.Figure instead)\n"
            "- WRONG: Putting fig inside an if block (must be at end of cell)\n"
            "- CRITICAL: ALWAYS use actual column names from the query â€” NEVER use 'col1', 'col2' or other placeholders\n"
            "- CRITICAL: For bar charts, ALWAYS include text=df['y_col'], textposition='auto' to show values on bars\n"
            "- CRITICAL: ALWAYS add hovertemplate with real column names so hover tooltips show meaningful labels\n"
            "  Example bar: hovertemplate='<b>%{x}</b><br>Revenue: %{y:,.2f}<extra></extra>'\n"
            "  Example line: hovertemplate='<b>%{x}</b><br>Sales: %{y:,.2f}<extra></extra>'\n"
            "- FORBIDDEN PATTERN: NEVER write _label_hints, _value_hints_ranked, _score_col, or any dynamic column-detection logic.\n"
            "  The schema is provided â€” decide x/y columns yourself using the AXIS SELECTION RULES above.\n"
            "- FORBIDDEN: NEVER use SHOW TABLES, SHOW DATABASES, PRAGMA, or information_schema queries as chart data.\n"
            "  These return metadata, not plottable values. Always query the actual data table.\n"
            "- FORBIDDEN: NEVER check if a table exists before querying it. The schema is already provided â€” trust it.\n"
            "  WRONG: df = await query_db(\"SHOW TABLES LIKE 'sales'\")\n"
            "  CORRECT: df = await query_db(\"SELECT ... FROM sales ...\")\n\n"
            "DATABASE RULES:\n"
            "- When DB available, ALWAYS use await query_db() for real data\n"
            "- NEVER use hardcoded sample data\n"
            "- READ-ONLY: NEVER generate INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE or any write SQL\n"
            "- The database is read-only â€” any write attempt will be blocked by the server\n"
            "\n"
            "SQL GENERATION â€” CORE RULES:\n"
            "1. Use ONLY columns that exist in the provided schema â€” NEVER invent or assume column names\n"
            "2. Match user fields using: exact match ’ substring match ’ semantic similarity ’ calculated fields\n"
            "3. CRITICAL: Before adding ANY column to a query, verify it exists in the target table(s)\n"
            "4. NEVER mix columns from different tables unless explicitly using JOIN\n"
            "\n"
            "SCHEMA VALIDATION â€” ABSOLUTE REQUIREMENT:\n"
            "- BEFORE generating any SQL, carefully examine the EXACT schema provided\n"
            "- Every column name in your SQL MUST exist in the schema for the table(s) you're querying\n"
            "- NEVER assume a column exists just because it seems logical\n"
            "- If a column doesn't exist in the target table, you MUST either:\n"
            "    a) Find an equivalent column in that table, OR\n"
            "    b) Use JOIN to access the column from another table, OR\n"
            "    c) Tell the user the column doesn't exist and suggest alternatives\n"
            "\n"
            "FIELD MATCHING PRIORITY:\n"
            "- 'name' ’ product_name, customer_name, first_name, last_name, brand, title\n"
            "- 'price' ’ buyPrice, cost, MSRP, unit_price, sale_price\n"
            "- 'revenue' ’ revenue, sales, amount, total, income, SUM(price * quantity)\n"
            "- 'sold' ’ quantity_sold, units_sold, qty, amount_sold\n"
            "- 'total quantity ordered' ’ SUM(quantity) from order items table\n"
            "- ONLY raise an error if absolutely NO reasonable interpretation exists\n"
            "\n"
            "QUERY MODIFICATION â€” CRITICAL:\n"
            "- STEP 1: Identify which table(s) are in the previous query's FROM clause\n"
            "- STEP 2: Check the schema to see which columns exist in those specific table(s)\n"
            "- STEP 3: Only add columns that exist in the identified table(s)\n"
            "- Start with the EXACT previous SQL query as your base\n"
            "- Only modify the specific part requested (WHERE, ORDER BY, GROUP BY, etc.)\n"
            "- NEVER change SELECT columns or FROM clause unless explicitly asked\n"
            "- NEVER add columns from other tables without using JOIN\n"
            "- PRESERVE ALL existing clauses (WHERE, GROUP BY, HAVING, ORDER BY)\n"
            "\n"
            "GROUP BY RULES:\n"
            "- All non-aggregated SELECT columns MUST be in GROUP BY\n"
            "- When grouping by a new field, add aggregate functions to existing SELECT columns\n"
            "\n"
            "FORBIDDEN SQL PATTERNS (will cause errors):\n"
            "- NEVER use DESCRIBE, SHOW COLUMNS, SHOW TABLES, SHOW DATABASES as chart data queries\n"
            "  These return metadata, not plottable values. Use SELECT from the actual table.\n"
            "- NEVER check if a table exists before querying â€” the schema is already provided\n"
            "  WRONG: SHOW TABLES LIKE 'sales' or DESCRIBE SalesData\n"
            "  CORRECT: SELECT col1, SUM(col2) FROM SalesData GROUP BY col1\n"
            "- NEVER use PRAGMA syntax for MySQL or PostgreSQL\n"
            "- NEVER query information_schema as a data table\n"
            "- For listing columns: MySQL ’ SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_NAME='tbl' AND TABLE_SCHEMA=DATABASE()\n"
            "                       PostgreSQL ’ SELECT column_name FROM information_schema.columns WHERE table_name='tbl'\n"
            "                       SQLite ’ PRAGMA table_info(tbl)\n"
            "\n"
            "ERROR HANDLING:\n"
            "- ONLY return errors when NO reasonable field mapping exists\n"
            "- When error is needed: explain what's missing, list available fields, suggest 2-3 natural language alternatives\n"
            "- Suggestions must be in plain English â€” NEVER use SQL syntax in suggestions\n"
            "- If tables can be joined (share common keys), suggest JOIN-based queries using natural language\n"
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
            "- If user says 'change', 'modify', 'update', 'fix', 'edit', 'add', 'remove' about existing code ’ use generate_code tool with the MODIFIED version of the existing code\n"
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
        print(f"  â”œâ”€ ðŸ§  Building context: {len(context_parts)} parts included.")
        response = self.llm.generate(system_msg, user_msg, images=images, tools=tools)

        # 5. Handle Text Responses
        if isinstance(response, str) or response.get("type") == "text":
            return {
                "answer": response if isinstance(response, str) else response.get("content", "I am processing your request."),
                "tool_used": "Direct Answer",
                "trace": "LLM answered directly without tools.",
                "raw_data":[]
            }

        # 6. Execute Triggered Tools â€” delegate to shared _execute_tool
        elif response.get("type") == "tool_calls":
            tool_call = response["tool_calls"][0]
            name = tool_call.get("name")
            args = tool_call.get("arguments", {})
            llm_content = response.get("content", "")
            info(f"Agent selected tool: {name}")
            if isinstance(args, str):
                try: args = json.loads(args)
                except: args = {}

            return self._execute_tool(
                name, args, llm_content, user_query, is_modification,
                original_code, active_cell_id, use_db_context, use_rag_context
            )

        return {"answer": "Unexpected format.", "tool_used": "Error", "trace": "Parse error.", "raw_data": []}

    # =========================================================================
    # STREAMING VERSION â€” yields SSE-formatted JSON events
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
          {"type": "token",     "text": "..."}          â€” streaming text token
          {"type": "code",      "answer": "...", ...}    â€” final code/tool result
          {"type": "done",      "tool_used": "...", ...} â€” stream complete
          {"type": "error",     "message": "..."}        â€” error
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
                # Vague query or other early exit â€” stream the answer as tokens
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
                    # Don't yield yet â€” process the tool call first

                elif event["type"] == "done":
                    break

            # No tool call â€” pure text answer
            if tool_event is None:
                yield _sse({"type": "done", "tool_used": "Direct Answer",
                            "answer": accumulated_text, "trace": "", "raw_data": []})
                return

            # Process tool call â€” reuse existing tool execution logic
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
                                    joins.append(f"  {table}.{col} ’ {other_table}.id")
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
                "answer": f"Could you be more specific? For example:\n- Which table or metric are you interested in? (Available: {table_list})\n- What time period or filters should I apply?\n- What format do you want â€” a table, chart, or summary?",
                "tool_used": "Direct Answer",
                "trace": "Vague query â€” asked for clarification.",
            }

        # Build tools list
        tools = []

        # Only expose run_sql when DB context is ON and a connection exists
        if use_db_context and getattr(self, "db", None) and self.db.engine:
            tools.append({"type": "function", "function": {"name": "run_sql", "description": "Execute a SQL query against the connected database to retrieve raw data.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["query", "explanation"]}}})

        tools.append({"type": "function", "function": {"name": "generate_code", "description": "Generate Pyodide-compatible Python code to run in the notebook.", "parameters": {"type": "object", "properties": {"python_code": {"type": "string"}, "explanation": {"type": "string"}}, "required": ["python_code", "explanation"]}}})
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
                    context_parts.append("\nâš ï¸ DATABASE: PostgreSQL")
                elif 'mysql' in db_url:
                    context_parts.append("\nâš ï¸ DATABASE: MySQL")

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
                rr = vector_store.search(qv, n_results=3)
                if rr:
                    lines, total = [], 0
                    for r in rr:
                        line = f"[{r['source_name']}]: {r['chunk_text'][:300]}"
                        if total + len(line) > 1200: break
                        lines.append(line); total += len(line)
                    context_parts.append(f"RAG KNOWLEDGE BASE:\n" + "\n\n".join(lines))
            except: pass

        no_db = ("\nâ›” DATABASE CONTEXT IS OFF â€” do NOT generate SQL or reference schema.\n") if not use_db_context else ""
        no_rag = ("\nâ›” RAG CONTEXT IS OFF â€” do NOT use search_knowledge.\n") if not use_rag_context else ""
        rag_hint = ("\n- RAG ENABLED: use search_knowledge for document questions.\n") if use_rag_context else ""

        system_msg = (
            "You are a Data Analyst Agent in a Pyodide notebook.\n\n"
            f"{no_db}{no_rag}"
            f"{PYODIDE_SYSTEM_CONTEXT}\n\n"
            "TOOL USAGE:\n"
            "0. Answer directly (no tool) for: greetings, yes/no questions about existing cells/charts, schema questions already in context, follow-ups, corrections.\n"
            "   EXAMPLES: 'is the chart showing 10 items?' ’ read cell code, answer yes/no. 'is this correct?' ’ evaluate and explain.\n"
            "1. Charts/plots ’ generate_code with go.Figure\n"
            "2. Data retrieval ’ run_sql\n"
            "3. Documents ’ search_knowledge\n"
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

    def _build_chart_summary(self, explanation: str, chart_type: str, x_col: str, y_col: str,
                              sql: str, preview_data: list) -> str:
        """
        Build a concise, informative chart summary for the chat panel.
        Shows what the chart displays, key data points, and invites follow-up.
        """
        lines = []

        # Chart type label
        type_labels = {
            'bar': '📊 Bar chart', 'line': '📈 Line chart', 'scatter': '🔵 Scatter plot',
            'pie': '🥧 Pie chart', 'histogram': '📉 Histogram', 'area': '📈 Area chart'
        }
        label = type_labels.get(chart_type, '📊 Chart')
        lines.append(f"**{label}** — {explanation}")

        # Key data insights from preview
        if preview_data and len(preview_data) > 0:
            import decimal
            try:
                # Top value
                top = preview_data[0]
                top_label = str(top.get(x_col, ''))
                top_val = top.get(y_col)
                if top_val is not None:
                    top_val_f = float(top_val)
                    formatted = f"{top_val_f:,.2f}" if top_val_f != int(top_val_f) else f"{int(top_val_f):,}"
                    lines.append(f"**Highest:** {top_label} — {formatted}")

                # Row count
                lines.append(f"**Data points:** {len(preview_data)} {x_col} values shown")

                # Range if multiple rows
                if len(preview_data) >= 2:
                    bottom = preview_data[-1]
                    bot_val = bottom.get(y_col)
                    bot_label = str(bottom.get(x_col, ''))
                    if bot_val is not None:
                        bot_val_f = float(bot_val)
                        formatted_b = f"{bot_val_f:,.2f}" if bot_val_f != int(bot_val_f) else f"{int(bot_val_f):,}"
                        lines.append(f"**Lowest:** {bot_label} — {formatted_b}")
            except Exception:
                pass

        lines.append("\n*Ask me to change the chart type, filter by date, add more categories, or compare with another metric.*")
        return "\n\n".join(lines)

    def _ensure_chart_sql_has_metric(self, sql: str, user_query: str) -> str:
        """
        If the LLM generated a non-aggregated or DISTINCT-only query for a chart request,
        rewrite it to a proper aggregate query using the actual schema.

        Handles cases like:
          SELECT DISTINCT Region FROM SalesData
          SELECT Region FROM SalesData
          → SELECT Region, SUM(SaleAmount) AS total_SaleAmount FROM SalesData GROUP BY Region ORDER BY total_SaleAmount DESC LIMIT 20
        """
        sql_stripped = sql.strip()

        # Only fix SELECT queries
        if not re.match(r'^\s*SELECT\b', sql_stripped, re.IGNORECASE):
            return sql

        # Check if it's already aggregated (has GROUP BY or aggregate functions)
        has_group_by = bool(re.search(r'\bGROUP\s+BY\b', sql_stripped, re.IGNORECASE))
        has_agg = bool(re.search(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(', sql_stripped, re.IGNORECASE))
        if has_group_by or has_agg:
            return sql  # already a proper aggregate query

        # Extract table name
        tbl_match = re.search(r'\bFROM\s+[`"\']?(\w+)[`"\']?', sql_stripped, re.IGNORECASE)
        if not tbl_match:
            return sql
        table = tbl_match.group(1)

        # Extract the label column (first SELECT column, strip DISTINCT)
        select_match = re.match(r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM\b', sql_stripped, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return sql
        label_col = select_match.group(1).strip().split(',')[0].strip().strip('`"\'')

        # Find the best numeric metric column from the schema
        metric_col = None
        metric_alias = None
        if getattr(self, 'db', None) and self.db.engine:
            try:
                schema = self.db.get_schema()
                # Filter to columns in this table
                table_cols = [r for r in schema if r['table_name'].lower() == table.lower()]
                # Score by metric relevance
                metric_hints = ['amount', 'sale', 'revenue', 'total', 'price', 'profit',
                                 'quantity', 'qty', 'cost', 'value', 'score', 'count', 'sum']
                id_hints = re.compile(r'(^|_)(id|key|num|no|code|seq|pk|fk)$', re.IGNORECASE)
                numeric_types = {'int', 'float', 'double', 'decimal', 'numeric', 'bigint',
                                  'smallint', 'tinyint', 'real', 'money', 'number'}

                candidates = []
                for col in table_cols:
                    cname = col['column_name']
                    ctype = col['data_type'].lower()
                    if cname.lower() == label_col.lower():
                        continue
                    if id_hints.search(cname):
                        continue
                    is_numeric = any(t in ctype for t in numeric_types)
                    if not is_numeric:
                        continue
                    score = sum(1 for h in metric_hints if h in cname.lower())
                    candidates.append((score, cname))

                if candidates:
                    candidates.sort(reverse=True)
                    metric_col = candidates[0][1]
                    metric_alias = f"total_{metric_col}"
            except Exception:
                pass

        if metric_col:
            new_sql = (
                f"SELECT {label_col}, SUM({metric_col}) AS {metric_alias} "
                f"FROM {table} GROUP BY {label_col} "
                f"ORDER BY {metric_alias} DESC LIMIT 20"
            )
            info(f"📊 Rewrote non-aggregated chart SQL: {new_sql}")
            return new_sql
        else:
            # No numeric metric found — fall back to COUNT
            new_sql = (
                f"SELECT {label_col}, COUNT(*) AS count "
                f"FROM {table} GROUP BY {label_col} "
                f"ORDER BY count DESC LIMIT 20"
            )
            info(f"📊 Rewrote to COUNT chart SQL: {new_sql}")
            return new_sql

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

                # Reject DESCRIBE/SHOW/PRAGMA — metadata commands, not chart data
                _meta_pattern = re.compile(r'^\s*(DESCRIBE|DESC|SHOW\s+(COLUMNS|TABLES|DATABASES)|PRAGMA)\b', re.IGNORECASE)
                if _meta_pattern.match(fixed_query.strip()):
                    _tbl = re.search(r'(?:DESCRIBE|DESC|SHOW\s+COLUMNS\s+FROM|SHOW\s+TABLES\s+LIKE)\s+[`"\']?(\w+)[`"\']?', fixed_query, re.IGNORECASE)
                    if _tbl:
                        fixed_query = f"SELECT * FROM {_tbl.group(1)} LIMIT 100"

                # If the LLM generated a non-aggregated / DISTINCT query for a chart,
                # rewrite it to a proper aggregate using the schema
                fixed_query = self._ensure_chart_sql_has_metric(fixed_query, user_query)

                chart_type = self._detect_chart_type_static(user_query)

                # Run preview query to get real column names + sample data
                try:
                    _is_select = re.match(r'^\s*(SELECT|WITH)\b', fixed_query.strip(), re.IGNORECASE)
                    _has_limit = re.search(r'\bLIMIT\s+\d+', fixed_query, re.IGNORECASE)
                    preview_sql = (fixed_query + " LIMIT 5") if (_is_select and not _has_limit) else fixed_query
                    preview_data = self.db.execute_query(preview_sql)
                    info(f"📊 Chart preview SQL: {preview_sql}")
                    if preview_data:
                        info(f"📊 Chart preview top-2: {preview_data[:2]}")
                    else:
                        info("📊 Chart preview: no rows returned")
                except Exception as _prev_err:
                    info(f"📊 Chart preview failed: {_prev_err}")
                    preview_data = None

                if preview_data and len(preview_data) > 0:
                    cols = list(preview_data[0].keys())

                    # Pick x/y axes using heuristics — no extra LLM call needed
                    import decimal as _decimal
                    _id_pat = re.compile(r'(^|_)(id|key|num|no|code|seq|pk|fk|ref|uuid|guid)$', re.IGNORECASE)
                    _label_signals = ['name','title','label','product','category','brand','region',
                                      'country','city','month','date','year','type','status','description',
                                      'segment','department','customer','quarter','week','period']
                    _metric_priority = ['total_revenue','revenue','total_sales','sales','total_profit',
                                        'profit','units_sold','quantity_sold','quantity','amount',
                                        'total_amount','price','value','score','rating','count','total',
                                        'avg','sum','percent','rate']

                    # X-axis: prefer label-signal columns, then first non-numeric
                    x_col = None
                    for c in cols:
                        if any(h in c.lower() for h in _label_signals):
                            x_col = c; break
                    if not x_col:
                        for c in cols:
                            v = preview_data[0][c]
                            if not isinstance(v, (int, float, _decimal.Decimal)):
                                x_col = c; break
                    if not x_col:
                        x_col = cols[0]

                    # Y-axis: exclude x_col and ID columns, score by metric priority
                    numeric_cols = [
                        c for c in cols
                        if c != x_col
                        and not _id_pat.search(c)
                        and isinstance(preview_data[0][c], (int, float, _decimal.Decimal))
                    ]

                    def _score(col):
                        cl = col.lower()
                        for i, h in enumerate(_metric_priority):
                            if cl == h: return len(_metric_priority) - i + 20
                            if cl.startswith(h) or cl.endswith(h): return len(_metric_priority) - i + 10
                            if h in cl: return len(_metric_priority) - i
                        return 0

                    y_col_raw = max(numeric_cols, key=_score) if numeric_cols else None

                    if y_col_raw is None:
                        # No numeric metric — rewrite SQL to COUNT
                        tbl_match = re.search(r'\bFROM\s+[`"\']?(\w+)[`"\']?', fixed_query, re.IGNORECASE)
                        if tbl_match:
                            tbl = tbl_match.group(1)
                            fixed_query = f"SELECT {x_col}, COUNT(*) AS count FROM {tbl} GROUP BY {x_col} ORDER BY count DESC LIMIT 20"
                        y_col = 'count'
                    else:
                        y_col = y_col_raw

                    info(f"📊 Axis → x={x_col}  y={y_col}  (heuristic, no LLM call)")
                    info(f"📊 Final chart SQL: {fixed_query}")

                    # Detect color/style preferences from user query
                    style = self._detect_chart_style(user_query)
                    color = style['color'] or '#2563eb'
                    multi_color = style['multi_color']
                    colorscale = style['colorscale']

                    # Always compute r,g,b from the resolved color (used in fill/border rgba)
                    _hex = color.lstrip('#')
                    r, g, b = int(_hex[0:2], 16), int(_hex[2:4], 16), int(_hex[4:6], 16)

                    # Build color argument for each chart type
                    if multi_color and colorscale:
                        bar_color = f"marker=dict(color=df['{y_col}'].tolist(), colorscale='{colorscale}', showscale=True, line=dict(color='rgba(0,0,0,0.1)', width=0.5), opacity=0.9)"
                        line_color = f"line=dict(color='{color}', width=2.5), marker=dict(size=7, color=df['{y_col}'].tolist(), colorscale='{colorscale}', showscale=False, line=dict(color='white', width=1.5))"
                        scatter_color = f"marker=dict(color=df['{y_col}'].tolist(), colorscale='{colorscale}', showscale=True, size=9, opacity=0.8, line=dict(color='white', width=1))"
                    elif multi_color:
                        # Use a qualitative palette for categories
                        _palette = "['#2563eb','#7c3aed','#db2777','#ea580c','#16a34a','#0891b2','#9333ea','#dc2626','#d97706','#059669','#0284c7','#be185d','#b45309','#15803d','#0e7490']"
                        bar_color = f"marker=dict(color={_palette}[:len(df)], line=dict(color='rgba(0,0,0,0.1)', width=0.5), opacity=0.9)"
                        line_color = f"line=dict(color='{color}', width=2.5), marker=dict(size=7, color={_palette}[:len(df)], line=dict(color='white', width=1.5))"
                        scatter_color = f"marker=dict(color={_palette}[:len(df)], size=9, opacity=0.8, line=dict(color='white', width=1))"
                    else:
                        # Single solid color
                        bar_color = f"marker=dict(color='{color}', line=dict(color='rgba({r},{g},{b},0.3)', width=0.5), opacity=0.9)"
                        line_color = f"line=dict(color='{color}', width=2.5), marker=dict(size=7, color='{color}', line=dict(color='white', width=1.5))"
                        scatter_color = f"marker=dict(color='{color}', size=9, opacity=0.8, line=dict(color='white', width=1))"

                    chart_templates = {
                        'pie': (
                            f"    _pie_colors = ['#2563eb','#7c3aed','#db2777','#ea580c','#16a34a','#0891b2','#9333ea','#dc2626','#d97706','#059669','#0284c7','#be185d','#b45309','#15803d','#0e7490']\n"
                            f"    fig = go.Figure(data=go.Pie(\n"
                            f"        labels=df['{x_col}'].tolist(), values=df['{y_col}'].tolist(),\n"
                            f"        hole=0.4, textinfo='label+percent+value',\n"
                            f"        textfont=dict(size=12),\n"
                            f"        hovertemplate='<b>%{{label}}</b><br>{y_col}: %{{value:,.2f}}<br>Share: %{{percent}}<extra></extra>',\n"
                            f"        marker=dict(colors=_pie_colors[:len(df)], line=dict(color='#ffffff', width=2))\n"
                            f"    ))"
                        ),
                        'line': (
                            f"    fig = go.Figure(data=go.Scatter(\n"
                            f"        x=df['{x_col}'].tolist(), y=df['{y_col}'].tolist(),\n"
                            f"        mode='lines+markers', name='{y_col}',\n"
                            f"        hovertemplate='<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>',\n"
                            f"        {line_color}\n"
                            f"    ))"
                        ),
                        'scatter': (
                            f"    fig = go.Figure(data=go.Scatter(\n"
                            f"        x=df['{x_col}'].tolist(), y=df['{y_col}'].tolist(),\n"
                            f"        mode='markers', name='{y_col}',\n"
                            f"        hovertemplate='<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>',\n"
                            f"        {scatter_color}\n"
                            f"    ))"
                        ),
                        'histogram': (
                            f"    fig = go.Figure(data=go.Histogram(\n"
                            f"        x=df['{x_col}'].tolist(), name='{x_col}',\n"
                            f"        hovertemplate='{x_col}: %{{x}}<br>Count: %{{y}}<extra></extra>',\n"
                            f"        marker_color='{color}', opacity=0.85,\n"
                            f"        marker_line=dict(color='white', width=0.5)\n"
                            f"    ))"
                        ),
                        'area': (
                            f"    fig = go.Figure(data=go.Scatter(\n"
                            f"        x=df['{x_col}'].tolist(), y=df['{y_col}'].tolist(),\n"
                            f"        mode='lines', fill='tozeroy', name='{y_col}',\n"
                            f"        hovertemplate='<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>',\n"
                            f"        line=dict(color='{color}', width=2),\n"
                            f"        fillcolor='rgba({r},{g},{b},0.15)'\n"
                            f"    ))"
                        ),
                        'bar': (
                            f"    fig = go.Figure(data=go.Bar(\n"
                            f"        x=df['{x_col}'].tolist(), y=df['{y_col}'].tolist(),\n"
                            f"        text=[round(float(v), 2) for v in df['{y_col}']],\n"
                            f"        textposition='auto', textfont=dict(size=11),\n"
                            f"        name='{y_col}',\n"
                            f"        hovertemplate='<b>%{{x}}</b><br>{y_col}: %{{y:,.2f}}<extra></extra>',\n"
                            f"        {bar_color}\n"
                            f"    ))"
                        ),
                    }
                    chart_code = chart_templates.get(chart_type, chart_templates['bar'])
                    safe_title = explanation.replace("'", "\\'")

                    python_code = f'''# {explanation}
df = await query_db("""{fixed_query}""")

if df is not None and not df.empty:
    import pandas as _pd
    # Convert all numeric-looking columns — handles MySQL Decimal, string numbers, etc.
    for _c in df.columns:
        try:
            df[_c] = _pd.to_numeric(df[_c], errors='raise')
        except (ValueError, TypeError):
            pass
    df = df.sort_values('{y_col}', ascending=False).head(15)
    df = df.reset_index(drop=True)
{chart_code}
    fig.update_layout(
        title=dict(text='{safe_title}', font=dict(size=16, color='#1e293b'), x=0.02),
        xaxis_title='{x_col}',
        yaxis_title='{y_col}',
        template='plotly_white',
        height=450,
        xaxis_tickangle=-35,
        font=dict(family='system-ui, -apple-system, sans-serif', size=12, color='#374151'),
        plot_bgcolor='#ffffff',
        paper_bgcolor='#ffffff',
        xaxis=dict(showgrid=False, linecolor='#e5e7eb', tickfont=dict(size=11)),
        yaxis=dict(gridcolor='#f3f4f6', linecolor='#e5e7eb', tickfont=dict(size=11)),
        margin=dict(l=60, r=20, t=60, b=80),
        hoverlabel=dict(bgcolor='#1e293b', font_color='white', font_size=12, bordercolor='#1e293b')
    )
else:
    fig = go.Figure()
    print("No data returned")

fig
'''
                else:
                    # Fallback: preview failed — use dtype-based detection at runtime
                    safe_title = explanation.replace("'", "\\'")
                    python_code = f'''# {explanation}
df = await query_db("""{fixed_query}""")

if df is not None and not df.empty:
    import pandas as _pd
    for _c in df.columns:
        try: df[_c] = _pd.to_numeric(df[_c], errors='coerce')
        except: pass
    _num = [c for c in df.columns if df[c].dtype in ['int64','float64','float32','int32']]
    _cat = [c for c in df.columns if c not in _num]
    x_col = _cat[0] if _cat else df.columns[0]
    y_col = _num[0] if _num else (df.columns[1] if len(df.columns) > 1 else df.columns[0])
    df = df.sort_values(y_col, ascending=False).head(15)
    fig = go.Figure(data=go.Bar(
        x=df[x_col], y=df[y_col],
        text=df[y_col], textposition='auto',
        hovertemplate='<b>%{{x}}</b><br>' + y_col + ': %{{y:,.2f}}<extra></extra>',
        marker_color='#2563eb'
    ))
    fig.update_layout(
        title='{safe_title}',
        xaxis_title=x_col, yaxis_title=y_col,
        template='plotly_white', height=450, xaxis_tickangle=-35
    )
else:
    fig = go.Figure()
    print("No data returned")

fig
'''
                python_code = self._sanitize_for_pyodide(python_code, fix_charts=False)
                python_code = self._inject_micropip_guards(python_code)

                # Build a meaningful chart summary for the chat panel
                chart_summary = self._build_chart_summary(
                    explanation, chart_type, x_col, y_col, fixed_query, preview_data
                )
                return {"answer": f"{chart_summary}\n\n```python\n{python_code}\n```", "tool_used": "Generate Code", "trace": fixed_query, "raw_data": []}

            elif wants_notebook_code:
                fixed_query = self._validate_and_fix_sql(self._fix_table_names(sql_query))
                python_code = f"""# {explanation}
df = await query_db('''{fixed_query}''')
if df is not None and not df.empty:
    print("Results: " + str(len(df)) + " rows")
else:
    print("âš ï¸ No data returned.")
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
    print("âš ï¸ No data returned. Try checking filters or date ranges.")
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
            retrieved = vector_store.search(qv, n_results=3)
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

    def _detect_chart_style(self, user_query: str) -> dict:
        """
        Extract color and style preferences from the user query.
        Returns a dict with 'color', 'colorscale', and 'multi_color' keys.
        """
        q = user_query.lower()

        # Named color → hex map
        color_map = {
            'red':       '#ef4444', 'crimson':   '#dc2626', 'pink':      '#ec4899',
            'orange':    '#f97316', 'amber':     '#f59e0b', 'yellow':    '#eab308',
            'green':     '#22c55e', 'emerald':   '#10b981', 'teal':      '#14b8a6',
            'cyan':      '#06b6d4', 'sky':       '#0ea5e9', 'blue':      '#3b82f6',
            'indigo':    '#6366f1', 'violet':    '#8b5cf6', 'purple':    '#a855f7',
            'fuchsia':   '#d946ef', 'rose':      '#f43f5e', 'slate':     '#64748b',
            'gray':      '#6b7280', 'grey':      '#6b7280', 'black':     '#1e293b',
            'white':     '#f8fafc', 'navy':      '#1e3a5f', 'coral':     '#ff6b6b',
            'gold':      '#fbbf24', 'silver':    '#94a3b8', 'brown':     '#92400e',
            'lime':      '#84cc16', 'mint':      '#6ee7b7', 'lavender':  '#c4b5fd',
        }

        # Colorscale keywords → Plotly colorscale names
        colorscale_map = {
            'rainbow': 'Rainbow', 'viridis': 'Viridis', 'plasma': 'Plasma',
            'inferno': 'Inferno', 'magma': 'Magma', 'turbo': 'Turbo',
            'blues': 'Blues', 'reds': 'Reds', 'greens': 'Greens',
            'sunset': 'Sunset', 'sunsetdark': 'Sunsetdark', 'rdbu': 'RdBu',
            'spectral': 'Spectral', 'portland': 'Portland', 'jet': 'Jet',
        }

        # Multi-color / color-by-category keywords
        multi_color_keywords = ['color by', 'colour by', 'colored by', 'coloured by',
                                 'different color', 'different colour', 'each color',
                                 'each colour', 'colorful', 'colourful', 'multi color',
                                 'multi colour', 'rainbow', 'varied color', 'varied colour']

        result = {
            'color': '#2563eb',       # default blue
            'colorscale': None,
            'multi_color': False,
        }

        # Check for multi-color request
        if any(kw in q for kw in multi_color_keywords):
            result['multi_color'] = True
            result['color'] = None  # will use colorscale

        # Check for colorscale
        for kw, cs in colorscale_map.items():
            if kw in q:
                result['colorscale'] = cs
                result['multi_color'] = True
                result['color'] = None
                break

        # Check for named color (only if not already multi-color)
        if not result['multi_color']:
            for name, hex_val in color_map.items():
                if re.search(r'\b' + name + r'\b', q):
                    result['color'] = hex_val
                    break

        return result
