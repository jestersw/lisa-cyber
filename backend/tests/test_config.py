from app.config import Settings


def test_blank_secrets_are_unset():
    # docker-compose injects these as empty strings when not provided; the auth
    # layer treats None as dev-mode-open, so blanks must normalise to None.
    s = Settings(operator_password="", jwt_secret="   ", agent_token="", llm_api_key="")
    assert s.operator_password is None
    assert s.jwt_secret is None
    assert s.agent_token is None
    assert s.llm_api_key is None


def test_real_secrets_are_kept():
    s = Settings(operator_password="hunter2", agent_token="tok")
    assert s.operator_password == "hunter2"
    assert s.agent_token == "tok"
