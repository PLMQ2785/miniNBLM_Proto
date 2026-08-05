from openai import OpenAI

from app.config import settings


class VLLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or settings.vllm_model
        self.client = OpenAI(
            base_url=base_url or settings.vllm_base_url,
            api_key=api_key or settings.vllm_api_key,
        )

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
