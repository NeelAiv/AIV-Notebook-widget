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
