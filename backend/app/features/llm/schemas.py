from pydantic import BaseModel, Field


class GroundedAnswerRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    context: str = Field(min_length=1, max_length=60_000)


class GroundedAnswerResponse(BaseModel):
    answer: str
    model: str
