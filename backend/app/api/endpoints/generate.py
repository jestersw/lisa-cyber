from fastapi import APIRouter, HTTPException

from app.llm import LLMError, build_prompt, generate_plugin, get_provider, parse_template
from app.schemas import (
    PluginGenerationRequest,
    PluginGenerationResponse,
    TemplateGenerationRequest,
    TemplateGenerationResponse,
)

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


@router.post("/application-templates/generate", response_model=PluginGenerationResponse)
def generate_application_plugin(req: PluginGenerationRequest):
    plugin = generate_plugin(req.name, req.os_type.value, req.description)
    if plugin is None:
        raise HTTPException(
            status_code=422,
            detail="Model returned invalid plugin JSON or the provider is unavailable",
        )
    return PluginGenerationResponse(
        name=req.name,
        os_type=req.os_type,
        template_config=plugin,
        source="llm",
    )
