from pydantic import BaseModel, Field
from typing import List, Any, Optional, Union

class QueryRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    notebook_cells: List[Union[str, dict]] = Field(default_factory=list)  # Accept both string and dict formats
    variables: List[str] = Field(default_factory=list)
    chat_history: List[Any] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    datasets: List[Any] = Field(default_factory=list)
    use_db_context: bool = True
    use_rag_context: bool = False
    is_modification: bool = False
    original_code: Optional[str] = None
    active_cell_id: Optional[str] = None


# This model defines the structure of the data going TO the Frontend
class QueryResponse(BaseModel):
    answer: str
    tool_used: str
    trace: str
    raw_data: List[Any]