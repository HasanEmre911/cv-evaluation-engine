from app.models import CVParsed, ScoreBreakdown

SKILL_WHITELIST = {
    "python","sql","pandas","numpy","scikit-learn",
    "pytorch","tensorflow","fastapi","flask","django",
    "docker","kubernetes","aws","gcp","azure",
}

EDUCATION_MAP = {"phd":20, "msc":16, "bsc":12, "bootcamp":8, "other":5}

def score_cv(parsed: CVParsed) -> ScoreBreakdown:
    found = [s for s in parsed.skills if s.lower() in SKILL_WHITELIST]
    skills_points = min(len(found), 10) * 5
    exp_points    = min(int(round(parsed.experience_years * 3)), 30)
    edu_points    = EDUCATION_MAP.get((parsed.education_level or "other").lower(), 5)
    total = skills_points + exp_points + edu_points
    return ScoreBreakdown(
        skills_points=skills_points,
        experience_points=exp_points,
        education_points=edu_points,
        total=total,
    )
