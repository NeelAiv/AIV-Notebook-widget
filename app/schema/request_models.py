from pydantic import BaseModel, Field
from typing import List, Any, Optional

# This model validates the data coming FROM the Frontend (JavaScript)
class QueryRequest(BaseModel):
    # Ensures the prompt is a string and is not empty
    prompt: str = Field(..., min_length=1, description="The user's natural language question")

# This model defines the structure of the data going TO the Frontend
class QueryResponse(BaseModel):
    answer: str
    tool_used: str
    trace: str
    raw_data: List[Any]