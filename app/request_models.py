from pydantic import BaseModel, Field
from typing import List, Any, Optional

class QueryRequest(BaseModel):
    # Ensures the prompt is a string and is not empty
    prompt: str = Field(..., min_length=1, description="The user's natural language question")
    # NEW: List of notebook cell contents (each string is a cell's code)
    notebook_cells: List[str] = Field(default_factory=list, description="Contents of the active notebook cells")
    # Existing: Active variables from browser memory
    variables: List[str] = Field(default_factory=list, description="Active variables in browser memory")
    chat_history: List[Any] = Field(default_factory=list, description="Previous chat messages")
    images: List[str] = Field(default_factory=list) # <--- NEW FIELD
    datasets: List[Any] = Field(default_factory=list) # <--- NEW FIELD FOR TEXT FILES

    # --- NEW FIELDS FOR MODIFICATION ---
    is_modification: bool = False
    original_code: Optional[str] = None
    active_cell_id: Optional[str] = None


# This model defines the structure of the data going TO the Frontend
class QueryResponse(BaseModel):
    answer: str
    tool_used: str
    trace: str
    raw_data: List[Any]