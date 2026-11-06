"""Default JD and criteria, used when resumes are scored without a job description.

Edit backend/defaults/default_jd.txt and default_criteria.json (or point DEFAULT_JD_FILE /
DEFAULT_CRITERIA_FILE elsewhere). The criteria weights must add up to 100. Files are re-read on each
request, so edits apply without restarting the backend.
"""
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from models.schemas import Rubric

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class DefaultsError(Exception):
    pass


@dataclass
class Defaults:
    jd_text: str
    rubric: Rubric


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else _BACKEND_DIR / p


def load_defaults(settings: Settings) -> Defaults:
    jd_path, criteria_path = _resolve(settings.default_jd_file), _resolve(settings.default_criteria_file)
    try:
        jd_text = jd_path.read_text(encoding="utf-8").strip()
        rubric = Rubric.model_validate_json(criteria_path.read_bytes())
    except OSError as e:
        raise DefaultsError(f"Can't read the default JD or criteria: {e}") from e
    except ValidationError as e:
        msg = "; ".join(err["msg"] for err in e.errors()[:3])
        raise DefaultsError(f"{criteria_path.name} is not valid criteria: {msg}") from e
    if not jd_text:
        raise DefaultsError(f"{jd_path.name} is empty")
    return Defaults(jd_text=jd_text, rubric=rubric)
