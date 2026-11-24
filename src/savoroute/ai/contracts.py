"""Strict user-input and model-output contracts for opt-in food interpretation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# JSON/base64 transport is deliberately capped; no user image is written to disk.
MAX_BODY_BYTES = 5_800_000
MAX_IMAGE_BYTES = 4_000_000
MAX_IMAGE_PIXELS = 12_000_000
MAX_PROVIDER_OUTPUT_BYTES = 32_000

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InterpretInput(StrictModel):
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    # Raw base64, not a data URL. The server validates actual image bytes.
    image_base64: Annotated[str, Field(max_length=5_400_000)] | None = None
    consent_remote_processing: Literal[True]

    @model_validator(mode="after")
    def has_input(self) -> InterpretInput:
        if not self.prompt and not self.image_base64:
            raise ValueError("Provide a prompt or an image")
        return self


class FoodInterpretation(StrictModel):
    # Treat every field as a fallible hypothesis, not verified evidence.
    search_query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
    dishes: Annotated[list[ShortText], Field(max_length=5)]
    cuisines: Annotated[list[ShortText], Field(max_length=5)]
    ingredients: Annotated[list[ShortText], Field(max_length=8)]
    uncertainties: Annotated[list[ShortText], Field(max_length=5)]


class InterpretOutput(StrictModel):
    api_version: Literal["v1"] = "v1"
    provider: Literal["openai"] | str
    interpretation: FoodInterpretation
    catalog_verified: Literal[False] = False
    limitations: str = (
        "Model-generated food hypotheses, not verified dish identification, menu availability, "
        "restaurant endorsement, nutrition, dietary suitability or allergen safety. "
        "Confirm or edit the suggested search before searching the catalog."
    )


class AIStatusOutput(StrictModel):
    api_version: Literal["v1"] = "v1"
    enabled: bool
    input_types: list[Literal["text", "image"]]
    consent_required: Literal[True] = True
    limitations: str = "Opt-in external processing; no local AI interpretation when disabled."
