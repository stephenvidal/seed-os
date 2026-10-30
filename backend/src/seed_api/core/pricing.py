"""What a model's tokens cost (D-035). Prices are configuration: they change."""

from pydantic import BaseModel, Field

from .messages import Usage


class ModelPrice(BaseModel):
    """US dollars per million tokens."""

    input_per_m: float = Field(ge=0)
    output_per_m: float = Field(ge=0)

    def cost(self, usage: Usage) -> float:
        return (
            usage.input_tokens * self.input_per_m + usage.output_tokens * self.output_per_m
        ) / 1_000_000


# Ollama Cloud's published list price (D-014). The off-peak half price and the
# cached-input rate are ignored, so a cost here is never below what is billed.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "deepseek-v4.1-flash": ModelPrice(input_per_m=0.30, output_per_m=1.20),
}
