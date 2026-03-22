from typing import List, Literal

from pydantic import BaseModel, ValidationError


class RangeCm(BaseModel):
    min: float
    max: float


class RangeMm(BaseModel):
    min: float
    max: float


class RangeTimes(BaseModel):
    min: float
    max: float


class Design(BaseModel):
    designSize: Literal["Micro", "Small", "Medium", "Large", "Full Size"]
    designSizeRangeCm: RangeCm
    designStyle: Literal["Regular", "Gradational", "Fil-a-Fil", "Counter", "Multicolor", "Solid"]
    weave: Literal["Plain", "Twill", "Oxford", "Dobby"]


class Stripe(BaseModel):
    stripeSizeRangeMm: RangeMm
    stripeMultiplyRange: RangeTimes
    isSymmetry: bool


class ColorItem(BaseModel):
    name: str
    percentage: float


class Visual(BaseModel):
    contrastLevel: Literal["Low", "Medium", "High"]


class Market(BaseModel):
    occasion: Literal["Formal", "Casual", "Party Wear"]


class Technical(BaseModel):
    yarnCount: Literal["20s", "30s", "40s", "50s", "60s", "80s/2", "100s/2"]
    construction: str
    gsm: float
    epi: float
    ppi: float


class TextileDesignResponse(BaseModel):
    design: Design
    stripe: Stripe
    colors: List[ColorItem]
    visual: Visual
    market: Market
    technical: Technical


def validate_textile_payload(payload: dict):
    """Return (parsed_model, None) when valid else (None, error_message)."""
    try:
        return TextileDesignResponse.model_validate(payload), None
    except ValidationError as exc:
        first_error = exc.errors()[0] if exc.errors() else {"msg": str(exc)}
        return None, first_error.get("msg", str(exc))
