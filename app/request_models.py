# --- START OF FILE request_models.py (MODIFIED) ---

from pydantic import BaseModel, Field
from typing import List, Any, Optional

# This model validates the data coming FROM the Frontend (JavaScript)
class QueryRequest(BaseModel):
    # Ensures the prompt is a string and is not empty
    prompt: str = Field(..., min_length=1, description="The user's natural language question")
    # NEW: List of notebook cell contents (each string is a cell's code)
    notebook_cells: List[str] = Field(default_factory=list, description="Contents of the active notebook cells")
    # Existing: Active variables from browser memory
    variables: List[str] = Field(default_factory=list, description="Active variables in browser memory")
    # NEW: Chat history for context
    chat_history: List[Any] = Field(default_factory=list, description="Previous chat messages")


# This model defines the structure of the data going TO the Frontend
class QueryResponse(BaseModel):
    answer: str
    tool_used: str
    trace: str
    raw_data: List[Any]