import io
import pypdf
import docx
import pandas as pd
def extract_text_from_file(file_content: bytes, filename: str) -> str:
    """
    Extracts text from PDF, DOCX, or TXT content.
    """
    filename_lower = filename.lower()
    
    try:
        if filename_lower.endswith('.pdf'):
            return _extract_from_pdf(file_content)
        elif filename_lower.endswith('.docx'):
            return _extract_from_docx(file_content)
        elif filename_lower.endswith(('.xls', '.xlsx')):
            return _extract_from_excel(file_content)
        elif filename_lower.endswith(('.txt', '.csv', '.py', '.js', '.json', '.ipynb', '.html', '.css', '.md')):
            # Code, JSON, Python Notebooks, Markdown, and tabular files can all be decoded directly to UTF-8
            return file_content.decode('utf-8', errors='ignore')
        elif filename_lower.endswith(('.png', '.jpg', '.jpeg', '.webp')):
            return f"[Image File: {filename} - Please use the AI Chat window upload to visually analyze images.]"
        else:
            return f"Unsupported file type: {filename}"
    except Exception as e:
        return f"Error extracting text: {str(e)}"

def _extract_from_pdf(content: bytes) -> str:
    text = ""
    with io.BytesIO(content) as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text

def _extract_from_docx(content: bytes) -> str:
    text = ""
    with io.BytesIO(content) as f:
        doc = docx.Document(f)
        for para in doc.paragraphs:
            text += para.text + "\n"
    return text

def _extract_from_excel(content: bytes) -> str:
    text = ""
    try:
        with io.BytesIO(content) as f:
            df_dict = pd.read_excel(f, sheet_name=None)
            for sheet_name, df in df_dict.items():
                text += f"--- Sheet: {sheet_name} ---\n"
                text += df.to_csv(index=False) + "\n"
    except Exception as e:
        text += f"Error parsing excel file: {str(e)}"
    return text

def is_structured_file(filename: str) -> bool:
    """Returns True if the file contains tabular/structured data."""
    return filename.lower().endswith(('.csv', '.xls', '.xlsx', '.json'))

def is_unstructured_file(filename: str) -> bool:
    """Returns True if the file contains unstructured text (good for RAG)."""
    return filename.lower().endswith(('.pdf', '.docx', '.txt', '.md'))

def extract_structured_metadata(content: bytes, filename: str) -> str:
    """Extracts columns and sample data for AI context to save tokens."""
    try:
        ext = filename.lower()
        df = None
        if ext.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content), nrows=5)
        elif ext.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content), nrows=5)
        elif ext.endswith('.json'):
            try:
                df = pd.read_json(io.BytesIO(content))
                df = df.head(5)
            except ValueError:
                return "JSON data (non-tabular)"
        
        if df is not None:
            info = f"Columns: {', '.join(str(c) for c in df.columns.tolist())}\n"
            info += f"Sample Data (First 5 Rows):\n{df.to_csv(index=False)}\n"
            return info
            
    except Exception as e:
        print(f"Metadata extraction error: {e}")
        
    return "Structured dataset. Full content available in context."
