from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Key = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")]
BoundText = Annotated[str, StringConstraints(max_length=16000)]
Reference = Annotated[str, StringConstraints(max_length=256)]
Scalar = str | bool | int | float | None


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Citation(Record):
    asset_id: Key
    location: Reference


class Answer(Record):
    decision: Literal["answer", "abstain", "escalate"]
    values: dict[Key, Scalar] = Field(default_factory=dict, max_length=100)
    citations: list[Citation] = Field(default_factory=list, max_length=100)


class Action(Record):
    operation: Key
    target: Key


class Execution(Record):
    events: list[Action] = Field(max_length=1000)
    final_state: dict[Key, JsonValue] = Field(max_length=100)


class Case(Record):
    id: Key
    scenario: BoundText
    rule: BoundText
    remediation: BoundText
    critical: bool = False
    answer: Answer | None = None
    state: dict[Key, JsonValue] | None = None
    ordered_actions: list[Action] = Field(default_factory=list)
    allowed_actions: list[Action] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_expectation(self):
        if (self.answer is None) == (self.state is None):
            raise ValueError("Each case must specify one answer or execution expectation.")
        if self.answer is not None and (self.ordered_actions or self.allowed_actions):
            raise ValueError("Answer cases cannot have execution expectations.")
        return self


class Dataset(Record):
    id: Key
    version: Key
    cases: list[Case] = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case ID.")
        return self


class Observation(Record):
    case_id: Key
    answer: Answer | None = None
    execution: Execution | None = None
    infrastructure_error: Key | None = None

    @model_validator(mode="after")
    def check_observation(self):
        if sum(value is not None for value in
               (self.answer, self.execution, self.infrastructure_error)) != 1:
            raise ValueError("Provide one answer, execution or infrastructure error.")
        return self


class Run(Record):
    dataset_id: Key
    dataset_version: Key
    subject_version: Key
    conditions_id: Key
    observations: list[Observation] = Field(max_length=250)
