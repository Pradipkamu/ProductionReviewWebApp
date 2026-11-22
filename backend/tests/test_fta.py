import pytest
from fastapi import HTTPException

from app.api.fta import _decorate_tree, _validate_tree


def _node(node_id, status="NOT_INVESTIGATED"):
    return {"id": node_id, "label": node_id, "type": "BASIC_EVENT", "gate": None, "children": []}


def test_fta_or_gate_is_satisfied_when_one_child_is_confirmed():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "CONFIRMED", "b": "NOT_INVESTIGATED"})
    assert result["logic_state"] == "SATISFIED"


def test_fta_and_gate_requires_all_children_confirmed():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "AND",
        "children": [_node("a"), _node("b")],
    }
    partial = _decorate_tree(tree, {"a": "CONFIRMED", "b": "SUSPECTED"})
    complete = _decorate_tree(tree, {"a": "CONFIRMED", "b": "CONFIRMED"})
    assert partial["logic_state"] == "UNKNOWN"
    assert complete["logic_state"] == "SATISFIED"


def test_fta_gate_is_not_satisfied_when_all_or_children_are_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "RULED_OUT", "b": "RULED_OUT"})
    assert result["logic_state"] == "NOT_SATISFIED"


def test_fta_template_requires_unique_node_ids_and_valid_gate():
    valid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    assert len(_validate_tree(valid)) == 3
    duplicate = {**valid, "children": [_node("a"), _node("a")]}
    with pytest.raises(HTTPException):
        _validate_tree(duplicate)
    invalid_gate = {**valid, "gate": "XOR"}
    with pytest.raises(HTTPException):
        _validate_tree(invalid_gate)


def test_fta_tree_rejects_non_top_event_root():
    with pytest.raises(HTTPException):
        _validate_tree(_node("leaf"))


def test_fta_tree_rejects_empty_node_label():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{"id": "cause", "label": " ", "type": "BASIC_EVENT", "gate": None, "children": []}],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_tree_rejects_nodes_without_logic_gate():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": None,
        "children": [_node("cause")],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_and_gate_is_not_satisfied_when_one_child_is_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "AND",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "CONFIRMED", "b": "RULED_OUT"})
    assert result["logic_state"] == "NOT_SATISFIED"


def test_fta_or_gate_remains_unknown_until_a_cause_is_confirmed_or_all_ruled_out():
    tree = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [_node("a"), _node("b")],
    }
    result = _decorate_tree(tree, {"a": "SUSPECTED", "b": "NOT_INVESTIGATED"})
    assert result["logic_state"] == "UNKNOWN"


def test_fta_only_leaf_cause_nodes_can_be_classified_as_causes():
    from app.api.fta import _validate_cause_classification, FindingUpdate

    payload = FindingUpdate(
        investigation_status="CONFIRMED",
        verification_method="Micrometer measurement",
        is_root_cause=True,
    )
    _validate_cause_classification("BASIC_EVENT", payload)
    _validate_cause_classification("EXTERNAL_EVENT", payload)
    with pytest.raises(HTTPException):
        _validate_cause_classification("TOP_EVENT", payload)
    with pytest.raises(HTTPException):
        _validate_cause_classification("INTERMEDIATE_EVENT", payload)


def test_fta_cause_classification_requires_confirmed_status():
    from app.api.fta import _validate_cause_classification, FindingUpdate

    payload = FindingUpdate(
        investigation_status="SUSPECTED",
        is_root_cause=True,
    )
    with pytest.raises(HTTPException):
        _validate_cause_classification("BASIC_EVENT", payload)



def test_fta_action_link_requires_all_contexts_to_match_investigation_plant():
    from app.api.fta import _validate_action_plants

    _validate_action_plants("2020", {"2020"})
    _validate_action_plants("2020", set())
    with pytest.raises(HTTPException):
        _validate_action_plants("2020", {"2070"})
    with pytest.raises(HTTPException):
        _validate_action_plants("2020", {"2020", "2070"})
    with pytest.raises(HTTPException):
        _validate_action_plants(None, {"2020"})


def test_fta_active_investigation_unique_index_excludes_closed_records():
    from app.models import FtaInvestigation

    index = next(
        item for item in FtaInvestigation.__table__.indexes
        if item.name == "uq_fta_open_rejection_template"
    )
    assert index.unique is True
    assert "CLOSED" in str(index.dialect_options["sqlite"]["where"])


def test_fta_investigation_model_has_no_duplicate_index_names():
    from app.models import FtaInvestigation

    names = [index.name for index in FtaInvestigation.__table__.indexes]
    assert len(names) == len(set(names))
    assert "ix_fta_investigations_status" in names
    assert "ix_fta_investigations_plant" in names
    assert "uq_fta_open_rejection_template" in names


def test_fta_tree_rejects_children_on_leaf_event_nodes():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "basic", "label": "Basic cause", "type": "BASIC_EVENT", "gate": "OR",
            "children": [_node("nested")],
        }],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)


def test_fta_tree_requires_children_for_intermediate_events():
    invalid = {
        "id": "top", "label": "Top event", "type": "TOP_EVENT", "gate": "OR",
        "children": [{
            "id": "intermediate", "label": "Intermediate event",
            "type": "INTERMEDIATE_EVENT", "gate": None, "children": [],
        }],
    }
    with pytest.raises(HTTPException):
        _validate_tree(invalid)
