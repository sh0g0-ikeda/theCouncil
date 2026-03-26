from pydantic import BaseModel, Field

REPORT_REASON_PATTERN = "^(hate|violence|defamation|crime|other)$"


class CreateReportRequest(BaseModel):
    reason: str = Field(pattern=REPORT_REASON_PATTERN)
