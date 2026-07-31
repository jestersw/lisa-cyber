from fastapi import APIRouter, HTTPException

from app.llm import LLMError, build_prompt, get_provider, parse_template
from app.schemas import TemplateGenerationRequest, TemplateGenerationResponse

router = APIRouter()


@router.post("/behavior-templates/generate", response_model=TemplateGenerationResponse)
def generate_template(req: TemplateGenerationRequest):
    prompt = build_prompt(req.description, req.os_type.value)
    try:
        raw = get_provider().generate(prompt)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=f"LLM provider unavailable: {exc}") from exc

    template_data = parse_template(raw)
    if template_data is None:
        raise HTTPException(status_code=422, detail="Model returned invalid template JSON")

    return TemplateGenerationResponse(
        name=req.name or f"{req.description[:40]} (draft)",
        os_type=req.os_type,
        template_data=template_data,
        source="llm",
    )
