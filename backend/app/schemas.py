from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class OSType(str, Enum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


class RoleBase(BaseModel):
    name: str
    description: str
    category: str


class RoleCreate(RoleBase):
    pass


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    is_active: bool | None = None


class RoleResponse(RoleBase):
    id: int
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BehaviorTemplateBase(BaseModel):
    name: str
    description: str | None = None
    role_id: int
    template_data: dict
    os_type: OSType = OSType.LINUX
    version: str = "1.0"


class BehaviorTemplateCreate(BehaviorTemplateBase):
    pass


class BehaviorTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    role_id: int | None = None
    template_data: dict | None = None
    os_type: OSType | None = None
    version: str | None = None
    is_active: bool | None = None


class BehaviorTemplateResponse(BehaviorTemplateBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ApplicationTemplateBase(BaseModel):
    name: str
    display_name: str | None = None
    category: str | None = None
    description: str | None = None
    version: str = "1.0"
    author: str | None = None
    template_config: dict
    os_type: OSType = OSType.LINUX


class ApplicationTemplateCreate(ApplicationTemplateBase):
    pass


class ApplicationTemplateUpdate(BaseModel):
    name: str | None = None
    display_name: str | None = None
    category: str | None = None
    description: str | None = None
    version: str | None = None
    author: str | None = None
    template_config: dict | None = None
    os_type: OSType | None = None
    is_active: bool | None = None


class ApplicationTemplateResponse(ApplicationTemplateBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AgentConfig(BaseModel):
    name: str
    role_id: int
    template_id: int
    os_type: OSType
    injection_target: str | None = None
    custom_config: dict = Field(default_factory=dict)
    schedule: dict | None = None
    behavior: dict | None = None
    heartbeat_interval_minutes: int | None = None
    applications: list[str] | None = None


class AgentGenerateResponse(BaseModel):
    agent_id: str
    message: str
    config: dict
    config_url: str
    status_url: str


class AgentResponse(BaseModel):
    id: int
    agent_id: str
    name: str
    status: str
    os_type: str
    last_seen: datetime | None = None
    created_at: datetime
    version_info: dict | None = None
    template_id: int | None = None
    role_id: int | None = None
    injection_target: str | None = None
    model_config = ConfigDict(from_attributes=True)


class AgentConfigResponse(BaseModel):
    agent_id: str
    name: str
    os_type: str
    role: dict
    behavior_template: dict
    server_url: str
    heartbeat_interval: int
    version: str


class AgentHeartbeatRequest(BaseModel):
    agent_id: str
    status: str = "active"
    timestamp: datetime | None = None
    system_info: dict = Field(default_factory=dict)
    current_activity: dict | None = None
    statistics: dict | None = None
    version: str | None = None


class AgentHeartbeatResponse(BaseModel):
    status: str
    agent_id: str
    timestamp: datetime
    message: str
    next_heartbeat_in: int
    commands: list[dict] = Field(default_factory=list)


class ActivityLog(BaseModel):
    id: int
    activity_type: str
    activity_data: dict | None = None
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class ActivityEventCreate(BaseModel):
    app: str
    activity_type: str
    timestamp: datetime
    duration_seconds: float | None = None
    role: str | None = None
    context: dict | None = None


class ActivityEventBatch(BaseModel):
    events: list[ActivityEventCreate]


class ActivityEventResponse(ActivityEventCreate):
    id: int
    agent_id: int | None = None
    model_config = ConfigDict(from_attributes=True)


class GeneratedTemplate(BaseModel):
    applications_used: list[str] = Field(min_length=1)
    work_start: str = "09:00"
    work_end: str = "18:00"
    activities: list[str] = Field(default_factory=list)


class TemplateGenerationRequest(BaseModel):
    description: str
    os_type: OSType = OSType.LINUX
    name: str | None = None


class TemplateGenerationResponse(BaseModel):
    name: str
    os_type: OSType
    template_data: dict
    source: str


class TimeRange(BaseModel):
    min: int
    max: int


class LunchWindow(BaseModel):
    earliest: str = "13:00"
    latest: str = "15:00"
    min_minutes: int = 45
    max_minutes: int = 75


class ScheduleSpec(BaseModel):
    workdays: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    work_start: str
    work_end: str
    lunch: LunchWindow = Field(default_factory=LunchWindow)


class BehaviorSpec(BaseModel):
    session_duration: TimeRange
    app_switch_pause: TimeRange
    inactive_period: TimeRange


class HeartbeatSpec(BaseModel):
    interval_minutes: int = 30


class AgentInfo(BaseModel):
    agent_id: str
    name: str
    role: str
    os_type: OSType


class AgentConfigSpec(BaseModel):
    agent_info: AgentInfo
    schedule: ScheduleSpec
    behavior: BehaviorSpec
    heartbeat: HeartbeatSpec
    applications: list[str]


class DeploymentPackage(BaseModel):
    agent_config: AgentConfigSpec
    application_plugins: dict[str, dict]
