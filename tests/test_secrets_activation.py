from shared.secrets_state import SecretsState


def test_activation_code_flow(tmp_path):
    st = SecretsState(tmp_path / "secrets.enc", tmp_path / "master.json")
    st.initialize({"master_password": "mp", "llm_provider": "stub"})
    assert st.unlock("mp")

    code = st.create_activation_code("llm", "123")
    assert len(code) == 5
    assert st.activate_with_code("llm", "wrong") is None
    uid = st.activate_with_code("llm", code)
    assert uid == "123"
    assert st.get_bound_user("llm") == "123"
    assert st.is_user_allowed_for_bot("llm", "123") is True
