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
