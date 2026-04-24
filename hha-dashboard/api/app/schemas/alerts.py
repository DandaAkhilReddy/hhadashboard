from pydantic import BaseModel


class Alert(BaseModel):
    id: str
    severity: str  # "red" | "yellow" | "blue"
    category: str  # "finance" | "operations" | "clinical" | "people"
    title: str
    detail: str
    owner: str


class Meta(BaseModel):
    generated_at: str
    data_source: str
    note: str
