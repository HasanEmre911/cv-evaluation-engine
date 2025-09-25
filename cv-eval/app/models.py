from pydantic import BaseModel
from typing import List

class CVParsed(BaseModel):
    skills: List[str]
    experience_years: float
    education_level: str  # "phd" | "msc" | "bsc" | "bootcamp" | "other"

class ScoreBreakdown(BaseModel):
    skills_points: int
    experience_points: int
    education_points: int
    total: int
