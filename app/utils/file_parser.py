import io
import pypdf
import docx

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
        elif filename_lower.endswith(('.txt', '.csv', '.py', '.js', '.json', '.ipynb', '.html', '.css', '.md')):
            # Code, JSON, Python Notebooks, Markdown, and tabular files can all be decoded directly to UTF-8
            return file_content.decode('utf-8', errors='ignore')
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
